import os
import feedparser
import requests
from newspaper import Article
from dotenv import load_dotenv
import re
from PIL import Image, ImageOps
from io import BytesIO
from keybert import KeyBERT

# Load environment variables
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
WP_SITE_URL        = os.getenv("WP_SITE_URL")
WP_USERNAME        = os.getenv("WP_USERNAME")
WP_APP_PASSWORD    = os.getenv("WP_APP_PASSWORD")
DEFAULT_IMAGE_URL  = os.getenv("DEFAULT_IMAGE_URL")

LAST_PUBLISHED_FILE = "last_published.txt"
kw_model = KeyBERT()

# ----------------- Helpers -----------------
def get_last_published():
    if os.path.exists(LAST_PUBLISHED_FILE):
        with open(LAST_PUBLISHED_FILE, "r") as f:
            return f.read().strip()
    return ""

def set_last_published(link):
    with open(LAST_PUBLISHED_FILE, "w") as f:
        f.write(link)

def clean_stray_letters(text):
    text = re.sub(r'^\s*[A-Za-z]\s+', '', text)
    text = re.sub(r'\s+[A-Za-z]\s*$', '', text)
    return text.strip()

def get_clean_paragraphs(article):
    paragraphs = [p.strip() for p in article.text.split("\n") if len(p.split()) >= 5]
    return "\n\n".join(paragraphs)

# ----------------- Text Cleaning -----------------
def clean_text(text):
    ad_lines = [
        "⚽ Descarga la App de JEINZ MACIAS Canales y Fútbol En Vivo GRATIS",
        "Disfruta partidos, canales y más ¡Totalmente gratis en Android!",
        "📲 Descargar APK",
        "⚽ Disfruta de partidos, canales y más ¡Totalmente gratis en Android!"
    ]
    for ad in ad_lines:
        text = text.replace(ad, "")

    patterns = [
        r'(Share Save|[\d]+ (hours|minutes) ago|Image source.*?)',
        r'http\S+|www\.\S+',
        r'\[.*?\]|\(.*?\)',
        r'["“”]|--|—|–',
        r'\*{1,2}'
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)

    text = re.sub(r'^\s*(#+)\s*(.+)$', r'<h2>\2</h2>', text, flags=re.MULTILINE)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip() and not line.lower().startswith("title:"))

# --------- Image Compression Helper -----------
def compress_to_target(raw_bytes: bytes, max_kb: int = 120, quality: int = 85) -> bytes:
    img = Image.open(BytesIO(raw_bytes)).convert('RGB')
    try:
        img = ImageOps.exif_transpose(img)
    except:
        pass
    buf = BytesIO()
    img.save(buf, format='WEBP', quality=quality, lossless=False, optimize=True)
    return buf.getvalue()

# -------------- AI Rewriting in Spanish --------------------
def rewrite_article_spanish(content):
    if not content.strip():
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
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        text = clean_stray_letters(text)
        text = re.sub(r'\*{1,2}', '', text)
        text = re.sub(r'^\s*(#+)\s*(.+)$', r'<h2>\2</h2>', text, flags=re.MULTILINE)
        return "\n\n".join(line for line in text.splitlines() if line.strip())
    except:
        return ""

def rewrite_title_spanish(title):
    if not title.strip():
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
        return re.sub(r'\s+', ' ', clean).strip() or title
    except:
        return title

# -------------- WordPress Integration -----------
def create_term(name, ttype):
    url = f"{WP_SITE_URL}/wp-json/wp/v2/{ttype}"
    auth = (WP_USERNAME, WP_APP_PASSWORD)
    r = requests.get(url, auth=auth, params={"search": name}, timeout=15)
    r.raise_for_status()
    items = r.json()
    if items:
        return items[0]["id"]
    r = requests.post(url, auth=auth, json={"name": name}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]

def upload_image(buf_or_url, title):
    try:
        if isinstance(buf_or_url, BytesIO):
            buf_or_url.seek(0)
            raw = buf_or_url.read()
        else:
            resp = requests.get(buf_or_url, timeout=15); resp.raise_for_status()
            raw = resp.content
        data = compress_to_target(raw, max_kb=120)
        fname = re.sub(r'\s+', '_', title).strip("_")[:40] + ".webp"
        url = f"{WP_SITE_URL}/wp-json/wp/v2/media"
        headers = {"Content-Disposition": f'attachment; filename={fname}'}
        r = requests.post(url, auth=(WP_USERNAME, WP_APP_PASSWORD), headers=headers,
                          files={"file": (fname, data)}, timeout=30)
        r.raise_for_status()
        return r.json().get("id")
    except Exception as e:
        print("⚠️ Upload error:", e)
        return None

def publish_post(title, content, media_id, tags, meta_desc, focus_kw):
    cat_id  = create_term("Noticias", "categories")
    tag_ids = [create_term(t, "tags") for t in tags]
    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [cat_id],
        "tags": tag_ids,
        "featured_media": media_id,
        "meta": {
            "rank_math_description": meta_desc,
            "rank_math_focus_keyword": focus_kw
        }
    }
    r = requests.post(f"{WP_SITE_URL}/wp-json/wp/v2/posts",
                      auth=(WP_USERNAME, WP_APP_PASSWORD), json=payload, timeout=30)
    r.raise_for_status()
    print("✅ Publicado:", r.json().get("link"))

# ------------------ Main ------------------------
def main():
    last_published = get_last_published()
    feeds = ["https://jeinzmaciass.com/feed/"]
    entries = []
    for f in feeds:
        entries.extend(feedparser.parse(f).entries[:1])  # Only latest article

    if not entries:
        print("⚠️ No articles found")
        return

    latest = entries[0]
    if latest.link == last_published:
        print("ℹ️ No new article, skipping.")
        return

    art = Article(latest.link); art.download(); art.parse()
    if len(art.text) < 300:
        return

    clean = clean_stray_letters(clean_text(get_clean_paragraphs(art)))

    rewritten = rewrite_article_spanish(clean)
    if len(rewritten.split()) < 80:
        rewritten = rewrite_article_spanish(clean)
    if len(rewritten.split()) < 80:
        return

    new_title = rewrite_title_spanish(latest.title)
    if len(new_title.split()) < 3:
        new_title = rewrite_title_spanish(latest.title)

    tags = [kw for kw,_ in kw_model.extract_keywords(clean,
                keyphrase_ngram_range=(1,2), stop_words='spanish', top_n=5)]

    media_id = upload_image(art.top_image or DEFAULT_IMAGE_URL, new_title)
    meta_desc = rewritten[:155].replace("\n", " ")
    focus_kw  = tags[0] if tags else ""

    publish_post(new_title, rewritten, media_id, tags, meta_desc, focus_kw)
    set_last_published(latest.link)

if __name__ == "__main__":
    main()
