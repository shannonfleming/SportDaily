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
from PIL import Image, ImageEnhance
from groq import Groq, APIError, RateLimitError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
except ImportError:
    print("⚠️ Warning: Google Indexing libs not installed. Install via: pip install google-api-python-client oauth2client")

# --- CONFIGURATION ---
# Pastikan API KEY Anda benar di Environment Variable atau isi manual di sini (tidak disarankan hardcode)
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# 🟢 CONFIGURASI DOMAIN & INDEXNOW
WEBSITE_URL = "https://sport-daily.vercel.app" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

# Cek API Key
if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing! Set 'GROQ_API_KEY' environment variable.")
    exit(1)

# --- TIM PENULIS (NEWSROOM) ---
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)", "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)", "Ben Foster (Sports Journalist)",
    "Mateo Rodriguez (European Football Analyst)"
]

# --- 🟢 DAFTAR KATEGORI RESMI ---
VALID_CATEGORIES = [
    "Transfer News", 
    "Premier League", 
    "Champions League", 
    "La Liga", 
    "International", 
    "Tactical Analysis"
]

# --- 🟢 SUMBER RSS ---
RSS_SOURCES = {
    "US Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
    "UK Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-GB&gl=GB&ceid=GB:en",
    "SkySports": "https://www.skysports.com/rss/12040"
}

# --- DIRECTORIES ---
CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

# Konfigurasi Fallback Image
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
]

TARGET_PER_SOURCE = 3 

# ==========================================
# 🧠 MEMORY & LINKING SYSTEM (TIDAK DIHAPUS)
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}"
    # Simpan max 50 link terakhir
    if len(memory) > 50:
        memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    # Ambil 3 link random untuk SEO
    if len(items) > 3: items = random.sample(items, 3)
    formatted_links = []
    for title, url in items:
        formatted_links.append(f"- [{title}]({url})")
    return "\n".join(formatted_links)

# ==========================================
# 📡 RSS FETCHER
# ==========================================
def fetch_rss_feed(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return None
        return feedparser.parse(response.content)
    except: return None

# ==========================================
# 🎨 IMAGE ENGINE (OPTIMIZED)
# ==========================================
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    # Prompt yang lebih realistis untuk berita
    base_prompt = f"editorial sports photography, {query}, realistic stadium background, 4k, press photo style, sharp focus"
    safe_prompt = base_prompt.replace(" ", "%20")[:300]
    
    print(f"      🎨 Generating Image: {query[:30]}...")

    # Coba 2 kali saja agar tidak terlalu lama
    for attempt in range(2):
        seed = random.randint(1, 999999)
        # Menggunakan Flux Realism via Pollinations
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&nologo=true&model=flux-realism&seed={seed}"
        
        try:
            response = requests.get(image_url, timeout=60)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content)).convert("RGB")
                
                # Optimasi Warna & Ketajaman
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.2)
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.1)

                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=80)
                
                print(f"      📸 Image Saved: {filename}")
                return f"/images/{filename}" 

        except Exception:
            time.sleep(2)
    
    print("      ⚠️ Image gen failed. Using Fallback.")
    return random.choice(FALLBACK_IMAGES)

# ==========================================
# 🚀 INDEXING ENGINE (TIDAK DIHAPUS)
# ==========================================
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
        # Ignore warning trivial
        pass

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
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=5)
        print(f"      🚀 IndexNow Submitted")
    except: pass

# ==========================================
# 🤖 AI WRITER ENGINE (FIXED LOGIC)
# ==========================================
def get_groq_article_json(title, summary, link, internal_links_block, author_name):
    # INI BAGIAN PENTING: Memberi tahu AI tanggal hari ini agar tidak halusinasi
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a professional journalist for 'Sport Daily'.
    TODAY'S DATE: {current_date_str}.
    
    TASK: Write a high-quality sports news article based on the input.
    
    CRITICAL RULES FOR REALISM:
    1. **CHECK THE DATE:** 
       - If the match is in the FUTURE relative to Today ({current_date_str}), write a **PREVIEW** or **PREDICTION**. Do NOT invent a fake final score.
       - If the match is PAST, write a **MATCH REPORT**.
    2. **NO HALLUCINATION:** Do not invent quotes or specific stats that aren't common knowledge or in the snippet.
    3. **CATEGORY:** Choose exactly one from: {json.dumps(VALID_CATEGORIES)}.
    4. **HEADERS:** Use engaging H2 and H3 markdown headers.
    
    OUTPUT FORMAT:
    You must return a Valid JSON Object with these keys:
    {{
        "title": "Engaging Headline (No Markdown)",
        "description": "SEO Description (140 chars)",
        "category": "Selected Category",
        "main_keyword": "Main Subject Name",
        "lsi_keywords": ["tag1", "tag2"],
        "content_body": "Full Article in Markdown format..."
    }}
    
    STRUCTURE FOR 'content_body':
    1. **Executive Summary** (Bold).
    2. H2: Context / Background.
    3. H2: Tactical Key Points / Stats Table (Markdown).
    4. Blockquote (Key Quote).
    5. H2: What's Next? (Schedule).
    6. **Read More** section (Insert the provided links here).
    """

    user_prompt = f"""
    News Title: {title}
    Snippet: {summary}
    Source Link: {link}
    
    Internal Links to Insert in 'Read More':
    {internal_links_block}
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=6000,
                response_format={"type": "json_object"} # 👈 INI KUNCI AGAR TIDAK ERROR PARSING
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(2)
            continue
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            continue
            
    return None

# ==========================================
# 🏁 MAIN LOOP
# ==========================================
def main():
    # Buat folder jika belum ada
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Fetching Source: {source_name}...")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        cat_success_count = 0
        
        # Loop artikel dalam feed
        for entry in feed.entries:
            if cat_success_count >= TARGET_PER_SOURCE: break

            # Bersihkan judul untuk file name
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"

            # Skip jika file sudah ada (agar tidak duplikat)
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue

            current_author = random.choice(AUTHOR_PROFILES)
            print(f"   🔥 Processing: {clean_title[:40]}...")
            
            # Siapkan Internal Links
            links_block = get_formatted_internal_links()
            
            # Panggil AI (Mode JSON)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, links_block, current_author)
            
            if not raw_json: continue

            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                print("      ❌ JSON Decode Error. Skipping.")
                continue

            # Fallback jika kategori AI salah
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # Generate Gambar
            img_name = f"{slug}.webp"
            keyword_for_image = data.get('main_keyword') or clean_title
            final_img = download_and_optimize_image(keyword_for_image, img_name)
            
            # Siapkan Metadata
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags_list = data.get('lsi_keywords', [])
            if data.get('main_keyword'): tags_list.append(data['main_keyword'])
            
            # Format Markdown Final
            md_content = f"""---
title: "{data['title']}"
date: {date_now}
author: "{current_author}"
categories: ["{data['category']}"]
tags: {json.dumps(tags_list)}
featured_image: "{final_img}"
featured_image_alt: "Image showing {data.get('main_keyword', 'Sports Event')}"
description: "{data['description']}"
slug: "{slug}"
url: "/{slug}/"
draft: false
---

{data['content_body']}

---
*Source: Analysis by {current_author} based on reports from [Original Source]({entry.link}).*
"""
            # Simpan File
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # Simpan ke Memory untuk Internal Link berikutnya
            save_link_to_memory(data['title'], slug)
            
            print(f"   ✅ Published: {filename} (Category: {data['category']})")
            
            # Lakukan Indexing
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            cat_success_count += 1
            total_generated += 1
            
            # Istirahat sejenak agar sopan ke server orang
            time.sleep(5)

    print(f"\n🎉 DONE! Total Articles Generated: {total_generated}")

if __name__ == "__main__":
    main()
