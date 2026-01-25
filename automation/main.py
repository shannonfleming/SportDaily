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

WEBSITE_URL = "https://sport-daily.vercel.app" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- TIM PENULIS ---
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", "Sarah Jenkins (Chief Editor)", 
    "Luca Romano (Transfer Specialist)", "Marcus Reynolds (PL Correspondent)", 
    "Elena Petrova (Tactical Expert)", "Ben Foster (Sports Journalist)"
]

# --- AUTHORITY SOURCES ---
AUTHORITY_SOURCES = [
    "Transfermarkt", "Sky Sports", "The Athletic", "Opta Analyst",
    "WhoScored", "BBC Sport", "The Guardian", "UEFA Official", "ESPN FC"
]

# --- TARGET GEOS (URUTAN PRIORITAS) ---
# Bot akan mengecek urut dari kiri ke kanan sampai target terpenuhi
# GB: Inggris, US: Amerika, NG: Nigeria (Bola hype tinggi), ZA: South Africa, IE: Ireland, AU: Australia
TARGET_GEOS = ["GB", "US", "NG", "ZA", "IE", "AU"]

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

TARGET_TOTAL_ARTICLES = 5 # Total artikel yg diinginkan per run

# --- FILTER KEYWORDS ---
SPORTS_KEYWORDS = [
    "football", "soccer", "premier league", "champions league", "manchester", 
    "liverpool", "arsenal", "chelsea", "madrid", "barcelona", "bayern", 
    "juventus", "ronaldo", "messi", "fifa", "uefa", "transfer", "cup", 
    "league", "sport", "coach", "manager", "vs", "score", "tottenham", 
    "united", "city", "villa", "newcastle", "mbappe", "bellingham", "klopp",
    "pep", "arteta", "ten hag", "pochetino", "mourinho", "world cup", "euro",
    "super bowl", "nfl" # Tambahan jika ingin sport umum US, hapus jika khusus bola kaki
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
    return "\n".join([f"* [{t}]({u})" for t, u in items])

# --- FETCHERS ---
def fetch_google_trends(geo="GB"):
    """
    Mengambil RSS Trends berdasarkan kode negara (GEO)
    """
    rss_url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
    print(f"   📡 Scanning Google Trends Region: {geo}...")
    try:
        feed = feedparser.parse(rss_url)
        trends = []
        if feed.entries:
            for entry in feed.entries:
                # Cek apakah keyword mengandung unsur olahraga
                if any(k in entry.title.lower() for k in SPORTS_KEYWORDS):
                    trends.append(entry.title)
        return trends
    except: return []

def fetch_news_context(keyword):
    """
    Mencari konteks berita di Google News Global (English)
    agar relevan dengan keyword dari negara manapun.
    """
    encoded = requests.utils.quote(f"{keyword} football news")
    # Tetap gunakan hl=en-GB untuk output bahasa Inggris yang rapi
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-GB&gl=GB&ceid=GB:en"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            feed = feedparser.parse(r.content)
            return feed.entries[0] if feed and feed.entries else None
    except: return None
    return None

# --- IMAGE & CLEANING ---
def clean_text(text):
    if not text: return ""
    return text.replace("**", "").replace("__", "").replace('"', "'").strip()

def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"): filename = filename.rsplit(".", 1)[0] + ".webp"
    # Prompt dinamis
    safe_prompt = f"{query} football match action, stadium atmosphere, 8k resolution, photorealistic, sharp focus".replace(" ", "%20")[:250]
    
    print(f"      🎨 Generating Image for: {query[:20]}...")
    for _ in range(2):
        seed = random.randint(1, 999999)
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true&model=flux-realism&seed={seed}&enhance=true"
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
                img = Image.open(BytesIO(r.content)).convert("RGB")
                img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                
                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(1.3)
                
                img.save(f"{IMAGE_DIR}/{filename}", "WEBP", quality=75)
                return f"/images/{filename}"
        except: time.sleep(2)
    return random.choice(FALLBACK_IMAGES)

# --- INDEXING ---
def submit_to_indexers(url):
    # IndexNow
    try:
        ep = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        requests.post(ep, json={"host": host, "key": INDEXNOW_KEY, "urlList": [url]})
        print(f"      🚀 IndexNow Submitted")
    except: pass
    
    # Google Indexing
    if GOOGLE_JSON_KEY:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_JSON_KEY), ["https://www.googleapis.com/auth/indexing"])
            build("indexing", "v3", credentials=creds).urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
            print(f"      🚀 Google Indexing Submitted")
        except Exception as e: 
            if "FutureWarning" not in str(e): print(f"      ⚠️ Google Index Error: {e}")

# --- AI WRITER ---
def generate_article(title, summary, link, author, trend_origin):
    system_prompt = f"""
    You are {author}, an international sports correspondent for 'Sport Daily'.
    TOPIC: Trending Football News (Origin: {trend_origin}).
    
    GOAL: Write a 1000-word viral article.
    
    OUTPUT JSON:
    {{
        "title": "Headline (Engaging, Max 60 chars)",
        "description": "Meta description (SEO Optimized)",
        "category": "Trending News",
        "main_keyword": "Focus Keyword",
        "lsi_keywords": ["key1", "key2"],
        "image_alt": "Alt text description"
    }}
    |||BODY_START|||
    [Markdown Content]
    
    STRUCTURE:
    - Executive Summary (Bold).
    - Detailed Analysis (Unique H2).
    - Statistical Data Table (Unique H2).
    - Reaction & Quotes (Unique H2).
    - Conclusion (Unique H2).
    - ### Read More (Block at the end):
    {get_formatted_internal_links()}
    """
    
    user_prompt = f"Trend: {title}\nContext: {summary}\nLink: {link}\nWrite now."
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.7, max_tokens=6500
            )
            return completion.choices[0].message.content
        except: continue
    return None

def process_and_save(data_raw, original_title, original_link, author, keyword_img, origin_country):
    try:
        parts = data_raw.split("|||BODY_START|||")
        if len(parts) < 2: return False
        
        data = json.loads(re.sub(r'```json\s*|```', '', parts[0].strip()))
        data['content'] = parts[1].strip()
        
        slug = slugify(data.get('title', original_title), max_length=60)
        filename = f"{slug}.md"
        
        if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
            print("      ⚠️ Duplicate content detected. Skipping.")
            return False
        
        # Image Generation
        img_url = download_and_optimize_image(keyword_img, f"{slug}.webp")
        
        # Metadata
        date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
        tags = json.dumps(data.get('lsi_keywords', []))
        
        md = f"""---
title: "{data.get('title')}"
date: {date}
author: "{author}"
categories: ["{data.get('category')}"]
tags: {tags}
featured_image: "{img_url}"
featured_image_alt: "{data.get('image_alt')}"
description: "{data.get('description')}"
slug: "{slug}"
url: "/{slug}/"
draft: false
---

{data['content']}

---
*Source: Global Trending Analysis ({origin_country}) by {author} based on [Original Report]({original_link}).*
"""
        with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md)
        save_link_to_memory(data.get('title'), slug)
        
        print(f"   ✅ Published: {filename}")
        submit_to_indexers(f"{WEBSITE_URL}/{slug}/")
        return True
    except Exception as e:
        print(f"   ⚠️ Parsing Error: {e}")
        return False

# --- MAIN LOGIC (MULTI-GEO) ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    generated_count = 0
    seen_trends = set() # Untuk mencegah duplikasi antar negara (misal "Messi" trending di GB dan US)
    
    print("\n🔥 STARTING MULTI-GEO TRENDS AUTOMATION 🔥")
    print(f"🎯 Target: {TARGET_TOTAL_ARTICLES} articles. Priority: {TARGET_GEOS}")
    
    # LOOP UTAMA: Pindah Negara jika kuota belum penuh
    for geo_code in TARGET_GEOS:
        if generated_count >= TARGET_TOTAL_ARTICLES:
            break # Stop jika target sudah terpenuhi
            
        print(f"\n🌍 Switching to Region: {geo_code}...")
        
        trends = fetch_google_trends(geo=geo_code)
        
        if not trends:
            print(f"   ⚠️ No sport trends found in {geo_code}. Trying next region...")
            continue
            
        print(f"   💎 Found {len(trends)} potential candidates in {geo_code}.")
        
        # LOOP TREND: Proses setiap trend dalam negara tersebut
        for trend_keyword in trends:
            if generated_count >= TARGET_TOTAL_ARTICLES: break
            
            # Cek apakah trend ini sudah diproses di negara sebelumnya?
            if trend_keyword.lower() in seen_trends:
                continue
                
            seen_trends.add(trend_keyword.lower())
            
            print(f"\n   🔍 Processing: {trend_keyword} ({geo_code})")
            
            # Cari berita pendukung (News Context)
            news_context = fetch_news_context(trend_keyword)
            if not news_context:
                print("      ❌ No detailed news found. Skipping.")
                continue
                
            author = random.choice(AUTHOR_PROFILES)
            
            # Generate Artikel
            raw_ai = generate_article(
                news_context.title, 
                news_context.summary, 
                news_context.link, 
                author,
                trend_origin=geo_code
            )
            
            if not raw_ai: continue
            
            # Simpan
            success = process_and_save(
                raw_ai, 
                news_context.title, 
                news_context.link, 
                author, 
                trend_keyword, # Gunakan keyword asli untuk gambar
                origin_country=geo_code
            )
            
            if success:
                generated_count += 1
                time.sleep(5) # Jeda sopan
                
    # LAPORAN AKHIR
    print(f"\n🎉 DONE! Generated {generated_count}/{TARGET_TOTAL_ARTICLES} articles from {len(seen_trends)} trends scanned.")
    if generated_count < TARGET_TOTAL_ARTICLES:
        print("⚠️ Note: Exhausted all regions but could not fill the target.")

if __name__ == "__main__":
    main()
