import requests
import os
import html
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

# ─── Optional: Google Sheets ─────────────────────────────────────────────
try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False

# ─── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Config (SAFE ENV HANDLING) ─────────────────────────────────────────
RAPIDAPI_KEY     = os.environ.get("RAPIDAPI_KEY")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not RAPIDAPI_KEY or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("Missing required environment variables")

GSHEET_CREDENTIALS = os.environ.get("GSHEET_CREDENTIALS", "")
GSHEET_ID          = os.environ.get("GSHEET_ID", "")
GSHEET_SHEET_NAME  = "Jobs"

SEEN_JOBS_FILE    = Path("seen_jobs.txt")
MAX_SEEN_JOBS     = 2000
MAX_JOBS_PER_RUN  = 15

# ─── SEARCH QUERIES ─────────────────────────────────────────────────────
SEARCH_QUERIES = [
    # PhD (Worldwide)
    "cellular molecular biology phd",
    "molecular biology phd",
    "doctoral student molecular biology",
    "PhD microbiology",
    "PhD molecular microbiology",

    # PhD (Sweden)
    "cellular molecular biology phd Sweden",
    "molecular biology phd Sweden",
    "PhD microbiology Sweden",

    # Research
    "research assistant",
    "research technician",

    # Lab (Sweden focus)
    "lab technician Sweden",
    "lab technician Gothenburg",
    "laboratory technician Sweden",
    "laboratory technician Gothenburg",

    # Specialized
    "AFM microscopy technician",
]

# ─── BLACKLIST ──────────────────────────────────────────────────────────
BLACKLIST_KEYWORDS = [
    "senior",
    "manager",
    "director",
    "principal",
    "head of",
    "intern",
    "internship",
    "volunteer",
    "unpaid",
    "sales",
    "marketing",
    "software engineer",
]

# ─── CACHE ──────────────────────────────────────────────────────────────
def load_seen_jobs():
    if SEEN_JOBS_FILE.exists():
        return set(SEEN_JOBS_FILE.read_text().splitlines())
    return set()

def save_seen_jobs(seen):
    data = list(seen)[-MAX_SEEN_JOBS:]
    SEEN_JOBS_FILE.write_text("\n".join(data))

# ─── API ────────────────────────────────────────────────────────────────
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

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)

            if resp.status_code == 429:
                time.sleep(60)
                continue

            if resp.status_code == 403:
                log.error("API key error (403)")
                return []

            resp.raise_for_status()

            try:
                data = resp.json()
            except ValueError:
                log.error("Invalid JSON response")
                return []

            if data.get("status") != "OK":
                return []

            return data.get("data", [])

        except requests.exceptions.Timeout:
            time.sleep(5 * attempt)
        except requests.exceptions.RequestException as e:
            log.error(f"Request error: {e}")
            time.sleep(5 * attempt)

    return []

# ─── FILTER ─────────────────────────────────────────────────────────────
def is_blacklisted(job):
    text = f"{job.get('job_title','')} {job.get('job_description','')}".lower()
    return any(k in text for k in BLACKLIST_KEYWORDS)

# ─── TELEGRAM ───────────────────────────────────────────────────────────
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
        return r.ok
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False

# ─── FORMAT ─────────────────────────────────────────────────────────────
def extract_salary(job):
    if job.get("job_salary_string"):
        return job["job_salary_string"]
    return ""

def format_job(job):
    title   = html.escape(job.get("job_title",""))
    company = html.escape(job.get("employer_name",""))
    city    = job.get("job_city","")
    country = job.get("job_country","")

    location = ", ".join([x for x in [city, country] if x]) or "Remote"

    link = job.get("job_apply_link") or job.get("job_google_link") or ""
    salary = extract_salary(job)

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

    for query in SEARCH_QUERIES:
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

    if not new_jobs:
        send_telegram("No new jobs found today.")
        save_seen_jobs(seen)
        return

    send_telegram(f"New jobs found: {len(new_jobs)}")

    for job in new_jobs[:MAX_JOBS_PER_RUN]:
        send_telegram(format_job(job))
        time.sleep(0.8)

    save_seen_jobs(seen)

if __name__ == "__main__":
    main()
