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
MODEL_NAME = "gemini-2.5-flash" 

# --- LOG ---
def log(msg, level="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

# --- DATA ---
rss_news_store = []
sent_links = set()
MAX_NEWS = 5000
CLEAR_COUNT = 1000

# --- HELPERS ---
def translate(text):
    try:
        return GoogleTranslator(source='auto', target='te').translate(text)
    except:
        return text

def clean_html_tags(text):
    if not text: return ""
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")

def send_long_message(chat_id, text):
    for i in range(0, len(text), 4000):
        try:
            bot.send_message(chat_id, text[i:i+4000], parse_mode='HTML', disable_web_page_preview=False)
        except Exception as e:
            log(f"❌ Telegram send error: {e}", "ERROR")

def manage_memory():
    global rss_news_store
    if len(rss_news_store) > MAX_NEWS:
        rss_news_store = rss_news_store[CLEAR_COUNT:]
        log(f"✅ Memory cleaned.")

# =========================
# 🟢 NORMAL RSS FETCH
# =========================
def fetch_normal_rss():
    FEEDS = {
        "CNBC": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml",
    }
    for name, url in FEEDS.items():
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            feed = feedparser.parse(res.content)
            for entry in feed.entries[:10]:
                link = entry.get("link", "")
                if not link or link in sent_links: continue
                sent_links.add(link)

                title = clean_html_tags(entry.get("title", ""))
                clean_desc = re.sub('<[^>]+>', '', entry.get("summary", "")).replace("\n", " ").strip()
                tel_title = translate(title)
                tel_desc = translate(clean_desc[:800])
                g_trans_url = f"https://translate.google.com/translate?sl=en&tl=te&u={link}"

                msg = (
                    f'<a href="{link}">&#8203;</a>'
                    f"📌 <b>{tel_title}</b>\n\n"
                    f"🇬🇧 <b>English Title:</b>\n{title}\n\n"
                    f"🇮🇳 <b>తెలుగు సమ్మరీ:</b>\n{tel_desc}\n\n"
                    f"🌐 <b>{name}</b>\n"
                    f"🔗 <a href='{g_trans_url}'>Read More in Telugu</a> | "
                    f"<a href='{link}'>English Original</a>"
                )
                rss_news_store.append(title + " " + clean_desc)
                manage_memory()
                send_long_message(CHAT_ID, msg)
                time.sleep(1)
        except Exception as e:
            log(f"❌ RSS Error {name}: {e}", "ERROR")

# =========================
# 🔵 X (NITTER) RSS FETCH
# =========================
def fetch_x_rss():
    X_FEEDS = {
        "CNBC News (X)": "https://nitter.net/CNBCTV18News/rss",
        "CNBC Live (X)": "https://nitter.net/CNBCTV18Live/rss",
    }
    scraper = cloudscraper.create_scraper()
    for name, url in X_FEEDS.items():
        try:
            res = scraper.get(url, timeout=20)
            if res.status_code != 200: continue
            feed = feedparser.parse(res.content)
            for entry in feed.entries[:5]:
                link = entry.get("link", "")
                if not link or link in sent_links: continue
                sent_links.add(link)

                title = clean_html_tags(re.sub(r'http\S+|@\w+|#\w+|⤵️', '', entry.get("title", "")))
                tel_title = translate(title)
                g_trans_url = f"https://translate.google.com/translate?sl=en&tl=te&u={link}"

                msg = (
                    f"🚀 <b>{name} Update</b>\n\n"
                    f"📌 <b>{tel_title}</b>\n\n"
                    f"🇬🇧 {title}\n\n"
                    f"🔗 <a href='{g_trans_url}'>Read More in Telugu</a> | "
                    f"<a href='{link}'>English Original</a>"
                )
                rss_news_store.append(title)
                manage_memory()

                # ఇమేజ్ ఉంటే ఫోటో పంపుతుంది
                soup = BeautifulSoup(str(entry.get('summary', '')), 'html.parser')
                img = soup.find('img')
                if img:
                    try: bot.send_photo(CHAT_ID, img['src'], caption=msg[:1024], parse_mode='HTML')
                    except: send_long_message(CHAT_ID, msg)
                else:
                    send_long_message(CHAT_ID, msg)
                time.sleep(2)
        except Exception as e:
            log(f"❌ X RSS Error {name}: {e}", "ERROR")

# =========================
# 🤖 AI SUMMARY
# =========================
@bot.message_handler(commands=['summary'])
def summary(message):
    if not rss_news_store:
        bot.reply_to(message, "❌ వార్తలు లేవు")
        return

    bot.send_message(CHAT_ID, "🔍 AI విశ్లేషణ జరుగుతోంది...")
    rss_data = "\n".join(rss_news_store[-100:])
    prompt = f"Analyze these news items in 4 sections: Corporate, National, Global, and Outlook. Output in Telugu:\n{rss_data}"

    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        # AI ఇచ్చే మెసేజ్‌లో <b> ట్యాగులు ఉండేలా మార్చవచ్చు లేదా ప్లెయిన్ టెక్స్ట్
        final_text = clean_html_tags(response.text).replace("**", "")
        bot.send_message(CHAT_ID, f"📊 <b>AI విశ్లేషణ</b>\n\n{final_text}", parse_mode='HTML')
        log("✅ Summary sent")
    except Exception as e:
        log(f"❌ AI Error: {e}", "ERROR")

# =========================
# 📋 LIST
# =========================
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

# =========================
# 🔄 LOOP & BOT START
# =========================
def loop():
    log("📡 Background Fetcher Started...")
    while True:
        try:
            fetch_normal_rss()
            fetch_x_rss()
        except Exception as e:
            log(f"❌ Loop Error: {e}", "ERROR")
        time.sleep(120) # 2 నిమిషాల గ్యాప్

def start_bot():
    log("🚀 Bot Polling Started...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            log(f"❌ Polling Error: {e}", "ERROR")
            time.sleep(5)

if __name__ == "__main__":
    # 1. త్రెడ్ లో న్యూస్ ఫెచింగ్ రన్ చేయడం
    threading.Thread(target=loop, daemon=True).start()
    
    # 2. మెయిన్ ప్రాసెస్ లో బాట్ ని రన్ చేయడం
    log("🤖 BOT IS ONLINE")
    start_bot()
