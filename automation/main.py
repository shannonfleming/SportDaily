import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps
from groq import Groq, APIError, RateLimitError, BadRequestError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# --- GOOGLE INDEXING LIBS ---
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# --- CONFIGURATION ---
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# 🟢 CONFIGURASI DOMAIN & INDEXNOW
WEBSITE_URL = "https://sport-daily.vercel.app" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- TIM PENULIS (NEWSROOM) ---
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)",
    "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)",
    "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)",
    "Hiroshi Tanaka (Data Scout)",
    "Ben Foster (Sports Journalist)",
    "Mateo Rodriguez (European Football Analyst)"
]

# --- AUTHORITY SOURCES ---
AUTHORITY_SOURCES = [
    "Transfermarkt", "Sky Sports", "The Athletic", "Opta Analyst",
    "WhoScored", "BBC Sport", "The Guardian", "UEFA Official", "ESPN FC"
]

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1556056504-5c7696c4c28d?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

TARGET_ARTICLES = 5 # Jumlah artikel trending yang ingin dibuat per sesi

# --- FILTER KEYWORDS (Agar Trends tetap relevan ke Bola) ---
# Kode akan menolak trend selebriti/politik dan hanya mengambil yg ada di list ini
SPORTS_KEYWORDS = [
    "football", "soccer", "premier league", "champions league", "manchester", 
    "liverpool", "arsenal", "chelsea", "madrid", "barcelona", "bayern", 
    "juventus", "ronaldo", "messi", "fifa", "uefa", "transfer", "cup", 
    "league", "sport", "coach", "manager", "vs", "score", "tottenham", 
    "united", "city", "villa", "newcastle", "mbappe", "bellingham"
]

# --- MEMORY SYSTEM ---
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}"
    if len(memory) > 50:
        memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    if len(items) > 3: items = random.sample(items, 3)
    formatted_links = []
    for title, url in items:
        formatted_links.append(f"* [{title}]({url})")
    return "\n".join(formatted_links)

# --- GOOGLE TRENDS FETCHER (BARU) ---
def fetch_google_trends(geo="GB"):
    """
    Mengambil Daily Trends RSS dari Google Trends UK (GB).
    Memfilter hanya topik yang mengandung keyword olahraga.
    """
    rss_url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
    print(f"📈 Checking Google Trends ({geo})...")
    
    try:
        feed = feedparser.parse(rss_url)
        trends = []
        if feed.entries:
            for entry in feed.entries:
                title = entry.title
                # Filter: Hanya ambil jika mengandung kata kunci bola
                if any(k in title.lower() for k in SPORTS_KEYWORDS):
                    trends.append(title)
                    print(f"   found sport trend: {title}")
        
        # Jika tidak ada trend spesifik bola, kembalikan kosong (skip run ini)
        if not trends:
            print("   ⚠️ No specific football trends found right now.")
            return []
            
        return trends
    except Exception as e:
        print(f"Error fetching trends: {e}")
        return []

# --- NEWS CONTEXT FETCHER (BARU) ---
def fetch_news_context(keyword):
    """
    Mencari berita spesifik berdasarkan Keyword Trending di Google News RSS.
    Ini penting agar AI punya data aktual, bukan halusinasi.
    """
    encoded_query = requests.utils.quote(f"{keyword} football news")
    # Search language GB untuk relevansi Premier League
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-GB&gl=GB&ceid=GB:en"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return None
        feed = feedparser.parse(response.content)
        if feed.entries:
            return feed.entries[0] # Ambil berita paling atas/terbaru
    except: return None
    return None

# --- CLEANING ---
def clean_text(text):
    if not text: return ""
    cleaned = text.replace("**", "").replace("__", "").replace("##", "")
    cleaned = cleaned.replace('"', "'") 
    cleaned = cleaned.strip()
    return cleaned

# --- IMAGE ENGINE ---
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    # Prompt dinamis
    base_prompt = f"{query} football match action, stadium atmosphere, 8k resolution, highly detailed, photorealistic, cinematic lighting, sharp focus, professional sports photography"
    safe_prompt = base_prompt.replace(" ", "%20")[:250]
    
    print(f"      🎨 Generating HQ Image: {query[:30]}...")

    for attempt in range(3):
        seed = random.randint(1, 999999)
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true&model=flux-realism&seed={seed}&enhance=true"
        
        try:
            response = requests.get(image_url, timeout=120)
            if response.status_code == 200:
                if "image" not in response.headers.get("content-type", ""):
                    time.sleep(2); continue

                img = Image.open(BytesIO(response.content)).convert("RGB")
                img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.3)
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.1)

                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=75, method=6, optimize=True)
                print(f"      📸 HQ Image Saved: {filename}")
                return f"/images/{filename}" 

        except Exception as e:
            time.sleep(5)
    
    return random.choice(FALLBACK_IMAGES)

# --- INDEXING ENGINE ---
def submit_to_google(url):
    if not GOOGLE_JSON_KEY: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Submitted")
    except Exception as e:
        if "FutureWarning" not in str(e): print(f"      ⚠️ Google Indexing Error: {e}")

def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'})
        print(f"      🚀 IndexNow Submitted")
    except Exception as e: print(f"      ⚠️ IndexNow Error: {e}")

# --- AI WRITER ENGINE ---
def parse_ai_response(text, fallback_title, fallback_desc):
    try:
        parts = text.split("|||BODY_START|||")
        if len(parts) >= 2:
            json_part = re.sub(r'```json\s*|```', '', parts[0].strip())
            body_part = parts[1].strip()
            data = json.loads(json_part)
            data['title'] = clean_text(data.get('title', fallback_title))
            data['description'] = clean_text(data.get('description', fallback_desc))
            data['image_alt'] = clean_text(data.get('image_alt', data['title']))
            data['content'] = body_part
            return data
    except Exception: pass
    
    clean_body = re.sub(r'\{.*\}', '', text, flags=re.DOTALL).replace("|||BODY_START|||", "").strip()
    return {
        "title": clean_text(fallback_title),
        "description": clean_text(fallback_desc),
        "image_alt": clean_text(fallback_title),
        "category": "Trending",
        "main_keyword": "Football",
        "lsi_keywords": [],
        "content": clean_body
    }

def get_groq_article_seo(title, summary, link, internal_links_block, author_name):
    selected_sources = ", ".join(random.sample(AUTHORITY_SOURCES, 3))
    
    system_prompt = f"""
    You are {author_name} for 'Sport Daily'.
    TOPIC: Trending Football News.
    
    GOAL: Write a 1000+ word viral article based on the TRENDING TOPIC provided.
    
    OUTPUT FORMAT (JSON):
    {{
        "title": "Headline (Clickworthy but not Clickbait, NO MARKDOWN)",
        "description": "SEO Meta description",
        "category": "Trending News",
        "main_keyword": "Entity Name (Player/Club)",
        "lsi_keywords": ["keyword1", "keyword2"],
        "image_alt": "Descriptive text for image"
    }}
    |||BODY_START|||
    [Markdown Content]

    # RULES:
    - START with a Dateline (e.g., **London** – )
    - Use Short paragraphs (1-3 sentences).
    - Tone: Professional yet engaging.
    
    # INTERNAL LINKING:
    BLOCK START:
    ### Read More
    {internal_links_block}
    BLOCK END.

    # STRUCTURE:
    1. **Executive Summary** (Unique H2).
    2. Analysis of the situation (Unique H2).
    3. Key Stats / Match Facts (Table format).
    4. **Read More** (Paste Block Above).
    5. What This Means for the Team/Player (Unique H2).
    6. Conclusion & External Source ({selected_sources}).
    """

    user_prompt = f"""
    Trending Topic: {title}
    Latest Details: {summary}
    Source Link: {link}
    
    Write the article now.
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing using llama-3.3-70b-versatile...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.7, max_tokens=6500,
            )
            return completion.choices[0].message.content
        except RateLimitError: continue
        except Exception as e: print(f"      ⚠️ Error: {e}"); continue
            
    return None

# --- MAIN LOOP ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("\n🔥 STARTING AUTOMATION: GOOGLE TRENDS MODE 🔥")
    
    # 1. Ambil Keyword dari Google Trends UK
    trending_topics = fetch_google_trends(geo="GB")
    
    total_generated = 0
    
    # 2. Loop setiap keyword trending
    for trend_keyword in trending_topics:
        if total_generated >= TARGET_ARTICLES: break
        
        print(f"\n🔍 Processing Trend: {trend_keyword}")
        
        # 3. Cari Konteks Berita dari Trend tersebut
        news_entry = fetch_news_context(trend_keyword)
        
        if not news_entry:
            print("   ⚠️ No specific news context found. Skipping.")
            continue

        clean_title = news_entry.title.split(" - ")[0]
        slug = slugify(clean_title, max_length=60, word_boundary=True)
        filename = f"{slug}.md"

        if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
            print("   ⚠️ Article already exists.")
            continue

        current_author = random.choice(AUTHOR_PROFILES)
        links_block = get_formatted_internal_links()
        
        # 4. Generate Artikel
        raw_response = get_groq_article_seo(clean_title, news_entry.summary, news_entry.link, links_block, current_author)
        
        if not raw_response: continue

        data = parse_ai_response(raw_response, clean_title, news_entry.summary)
        if not data: continue

        # 5. Generate Gambar dari Keyword Trend
        img_name = f"{slug}.webp"
        # Gunakan keyword trend asli untuk gambar agar lebih akurat (misal: "Man United vs Chelsea")
        final_img = download_and_optimize_image(trend_keyword, img_name)
        
        date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
        tags_list = data.get('lsi_keywords', [])
        if data.get('main_keyword'): tags_list.append(data['main_keyword'])
        tags_str = json.dumps(tags_list)
        img_alt = data.get('image_alt', clean_title).replace('"', "'")
        
        md = f"""---
title: "{data['title']}"
date: {date}
author: "{current_author}"
categories: ["{data['category']}"]
tags: {tags_str}
featured_image: "{final_img}"
featured_image_alt: "{img_alt}"
description: "{data['description']}"
slug: "{slug}"
url: "/{slug}/"
draft: false
---

{data['content']}

---
*Source: Trending Analysis by {current_author} based on Google Trends data and [Original Story]({news_entry.link}).*
"""
        with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md)
        
        if 'title' in data: save_link_to_memory(data['title'], slug)
        
        print(f"   ✅ Published: {filename}")
        total_generated += 1
        
        # 6. Indexing
        full_article_url = f"{WEBSITE_URL}/{slug}/"
        submit_to_indexnow(full_article_url)
        submit_to_google(full_article_url)
        
        time.sleep(5)

    print(f"\n🎉 DONE! Total Trending Articles: {total_generated}")

if __name__ == "__main__":
    main()
