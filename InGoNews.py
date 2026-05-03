import cloudscraper
import requests
import time
import re
import os
from datetime import datetime
from deep_translator import GoogleTranslator
import threading
import telebot
import feedparser
from google import genai 
from bs4 import BeautifulSoup

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN") 
CHAT_ID = os.getenv("CHAT_ID") 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash" # తాజా మోడల్ కి మార్చబడింది

# --- LOG ---
def log(msg, level="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

# --- DATA ---
rss_news_store = []
sent_links = set()

# --- HELPERS ---
def translate(text):
    try:
        return GoogleTranslator(source='auto', target='te').translate(text)
    except:
        return text

def send_long_message(chat_id, text):
    """
    మెసేజ్ లో Markdown ఎర్రర్స్ ఉంటే వాటిని ప్లెయిన్ టెక్స్ట్ గా పంపుతుంది.
    """
    for i in range(0, len(text), 4000):
        part = text[i:i+4000]
        try:
            bot.send_message(chat_id, part, parse_mode='Markdown', disable_web_page_preview=False)
        except Exception as e:
            # Markdown వల్ల ఎర్రర్ వస్తే, ఎటువంటి ఫార్మాటింగ్ లేకుండా పంపుతుంది
            log(f"⚠️ Markdown parsing failed, sending as plain text: {e}", "WARNING")
            bot.send_message(chat_id, part, disable_web_page_preview=False)

# --- FETCH RSS (Memory Management Included) ---
def fetch_rss():
    global rss_news_store, sent_links
    log("🌍 RSS checking started...")
    
    # మెమరీ క్లీనింగ్: 5000 వార్తలు దాటితే పాత 1000 వార్తలు క్లియర్ అవుతాయి
    if len(rss_news_store) >= 5000:
        log("🧹 Memory cleaning: Removing oldest 1000 items...")
        rss_news_store = rss_news_store[1000:]
        
        if len(sent_links) > 6000:
            sent_links = set(list(sent_links)[-5000:])
    
    RSS_FEEDS = {
        "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
        "CNBC": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml",
        "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "NDTV News": "https://feeds.feedburner.com/ndtvnews-top-stories",
        "Bloomberg": "https://feeds.bloomberg.com/markets/news.rss"
    }

    for name, url in RSS_FEEDS.items():
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(res.content)
            
            for entry in feed.entries[:10]:
                link = entry.get("link", "")
                if not link or link in sent_links:
                    continue

                sent_links.add(link)
                title = entry.get("title", "")
                summary_raw = entry.get("summary") or entry.get("description") or ""
                clean_desc = re.sub('<[^>]+>', '', summary_raw).replace("\n", " ").strip()
                
                tel_title = translate(title)
                tel_desc = translate(clean_desc[:800]) if len(clean_desc) > 10 else "పూర్తి వివరాల కోసం క్రింది లింక్ క్లిక్ చేయండి."

                google_translate_url = f"https://translate.google.com/translate?sl=en&tl=te&u={link}"

                msg = (
                    f"[\u200b]({link})" 
                    f"📌 *{tel_title}*\n\n"
                    f"🇬🇧 *English Title:*\n{title}\n\n"
                    f"🇮🇳 *తెలుగు సమ్మరీ:*\n{tel_desc}\n\n"
                    f"🌐 *{name}* | 🔗 [Read More in Telugu]({google_translate_url})"
                )

                rss_news_store.append(title + " " + clean_desc)
                send_long_message(CHAT_ID, msg)
                time.sleep(1)

        except Exception as e:
            log(f"❌ RSS Error {name}: {e}", "ERROR")

# --- AI SUMMARY COMMAND ---
@bot.message_handler(commands=['summary'])
def summary(message):
    if not rss_news_store:
        bot.reply_to(message, "❌ వార్తలు లేవు")
        return

    bot.send_message(CHAT_ID, "🔍 AI విశ్లేషణ జరుగుతోంది...")
    rss = "\n".join(rss_news_store[-100:])

    prompt = f"""
Please analyze the following news data and provide a detailed market summary in Telugu:

1. 📈 **Nifty & Market Sentiment**: Based on the news, explain the current situation of Nifty 50. Is it bullish, bearish, or sideways? Mention key levels if available.
2. 🚀 **Stock Market & Corporate Analysis**: Highlight important stocks that are in focus and why.
3. 🇮🇳 **National & Policy News**: Key government decisions affecting the economy.
4. 🌍 **Global Trends**: Impact of international markets (US Fed, Crude Oil, etc.) on our market.

Provide actionable insights for traders/investors in a professional Telugu tone.

DATA:
{rss}
"""
    
    try:
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        send_long_message(CHAT_ID, response.text)
    except Exception as e:
        log(f"❌ AI Error: {e}", "ERROR")

# --- LIST COMMAND ---
@bot.message_handler(commands=['list'])
def list_news(message):
    log(f"📋 List command requested")

    if not rss_news_store:
        bot.reply_to(message, "❌ ప్రస్తుతం ఏ వార్తలు లేవు.")
        return

    args = message.text.split()
    try:
        page = int(args[1]) if len(args) > 1 else 1
    except:
        page = 1

    per_page = 20
    total_news = len(rss_news_store)
    total_pages = (total_news + per_page - 1) // per_page

    if page < 1 or page > total_pages:
        bot.reply_to(message, f"❌ పేజీ {page} లేదు.\nమొత్తం {total_pages} పేజీలు ఉన్నాయి.")
        return

    reversed_store = list(reversed(rss_news_store))
    start = (page - 1) * per_page
    page_news = reversed_store[start:start + per_page]

    response = f"📋 ఇటీవలి వార్తలు - పేజీ {page}/{total_pages}\n"
    response += f"📊 మొత్తం వార్తలు: {total_news}\n\n"

    for i, news in enumerate(page_news, start + 1):
        # లిస్ట్ లో వచ్చే టెక్స్ట్ లో టెలిగ్రామ్ ఎర్రర్స్ రాకుండా క్లీన్ చేయడం
        safe_news = news.replace("*", "").replace("_", "").replace("`", "")
        short_news = (safe_news[:120] + "...") if len(safe_news) > 120 else safe_news
        response += f"{i}. {short_news}\n\n"

    response += f"📌 తదుపరి పేజీ చూడాలంటే: /list {page + 1}\n"
    response += f"📌 మొదటి పేజీ: /list"

    send_long_message(CHAT_ID, response)
    log(f"✅ List Page {page} sent")
    
# --- LOOP & BOT START ---
def loop():
    while True:
        try:
            fetch_rss()
        except Exception as e:
            log(f"❌ Loop Error: {e}", "ERROR")
        time.sleep(120)

def start_bot():
    while True:
        try:
            bot.infinity_polling()
        except Exception as e:
            log(f"❌ Polling Error: {e}", "ERROR")
            time.sleep(5)

if __name__ == "__main__":
    # రెండు పనులను వేర్వేరుగా రన్ చేయడం
    threading.Thread(target=loop, daemon=True).start()
    
    log("🚀 Bot Started with New Google GenAI SDK")
    start_bot()
