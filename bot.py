import requests
import os
import html
import time
import logging
from pathlib import Path

# ─── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── ENV (MULTI-BOT SUPPORT) ─────────────────────────────────────────────
RAPIDAPI_KEY     = os.environ.get("RAPIDAPI_KEY")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SEARCH_QUERIES = os.environ.get("SEARCH_QUERIES", "").split("|")
BLACKLIST_KEYWORDS = os.environ.get("BLACKLIST_KEYWORDS", "").split("|")

if not RAPIDAPI_KEY or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("Missing required environment variables")

# ─── SETTINGS ────────────────────────────────────────────────────────────
SEEN_JOBS_FILE    = Path("seen_jobs.txt")
MAX_SEEN_JOBS     = 2000
MAX_JOBS_PER_RUN  = 15

# ─── CACHE ───────────────────────────────────────────────────────────────
def load_seen_jobs():
    if SEEN_JOBS_FILE.exists():
        return set(SEEN_JOBS_FILE.read_text().splitlines())
    return set()

def save_seen_jobs(seen):
    data = list(seen)[-MAX_SEEN_JOBS:]
    SEEN_JOBS_FILE.write_text("\n".join(data))

# ─── API ─────────────────────────────────────────────────────────────────
def search_jobs(query, retries=3):
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }

    params = {
        "query": query,
        "num_pages": "1",
        "date_posted": "3days",
        "work_from_home": "true",
    }

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)

            if resp.status_code == 429:
                time.sleep(60)
                continue

            if resp.status_code == 403:
                log.error("API key error (403)")
                return []

            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "OK":
                return []

            return data.get("data", [])

        except Exception as e:
            log.error(f"Request error: {e}")
            time.sleep(5 * (attempt + 1))

    return []

# ─── FILTER ──────────────────────────────────────────────────────────────
def is_blacklisted(job):
    text = f"{job.get('job_title','')} {job.get('job_description','')}".lower()
    return any(k.strip().lower() in text for k in BLACKLIST_KEYWORDS if k.strip())

# ─── TELEGRAM ────────────────────────────────────────────────────────────
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        if not r.ok:
            log.error(f"Telegram error: {r.text}")
        return r.ok
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False

# ─── FORMAT ──────────────────────────────────────────────────────────────
def format_job(job):
    title   = html.escape(job.get("job_title", ""))
    company = html.escape(job.get("employer_name", ""))

    city    = job.get("job_city", "")
    country = job.get("job_country", "")
    location = ", ".join([x for x in [city, country] if x]) or "Remote"

    link = job.get("job_apply_link") or job.get("job_google_link") or ""
    salary = job.get("job_salary_string", "")

    msg = [
        f"💼 <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]

    if salary:
        msg.append(f"💰 {html.escape(salary)}")

    if link:
        msg.append(f'🔗 <a href="{link}">Apply</a>')

    return "\n".join(msg)

# ─── MAIN ───────────────────────────────────────────────────────────────
def main():
    seen = load_seen_jobs()
    new_jobs = []

    log.info(f"Searching {len(SEARCH_QUERIES)} queries")

    for query in SEARCH_QUERIES:
        if not query.strip():
            continue

        log.info(f"Searching: {query}")
        jobs = search_jobs(query)

        for job in jobs:
            job_id = job.get("job_id") or job.get("job_apply_link")

            if not job_id:
                continue

            if job_id in seen:
                continue

            if is_blacklisted(job):
                continue

            seen.add(job_id)
            new_jobs.append(job)

        time.sleep(1)

    log.info(f"New jobs found: {len(new_jobs)}")

    if not new_jobs:
        send_telegram("No new jobs found today.")
        save_seen_jobs(seen)
        return

    send_telegram(f"🔥 New jobs found: {len(new_jobs)}")

    for job in new_jobs[:MAX_JOBS_PER_RUN]:
        send_telegram(format_job(job))
        time.sleep(0.8)

    save_seen_jobs(seen)

    log.info("Done.")

if __name__ == "__main__":
    main()
