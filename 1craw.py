"""
pip install playwright
playwright install chromium
python craw.py
"""
import json
import random
import re
import time
from playwright.sync_api import sync_playwright

API = (
    "https://pmvhaven.com/api/videos"
    "?limit=32&page={page}"
    "&tags=Non-nude,Non+nude,Nonnude&tagMode=OR&expandTags=false"
)
PROXY = None  # e.g. "http://47.89.184.18:3128" ; None = connect directly
OUTPUT = "videos.json"
MAX_RETRIES = 3
MAX_VIDEOS = 2000  # stop crawling once more than this many videos are collected

# Candidate field names (the first one found is used). Adjust if your API differs.
VIDEO_URL_KEYS = ("videoUrl", "video_url", "url", "hlsUrl", "streamUrl", "src")
THUMB_KEYS = ("thumbnails", "thumbnailUrl", "thumbnail", "thumbnailUrls", "thumbnailSizes")


# Words to replace in title/description -> new word. Edit freely.
# Matching is case-insensitive, whole-word, and also catches s / ed / ing / er endings.
WORD_REPLACEMENTS = {
    "porn": "sexy",
    "pornography": "foxy",
    "pornstar": "model",
    "fuck": "mess",
    "fucking": "really",
    "motherfucker": "person",
    "shit": "stuff",
    "bitch": "girl",
    "slut": "woman",
    "whore": "female",
    "cock": "banana",
    "dick": "grape",
    "pussy": "kitty",
    "cum": "finish",
    "cumshot": "done",
    "blowjob": "kiss",
    "anal": "special",
    "nude": "bare",
    "naked": "bare",
    "sex": "love",
    "xxx": "special",
}

_REPLACE_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, WORD_REPLACEMENTS), key=len, reverse=True))
    + r")(s|ed|ing|er)?\b",
    re.IGNORECASE,
)


def clean_text(text):
    """Replace flagged words with their substitutes, keeping the original casing style."""
    if not text:
        return text

    def repl(m):
        new = WORD_REPLACEMENTS[m.group(1).lower()]
        word = m.group(1)
        if word.isupper() and len(word) > 1:
            return new.upper()
        if word[0].isupper():
            return new.capitalize()
        return new

    return _REPLACE_RE.sub(repl, text)


def _width_of(item, key=""):
    """Best-effort pixel width from a thumbnail dict or a size key like '320' / '320w'."""
    if isinstance(item, dict):
        for k in ("width", "w"):
            if isinstance(item.get(k), (int, float)):
                return item[k]
    m = re.search(r"\d+", str(key))
    return int(m.group()) if m else None


def smallest_thumbnail(v):
    """Return the URL of the smallest thumbnail available."""
    cands = []  # (width or None, url)
    for key in THUMB_KEYS:
        t = v.get(key)
        if isinstance(t, str):
            cands.append((None, t))
        elif isinstance(t, list):
            for item in t:
                if isinstance(item, str):
                    cands.append((_width_of(item), item))
                elif isinstance(item, dict):
                    url = item.get("url") or item.get("src")
                    if url:
                        cands.append((_width_of(item), url))
        elif isinstance(t, dict):
            for size_key, item in t.items():
                url = item if isinstance(item, str) else (item or {}).get("url")
                if url:
                    cands.append((_width_of(item, size_key), url))
    if not cands:
        return None
    sized = [c for c in cands if c[0] is not None]
    return min(sized)[1] if sized else cands[0][1]


def slim(v):
    """Keep only the fields we care about."""
    title = clean_text(v.get("title"))
    video_url = next((v[k] for k in VIDEO_URL_KEYS if v.get(k)), None)
    return {
        "id": v.get("_id"),
        "title": title,
        "description": title,  # description = title
        "tags": v.get("tags", []),
        "videoUrl": video_url,
        "thumbnailUrl": smallest_thumbnail(v),
        "durationSeconds": v.get("durationSeconds"),
        "views": v.get("views"),
        "date": v.get("releaseDate"),
    }


def fetch_page(page, n):
    """Open one API page in the browser and return the parsed JSON."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = page.goto(API.format(page=n), wait_until="domcontentloaded", timeout=60_000)
            if resp is None or resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status if resp else 'no response'}")
            # Chromium shows raw JSON inside a <pre>; fall back to body text
            if page.locator("pre").count():
                text = page.locator("pre").first.inner_text(timeout=15_000)
            else:
                text = page.inner_text("body")
            data = json.loads(text)
            if not data.get("success"):
                raise RuntimeError("success=false")
            return data
        except Exception as e:
            print(f"  page {n} attempt {attempt}/{MAX_RETRIES} failed: {e}")
            time.sleep(2 * attempt)
    return None


def main():
    videos = {}  # keyed by _id to avoid duplicates between pages

    with sync_playwright() as p:
        launch_args = {"headless": True}
        if PROXY:
            launch_args["proxy"] = {"server": PROXY}
        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(
            ignore_https_errors=True,  # needed if the proxy re-signs HTTPS
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        first = fetch_page(page, 1)
        if not first:
            print("Could not load page 1, aborting.")
            browser.close()
            return

        total_pages = first["pagination"]["totalPages"]
        print(f"Total videos: {first['pagination']['total']}, pages: {total_pages}")
        for v in first["videos"]:
            videos[v["_id"]] = slim(v)

        for n in range(2, total_pages + 1):
            if len(videos) > MAX_VIDEOS:
                print(f"Collected {len(videos)} videos (> {MAX_VIDEOS}), stopping.")
                break
            data = fetch_page(page, n)
            if data is None:
                print(f"Skipping page {n}")
                continue
            for v in data["videos"]:
                videos[v["_id"]] = slim(v)
            print(f"page {n}/{total_pages} ok  (collected {len(videos)})")
            time.sleep(random.uniform(1.0, 2.5))  # be polite to the server

        browser.close()

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(list(videos.values()), f, ensure_ascii=False, indent=2)
    print(f"Saved {len(videos)} videos to {OUTPUT}")


if __name__ == "__main__":
    main()