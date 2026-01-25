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
WEBSITE_URL = "https://sport-daily.vercel.app" # Tanpa slash di akhir
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

# --- CATEGORY RSS FEED (MODIFIED) ---
# 🔴 PERBAIKAN: Link RSS Trends lama (404) diganti dengan Google News Sports Topic (US)
# Link ini setara dengan category=17 (Sports) di Google Trends, tapi formatnya RSS yang valid (200 OK).
CATEGORY_URLS = {
    "US Sports Trends": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en"
}

# --- AUTHORITY SOURCES ---
AUTHORITY_SOURCES = [
    "Transfermarkt", "Sky Sports", "The Athletic", "Opta Analyst",
    "WhoScored", "BBC Sport", "The Guardian", "UEFA Official", "ESPN FC"
]

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1556056504-5c7696c4c28d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

TARGET_PER_CATEGORY = 1 

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

# --- RSS FETCHER (MODIFIED) ---
def fetch_rss_feed(url):
    # Update Header agar terlihat seperti Browser (Mencegah 403 Forbidden)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://news.google.com/'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        # Jika RSS asli mati (404), return None agar tidak crash
        if response.status_code != 200: 
            print(f"      ⚠️ Feed Error: Status {response.status_code}")
            return None
        return feedparser.parse(response.content)
    except Exception as e: 
        print(f"      ⚠️ Fetch Error: {e}")
        return None

# --- CLEANING ---
def clean_text(text):
    if not text: return ""
    cleaned = text.replace("**", "").replace("__", "").replace("##", "")
    cleaned = cleaned.replace('"', "'") 
    cleaned = cleaned.strip()
    return cleaned

# --- IMAGE ENGINE (HQ WEBP + SHARPNESS BOOSTER) ---
def download_and_optimize_image(query, filename):
    # Paksa ekstensi .webp
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    # Prompt Engineering: Detail Tinggi
    base_prompt = f"{query} football match action, stadium atmosphere, 8k resolution, highly detailed, photorealistic, cinematic lighting, sharp focus, professional sports photography"
    safe_prompt = base_prompt.replace(" ", "%20")[:250]
    
    print(f"      🎨 Generating HQ Image: {base_prompt[:40]}...")

    for attempt in range(3):
        seed = random.randint(1, 999999)
        # Gunakan model Flux Realism
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true&model=flux-realism&seed={seed}&enhance=true"
        
        try:
            response = requests.get(image_url, timeout=120)
            
            if response.status_code == 200:
                if "image" not in response.headers.get("content-type", ""):
                    print("      ⚠️ Not an image type. Retrying...")
                    time.sleep(2)
                    continue

                img = Image.open(BytesIO(response.content))
                img = img.convert("RGB")
                
                # 1. RESIZE 16:9 (1200x675) Standard Discover
                img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                
                # 2. VISUAL ENHANCEMENT (Agar Tajam di HP)
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.3) # Tajamkan 30%
                
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.1) # Warna +10%

                output_path = f"{IMAGE_DIR}/{filename}"
                
                # 3. SAVE AS WEBP (Quality 85)
                img.save(output_path, "WEBP", quality=75, method=6, optimize=True)
                
                print(f"      📸 HQ Image Saved: {filename}")
                return f"/images/{filename}" 

        except Exception as e:
            print(f"      ⚠️ Image fail (Attempt {attempt+1}): {e}")
            time.sleep(5)
    
    print("      ❌ Image failed after 3 attempts. Using Fallback.")
    return random.choice(FALLBACK_IMAGES)

# --- INDEXING ENGINE (GOOGLE & INDEXNOW) ---

def submit_to_google(url):
    if not GOOGLE_JSON_KEY:
        print("      ⚠️ Google Indexing Skipped: No JSON Key found.")
        return

    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)

        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Submitted: {url}")
    except Exception as e:
        if "FutureWarning" not in str(e):
             print(f"      ⚠️ Google Indexing Error: {e}")

def submit_to_indexnow(url):
    if "Sportdaily" in WEBSITE_URL and "Sportdaily-alpha" not in WEBSITE_URL:
         pass # Check logic sederhana

    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        
        headers = {'Content-Type': 'application/json; charset=utf-8'}
        response = requests.post(endpoint, json=data, headers=headers)
        
        if response.status_code == 200:
            print(f"      🚀 IndexNow Submitted: {url}")
        else:
            print(f"      ⚠️ IndexNow Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"      ⚠️ IndexNow Error: {e}")

# --- AI WRITER ENGINE ---
def parse_ai_response(text, fallback_title, fallback_desc):
    try:
        parts = text.split("|||BODY_START|||")
        if len(parts) >= 2:
            json_part = parts[0].strip()
            body_part = parts[1].strip()
            json_part = re.sub(r'```json\s*', '', json_part)
            json_part = re.sub(r'```', '', json_part)
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
        "category": "General",
        "main_keyword": "Football",
        "lsi_keywords": [],
        "content": clean_body
    }

def get_groq_article_seo(title, summary, link, internal_links_block, target_category, author_name):
    AVAILABLE_MODELS = ["llama-3.3-70b-versatile"]
    selected_sources = ", ".join(random.sample(AUTHORITY_SOURCES, 3))
    
    system_prompt = f"""
    You are {author_name} for 'Sport Daily'.
    TARGET CATEGORY: {target_category}
    
    GOAL: Write a 1200+ word article with UNIQUE HEADERS & DIVERSE SOURCES.
    
    OUTPUT FORMAT (JSON):
    {{
        "title": "Headline (NO MARKDOWN)",
        "description": "Meta description",
        "category": "{target_category}",
        "main_keyword": "Entity Name",
        "lsi_keywords": ["keyword1"],
        "image_alt": "Descriptive text for image"
    }}
    |||BODY_START|||
    [Markdown Content]

    # RULES:
    - NO GENERIC HEADERS. Use creative sub-headlines.
    - NO EMOJIS.
    
    # INTERNAL LINKING:
    BLOCK START:
    ### Read More
    {internal_links_block}
    BLOCK END.

    # STRUCTURE:
    1. Executive Summary (Blockquote).
    2. Deep Dive Analysis (Unique H2).
    3. Mandatory Data Table (Unique H2).
    4. **Read More** (Paste Block Above).
    5. Quotes & Reaction (Unique H2).
    6. External Authority Link (Source: {selected_sources}).
    7. FAQ.
    """

    user_prompt = f"""
    News Topic: {title}
    Summary: {summary}
    Link: {link}
    
    Write the 1200-word masterpiece now.
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        for model in AVAILABLE_MODELS:
            try:
                print(f"      🤖 AI Writing ({target_category}) using {model}...")
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.75, 
                    max_tokens=7500,
                )
                return completion.choices[0].message.content
            except RateLimitError:
                print(f"      ⚠️ Limit hit on {model}, switching...")
                continue
            except Exception as e:
                print(f"      ⚠️ Error: {e}")
                continue
            
    return None

# --- MAIN LOOP ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0

    for category_name, rss_url in CATEGORY_URLS.items():
        print(f"\n📡 Fetching: {category_name}...")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        cat_success_count = 0
        for entry in feed.entries:
            if cat_success_count >= TARGET_PER_CATEGORY: break

            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"

            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue

            # PILIH PENULIS SECARA ACAK
            current_author = random.choice(AUTHOR_PROFILES)
            print(f"   🔥 Processing: {clean_title[:40]}... (Author: {current_author})")
            
            links_block = get_formatted_internal_links()
            raw_response = get_groq_article_seo(clean_title, entry.summary, entry.link, links_block, category_name, current_author)
            
            if not raw_response: continue

            data = parse_ai_response(raw_response, clean_title, entry.summary)
            if not data: continue

            # IMAGE GENERATION (WEBP)
            img_name = f"{slug}.webp"
            keyword_for_image = data.get('main_keyword') or clean_title
            
            final_img = download_and_optimize_image(keyword_for_image, img_name)
            
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
*Source: Analysis by {current_author} based on international reports and [Original Story]({entry.link}).*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md)
            
            if 'title' in data: save_link_to_memory(data['title'], slug)
            
            print(f"   ✅ Published: {filename}")
            cat_success_count += 1
            total_generated += 1
            
            # --- AUTO INDEXING TRIGGER ---
            full_article_url = f"{WEBSITE_URL}/{slug}/"
            print(f"   🚀 Submitting for Indexing: {full_article_url}")
            
            submit_to_indexnow(full_article_url)
            submit_to_google(full_article_url)
            
            time.sleep(5)

    print(f"\n🎉 DONE! Total: {total_generated}")

if __name__ == "__main__":
    main()
