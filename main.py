import os
import feedparser
import requests
from newspaper import Article
from dotenv import load_dotenv
import re
from PIL import Image, ImageOps
from io import BytesIO
from keybert import KeyBERT
import logging # Import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv() # This will only load if .env file exists. For GitHub Actions, vars are passed directly.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
WP_SITE_URL        = os.getenv("WP_SITE_URL")
WP_USERNAME        = os.getenv("WP_USERNAME")
WP_APP_PASSWORD    = os.getenv("WP_APP_PASSWORD")
DEFAULT_IMAGE_URL  = os.getenv("DEFAULT_IMAGE_URL")

# Verify essential environment variables
if not OPENROUTER_API_KEY: logging.error("OPENROUTER_API_KEY not set!"); exit(1)
if not WP_SITE_URL: logging.error("WP_SITE_URL not set!"); exit(1)
if not WP_USERNAME: logging.error("WP_USERNAME not set!"); exit(1)
if not WP_APP_PASSWORD: logging.error("WP_APP_PASSWORD not set!"); exit(1)
if not DEFAULT_IMAGE_URL: logging.warning("DEFAULT_IMAGE_URL not set, image uploads might fail if top_image is missing.")


LAST_PUBLISHED_FILE = "last_published.txt"
kw_model = KeyBERT()

# ----------------- Helpers -----------------
def get_last_published():
    if os.path.exists(LAST_PUBLISHED_FILE):
        with open(LAST_PUBLISHED_FILE, "r") as f:
            link = f.read().strip()
            logging.info(f"Loaded last published link: {link}")
            return link
    logging.info(f"'{LAST_PUBLISHED_FILE}' not found. Starting fresh.")
    return ""

def set_last_published(link):
    with open(LAST_PUBLISHED_FILE, "w") as f:
        f.write(link)
    logging.info(f"Saved '{link}' as last published.")

# ... (rest of your helper functions) ...

# -------------- AI Rewriting in Spanish --------------------
def rewrite_article_spanish(content):
    logging.info("Attempting to rewrite article content.")
    if not content.strip():
        logging.warning("Content to rewrite is empty.")
        return ""
    api_url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    system = (
        "Eres un redactor profesional de deportes. "
        "Responde siempre en español. "
        "Reescribe el siguiente texto en español con un estilo natural, claro y fluido, "
        "100% único, sin plagio, en 3–5 párrafos separados por líneas en blanco. "
        "No incluyas nombres de autores ni menciones del sitio original. "
        "El texto debe estar limpio, sin letras sueltas ni fragmentos extraños."
    )
    payload = {
        "model": "meta-llama/llama-3-8b-instruct",
        "temperature": 0.6,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": content}
        ]
    }
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status() # This will raise an HTTPError for bad responses (4xx, 5xx)
        text = resp.json()["choices"][0]["message"]["content"].strip()
        text = clean_stray_letters(text)
        text = re.sub(r'\*{1,2}', '', text)
        text = re.sub(r'^\s*(#+)\s*(.+)$', r'<h2>\2</h2>', text, flags=re.MULTILINE)
        logging.info("Article content successfully rewritten.")
        return "\n\n".join(line for line in text.splitlines() if line.strip())
    except requests.exceptions.Timeout:
        logging.error("OpenRouter API call timed out for article rewrite.")
        return ""
    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling OpenRouter API for article rewrite: {e}. Response: {resp.text if 'resp' in locals() else 'No response'}")
        return ""
    except Exception as e:
        logging.error(f"An unexpected error occurred during article rewrite: {e}")
        return ""

def rewrite_title_spanish(title):
    logging.info("Attempting to rewrite title.")
    if not title.strip():
        logging.warning("Title to rewrite is empty.")
        return "Sin título"
    api_url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    system = (
        "Eres un redactor de titulares. "
        "Escribe un titular breve y llamativo en español con máximo 12 palabras, "
        "sin signos de puntuación ni caracteres extraños. "
        "Responde solo con el titular limpio y directo, sin letras sueltas."
    )
    payload = {
        "model": "meta-llama/llama-3-8b-instruct",
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": title}
        ]
    }
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        raw = clean_stray_letters(raw)
        raw = re.sub(r'\*{1,2}', '', raw)
        raw = re.sub(r'^\s*(#+)\s*(.+)$', r'<h2>\2</h2>', raw, flags=re.MULTILINE)
        clean = "".join(ch for ch in raw if ch.isalpha() or ch.isspace() or ch in "<>/h2")
        cleaned_title = re.sub(r'\s+', ' ', clean).strip()
        logging.info(f"Title successfully rewritten to: {cleaned_title}")
        return cleaned_title or title
    except requests.exceptions.Timeout:
        logging.error("OpenRouter API call timed out for title rewrite.")
        return title
    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling OpenRouter API for title rewrite: {e}. Response: {resp.text if 'resp' in locals() else 'No response'}")
        return title
    except Exception as e:
        logging.error(f"An unexpected error occurred during title rewrite: {e}")
        return title

# -------------- WordPress Integration -----------
def create_term(name, ttype):
    logging.info(f"Checking/creating term '{name}' of type '{ttype}'.")
    url = f"{WP_SITE_URL}/wp-json/wp/v2/{ttype}"
    auth = (WP_USERNAME, WP_APP_PASSWORD)
    try:
        r = requests.get(url, auth=auth, params={"search": name}, timeout=15)
        r.raise_for_status()
        items = r.json()
        if items:
            term_id = items[0]["id"]
            logging.info(f"Term '{name}' ({ttype}) already exists with ID: {term_id}")
            return term_id
        r = requests.post(url, auth=auth, json={"name": name}, timeout=15)
        r.raise_for_status()
        term_id = r.json()["id"]
        logging.info(f"Term '{name}' ({ttype}) created with ID: {term_id}")
        return term_id
    except requests.exceptions.RequestException as e:
        logging.error(f"Error creating/fetching term '{name}' ({ttype}): {e}. Response: {r.text if 'r' in locals() else 'No response'}")
        raise # Re-raise to stop execution if terms can't be created

def upload_image(buf_or_url, title):
    logging.info(f"Attempting to upload image for '{title}'.")
    try:
        if isinstance(buf_or_url, BytesIO):
            buf_or_url.seek(0)
            raw = buf_or_url.read()
            logging.info("Image source is BytesIO.")
        else:
            logging.info(f"Fetching image from URL: {buf_or_url}")
            resp = requests.get(buf_or_url, timeout=15); resp.raise_for_status()
            raw = resp.content
        
        data = compress_to_target(raw, max_kb=120)
        fname = re.sub(r'\s+', '_', title).strip("_")[:40] + ".webp"
        url = f"{WP_SITE_URL}/wp-json/wp/v2/media"
        headers = {"Content-Disposition": f'attachment; filename={fname}'}
        
        logging.info(f"Uploading image '{fname}' to WordPress.")
        r = requests.post(url, auth=(WP_USERNAME, WP_APP_PASSWORD), headers=headers,
                          files={"file": (fname, data)}, timeout=30)
        r.raise_for_status()
        media_id = r.json().get("id")
        logging.info(f"Image uploaded with Media ID: {media_id}")
        return media_id
    except requests.exceptions.RequestException as e:
        logging.error(f"WordPress image upload failed: {e}. Response: {r.text if 'r' in locals() else 'No response'}")
        logging.error("Returning None for media_id.")
        return None
    except Exception as e:
        logging.error(f"⚠️ Upload error: {e}")
        logging.error("Returning None for media_id.")
        return None

def publish_post(title, content, media_id, tags, meta_desc, focus_kw):
    logging.info(f"Attempting to publish post: '{title}'")
    try:
        cat_id  = create_term("Noticias", "categories")
        tag_ids = [create_term(t, "tags") for t in tags]
        
        payload = {
            "title": title,
            "content": content,
            "status": "publish",
            "categories": [cat_id],
            "tags": tag_ids,
            "featured_media": media_id if media_id else None, # Ensure None if media_id is 0 or invalid
            "meta": {
                "rank_math_description": meta_desc,
                "rank_math_focus_keyword": focus_kw
            }
        }
        logging.info(f"Publishing payload prepared. Title: {title}, Categories: {payload['categories']}, Tags: {payload['tags']}, Media ID: {payload['featured_media']}")
        r = requests.post(f"{WP_SITE_URL}/wp-json/wp/v2/posts",
                          auth=(WP_USERNAME, WP_APP_PASSWORD), json=payload, timeout=30)
        r.raise_for_status()
        post_link = r.json().get("link")
        logging.info(f"✅ Publicado: {post_link}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"WordPress post publication failed: {e}. Response: {r.text if 'r' in locals() else 'No response'}")
        return False
    except Exception as e:
        logging.error(f"An unexpected error occurred during post publication: {e}")
        return False

# ------------------ Main ------------------------
def main():
    logging.info("--- Script started ---")
    
    # Check if critical env vars are set (already done at global scope, but good to double check main)
    if not all([OPENROUTER_API_KEY, WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD]):
        logging.critical("One or more essential environment variables are missing. Exiting.")
        return

    last_published = get_last_published()
    feeds = ["https://jeinzmaciass.com/feed/"]
    entries = []
    for f in feeds:
        try:
            feed_data = feedparser.parse(f)
            if feed_data.bozo: # Check for well-formedness
                logging.warning(f"RSS feed '{f}' is not well-formed: {feed_data.bozo_exception}")
            entries.extend(feed_data.entries[:1])  # Only latest article
            logging.info(f"Successfully parsed feed: {f}")
        except Exception as e:
            logging.error(f"Error parsing RSS feed {f}: {e}")
            
    if not entries:
        logging.warning("⚠️ No articles found in any RSS feed, or all failed to parse. Exiting.")
        return

    latest = entries[0]
    logging.info(f"Latest article from RSS: {latest.link}")
    
    if latest.link == last_published:
        logging.info("ℹ️ No new article, skipping. Link matches last published.")
        return

    try:
        art = Article(latest.link); 
        logging.info(f"Downloading article from: {latest.link}")
        art.download(); 
        logging.info("Article downloaded. Parsing...")
        art.parse()
        logging.info(f"Article parsed. Text length: {len(art.text)}")
    except Exception as e:
        logging.error(f"Error downloading or parsing article from {latest.link}: {e}")
        return

    if len(art.text) < 300:
        logging.warning(f"Article content too short ({len(art.text)} chars). Skipping.")
        return

    clean = clean_stray_letters(clean_text(get_clean_paragraphs(art)))
    logging.info(f"Cleaned article content length: {len(clean)}")

    rewritten = rewrite_article_spanish(clean)
    if len(rewritten.split()) < 80:
        logging.warning(f"First rewrite attempt too short ({len(rewritten.split())} words). Retrying.")
        rewritten = rewrite_article_spanish(clean)
    if len(rewritten.split()) < 80:
        logging.error(f"Rewritten article content still too short ({len(rewritten.split())} words). Skipping post.")
        return
    logging.info(f"Final rewritten article content word count: {len(rewritten.split())}")

    new_title = rewrite_title_spanish(latest.title)
    if len(new_title.split()) < 3:
        logging.warning(f"First title rewrite attempt too short ({len(new_title.split())} words). Retrying.")
        new_title = rewrite_title_spanish(latest.title)
    if len(new_title.split()) < 3:
        logging.error(f"Rewritten title still too short ({len(new_title.split())} words). Using original title.")
        new_title = latest.title # Fallback to original title if AI fails repeatedly

    tags = [kw for kw,_ in kw_model.extract_keywords(clean,
                keyphrase_ngram_range=(1,2), stop_words='spanish', top_n=5)]
    logging.info(f"Generated keywords: {tags}")

    media_id = upload_image(art.top_image or DEFAULT_IMAGE_URL, new_title)
    if media_id is None and DEFAULT_IMAGE_URL: # Only log if default image was supposed to be used
        logging.warning(f"No image uploaded, using fallback or default if available. Media ID: {media_id}")
    elif media_id is None and not DEFAULT_IMAGE_URL:
        logging.warning("No image uploaded and DEFAULT_IMAGE_URL is not set. Post will be published without featured image.")

    meta_desc = rewritten[:155].replace("\n", " ")
    focus_kw  = tags[0] if tags else ""
    logging.info(f"Meta description: '{meta_desc[:50]}...'")
    logging.info(f"Focus keyword: '{focus_kw}'")


    if publish_post(new_title, rewritten, media_id, tags, meta_desc, focus_kw):
        set_last_published(latest.link)
    else:
        logging.error("Post publication failed. Not updating last_published.txt.")


    logging.info("--- Script finished ---")

if __name__ == "__main__":
    main()
