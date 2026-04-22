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
import google.generativeai as genai
from bs4 import BeautifulSoup

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

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
    for i in range(0, len(text), 4000):
        try:
            bot.send_message(chat_id, text[i:i+4000])
        except Exception as e:
            log(f"❌ Telegram send error: {e}", "ERROR")

# --- RSS FEEDS ---
RSS_FEEDS = {
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "CNBC": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml",
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "NDTV News": "https://feeds.feedburner.com/ndtvnews-top-stories",
    "Bloomberg": "https://feeds.bloomberg.com/markets/news.rss",
    "Yahoo": "https://finance.yahoo.com/news/rssindex"
}

# --- FETCH RSS ---
# --- Yahoo full content scraper ---
def get_yahoo_summary(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.text, "html.parser")
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text() for p in paragraphs[:5]) # మొదటి 5 పేరాలు
        return text[:500] if text else "" 
    except:
        return ""

def fetch_rss():
    log("🌍 RSS checking started...")
    for name, url in RSS_FEEDS.items():
        try:
            log(f"🔗 Fetching: {name}")
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=10)
            
            feed = feedparser.parse(res.content)
            for entry in feed.entries[:10]:
                link = entry.get("link", "")
                if not link or link in sent_links:
                    continue

                sent_links.add(link)
                title = entry.get("title", "")

                # --- Yahoo అయితేనే Scraping చేస్తుంది ---
                if name == "Yahoo":
                    log(f"🔎 Scraping Yahoo link for summary...")
                    clean_desc = get_yahoo_summary(link)
                    if not clean_desc: # స్క్రాపింగ్ ఫెయిల్ అయితే ఫీడ్ లో ఉన్నది తీసుకుంటుంది
                        summary_raw = entry.get("description") or entry.get("summary") or ""
                        clean_desc = re.sub('<[^>]+>', '', summary_raw)
                else:
                    # మిగతా ఫీడ్స్ కి పాత లాజిక్ (వేగంగా ఉంటుంది)
                    summary_raw = entry.get("summary") or entry.get("description") or ""
                    clean_desc = re.sub('<[^>]+>', '', summary_raw)

                clean_desc = clean_desc.replace("\n", " ").strip()
                
                # తెలుగు అనువాదం
                tel_title = translate(title)
                # ఒకవేళ సమ్మరీ అస్సలు దొరకకపోతే టైటిల్ నే సమ్మరీగా వాడదాం
                if not clean_desc or len(clean_desc) < 10:
                    tel_desc = "పూర్తి వివరాల కోసం క్రింది లింక్ క్లిక్ చేయండి."
                else:
                    tel_desc = translate(clean_desc[:800])

                msg = (
                    f"📌 *{tel_title}*\n\n"
                    f"🇬🇧 *English Title:*\n{title}\n\n"
                    f"🇮🇳 *తెలుగు సమ్మరీ:*\n{tel_desc}\n\n"
                    f"🌐 **{name}** | 🔗 [Read More]({link})"
                )

                rss_news_store.append(title + " " + clean_desc)
                send_long_message(CHAT_ID, msg)
                time.sleep(1)

        except Exception as e:
            log(f"❌ RSS Error {name}: {e}", "ERROR")

# --- AI SUMMARY ---
@bot.message_handler(commands=['summary'])
def summary(message):
    if not rss_news_store:
        bot.reply_to(message, "❌ వార్తలు లేవు")
        return

    bot.send_message(CHAT_ID, "🔍 AI విశ్లేషణ జరుగుతోంది...")

    rss = "\n".join(rss_news_store[-100:])

    prompt = f"""
Structure the response into these 3 specific sections:

1. 🚀 Stock Market & Corporate Analysis
2. 🇮🇳 National Business & Policy News
3. 🌍 International Market & Global Trends

Provide detailed analysis in Telugu.
Give clear actionable insights and highlight important stocks if any.

DATA:
{rss}
"""

    try:
        response = model.generate_content(prompt)
        result = response.text

        send_long_message(CHAT_ID, result)
        log("✅ Summary sent")

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
        short_news = (news[:120] + "...") if len(news) > 120 else news
        response += f"{i}. {short_news}\n\n"

    response += f"📌 తదుపరి పేజీ: /list {page + 1}"

    send_long_message(CHAT_ID, response)

# --- LOOP ---
def loop():
    while True:
        log("🔁 New cycle started")
        try:
            fetch_rss()
            log("✅ Cycle completed")
        except Exception as e:
            log(f"❌ Loop Error: {e}", "ERROR")
        time.sleep(120)

# --- BOT ---
def start_bot():
    while True:
        try:
            log("🤖 Bot polling...")
            bot.infinity_polling()
        except Exception as e:
            log(f"❌ Polling Error: {e}", "ERROR")
            time.sleep(5)

# --- MAIN ---
if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=start_bot, daemon=True).start()

    log("🚀 Bot Started Successfully")

    while True:
        time.sleep(60)