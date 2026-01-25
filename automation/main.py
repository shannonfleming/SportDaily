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
    "Ben Foster (Sports Journalist)"
]

# --- TARGET GEOS ---
# Prioritas negara untuk dicek
TARGET_GEOS = ["US", "GB", "NG", "ZA", "IE", "AU", "ES", "IT", "BR"]

# --- CONTENT CONFIG ---
CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_TOTAL_ARTICLES = 5 

# --- BROWSER HEADERS ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

# --- MASSIVE KEYWORD DATABASE (Backup Filter) ---
SPORTS_KEYWORDS = [
    "football", "soccer", "sport", "league", "cup", "game", "match", "vs", "score",
    "result", "highlights", "table", "fixture", "transfer", "injury", "manager",
    "ufc", "mma", "nba", "basketball", "nfl", "f1", "formula 1", "moto gp", "boxing",
    "premier league", "champions league", "europa", "la liga", "serie a", "bundesliga", 
    "ligue 1", "mls", "fifa", "uefa", "fa cup", "carabao", "copa america", "euro 2024", 
    "world cup", "afcon", "libertadores", "super bowl", "playoffs",
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "liverpool", "luton", "man city", 
    "manchester city", "man utd", "manchester united", "newcastle", "nottingham",
    "sheffield", "tottenham", "spurs", "west ham", "wolves", "leicester", "leeds",
    "real madrid", "barcelona", "atletico", "girona", "villarreal", "sevilla",
    "bayern", "dortmund", "leverkusen", "juventus", "milan", "inter", "roma", "napoli", 
    "psg", "ajax", "benfica", "porto", "sporting", "celtic", "rangers", "miami", 
    "al nassr", "al hilal", "knicks", "76ers", "lakers", "warriors", "chiefs", "49ers",
    "paddy pimblett", "pimblett", "mcgregor", "jon jones", "ngannou",
    "messi", "ronaldo", "mbappe", "haaland", "bellingham", "kane", "salah", "debruyne",
    "saka", "rice", "foden", "vinicius", "rodrygo", "yamal", "lewandowski", "neymar",
    "mike mccarthy", "dak prescott", "lebron", "curry"
]

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
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
    if len(memory) > 50: memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    if len(items) > 3: items = random.sample(items, 3)
    return "\n".join([f"* [{t}]({u})" for t, u in items])

# --- 🔥 NEW: GOOGLE TRENDS JSON API FETCHER 🔥 ---
def fetch_google_trends(geo="US"):
    """
    Menggunakan JSON Endpoint API Resmi Google Trends.
    Menggantikan RSS yang sudah mati (404).
    Mendukung filter category sports (cat=s).
    """
    # Endpoint resmi API (Hidden API)
    url = "https://trends.google.com/trends/api/dailytrends"
    
    # Parameter query string
    params = {
        "hl": "en-US",
        "tz": "0",       # Timezone UTC
        "geo": geo,      # Kode negara
        "cat": "s",      # s = Sports (PENTING!)
        "ns": "15"       # Ambil 15 trend teratas
    }
    
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://trends.google.com/trends/trendingsearches/daily?geo=' + geo,
    }

    print(f"   🔎 Scanning 'Sports' API for Region: {geo}...")
    
    try:
        # Request ke Google
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"      ⚠️ Status Code: {response.status_code} (Mungkin negara tidak support daily trends)")
            return []
            
        # Google API mengembalikan "Magic Prefix" di awal respon: ")]}',"
        # Kita harus hapus 5 karakter pertama agar jadi JSON valid
        content = response.text[5:] 
        
        data = json.loads(content)
        
        # Parsing struktur JSON Google
        # default -> trendingSearchesDays -> [0] -> trendingSearches
        days = data.get("default", {}).get("trendingSearchesDays", [])
        
        if not days:
            print("      ⚠️ JSON structure mismatch or empty.")
            return []
            
        # Ambil hari ini (index 0)
        todays_trends = days[0].get("trendingSearches", [])
        
        trends_found = []
        
        print(f"      ✅ API Success! Found {len(todays_trends)} items.")
        
        for item in todays_trends:
            # Ambil judul trend (Query)
            query = item.get("title", {}).get("query", "")
            
            if query:
                # Karena kita sudah pakai cat=s, seharusnya ini sudah olahraga semua.
                # Tapi kita cek lagi pakai SPORTS_KEYWORDS untuk memastikan kualitas.
                # Atau kita bisa langsung ambil saja karena API Google cukup akurat.
                
                # Kita log apa saja yang ditemukan
                # print(f"         Found: {query}")
                trends_found.append(query)
                
        return trends_found

    except Exception as e:
        print(f"      ❌ API Error: {e}")
        return []

def fetch_news_context(keyword):
    """
    Mencari konteks berita di Google News Global
    """
    encoded = requests.utils.quote(f"{keyword} news")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    
    headers = {'User-Agent': random.choice(USER_AGENTS)} 
    
    try:
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
    safe_prompt = f"{query} sports action photography, stadium atmosphere, 8k, realistic, sharp focus".replace(" ", "%20")[:250]
    
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
    try:
        ep = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        requests.post(ep, json={"host": host, "key": INDEXNOW_KEY, "urlList": [url]})
        print(f"      🚀 IndexNow Submitted")
    except: pass
    
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
    You are {author}, a professional sports journalist.
    TOPIC: {title} (Trending in {trend_origin}).
    
    GOAL: Write a 1000-word engaging article.
    
    OUTPUT JSON:
    {{
        "title": "Headline (Max 60 chars, Clickworthy)",
        "description": "Meta description",
        "category": "Sports News",
        "main_keyword": "Focus Keyword",
        "lsi_keywords": ["key1", "key2"],
        "image_alt": "Alt text description"
    }}
    |||BODY_START|||
    [Markdown Content]
    
    STRUCTURE:
    - **Dateline** (e.g., {trend_origin} - ).
    - **Executive Summary** (Italicized, 50 words, Unique H2).
    - **Match/Event Analysis** (Unique H2).
    - **Key Stats/Table** (Markdown Table).
    - **Quotes & Reactions** (Unique H2).
    - **Conclusion** (Unique H2).
    - ### Read More (Block at the end):
    {get_formatted_internal_links()}
    """
    
    user_prompt = f"Write about: {title}\nDetails: {summary}\nLink: {link}"
    
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
        
        img_url = download_and_optimize_image(keyword_img, f"{slug}.webp")
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
*Source: Trending Analysis ({origin_country}) by {author}.*
"""
        with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md)
        save_link_to_memory(data.get('title'), slug)
        
        print(f"   ✅ Published: {filename}")
        submit_to_indexers(f"{WEBSITE_URL}/{slug}/")
        return True
    except Exception as e:
        print(f"   ⚠️ Parsing Error: {e}")
        return False

# --- MAIN LOGIC ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    generated_count = 0
    seen_trends = set() 
    
    print("\n🔥 STARTING SPORTS TRENDS AUTOMATION (API JSON MODE) 🔥")
    print(f"🎯 Target: {TARGET_TOTAL_ARTICLES} articles.")
    
    for geo_code in TARGET_GEOS:
        if generated_count >= TARGET_TOTAL_ARTICLES: break
            
        print(f"\n🌍 Switching to Region: {geo_code}...")
        
        # 🟢 PANGGIL API JSON
        trends = fetch_google_trends(geo=geo_code)
        
        if not trends:
            print(f"   ⚠️ No sports data in {geo_code} via API.")
            continue
        
        for trend_keyword in trends:
            if generated_count >= TARGET_TOTAL_ARTICLES: break
            
            if trend_keyword.lower() in seen_trends: continue
            seen_trends.add(trend_keyword.lower())
            
            print(f"\n   🔍 Processing: {trend_keyword} ({geo_code})")
            news_context = fetch_news_context(trend_keyword)
            if not news_context:
                print("      ❌ No detailed news found. Skipping.")
                continue
                
            author = random.choice(AUTHOR_PROFILES)
            raw_ai = generate_article(news_context.title, news_context.summary, news_context.link, author, trend_origin=geo_code)
            
            if not raw_ai: continue
            
            success = process_and_save(raw_ai, news_context.title, news_context.link, author, trend_keyword, origin_country=geo_code)
            if success:
                generated_count += 1
                time.sleep(5) 
                
    print(f"\n🎉 DONE! Generated {generated_count}/{TARGET_TOTAL_ARTICLES} articles.")

if __name__ == "__main__":
    main()
