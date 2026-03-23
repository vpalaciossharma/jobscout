#!/usr/bin/env python3
"""
Job Scout — Daily PM Job Alert for Vanessa Palacios Sharma
=========================================================
Fetches Senior PM jobs from LinkedIn, Indeed, Glassdoor via JSearch API,
scores each role against Vanessa's AdTech/Technical PM profile,
and sends a formatted HTML digest via Gmail.

Usage:
    python3 job_scout.py               # Run normally
    python3 job_scout.py --test        # Test email with sample data (no API call)
    python3 job_scout.py --preview     # Print jobs to console without emailing
"""

import json
import os
import re
import sys
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    import requests
except ImportError:
    os.system("pip install requests --break-system-packages -q")
    import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"

def load_config():
    """Load credentials from config.json, falling back to env vars."""
    config = {
        "rapidapi_key": os.environ.get("RAPIDAPI_KEY", ""),
        "gmail_address": os.environ.get("GMAIL_ADDRESS", "sharma.portland@gmail.com"),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD", ""),
        "recipient_email": os.environ.get("RECIPIENT_EMAIL", "vpalaciossharma@gmail.com"),
    }
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            file_config = json.load(f)
            config.update(file_config)
    return config


# ─────────────────────────────────────────────────────────────────────────────
# VANESSA'S PROFILE — keyword banks for job scoring
# ─────────────────────────────────────────────────────────────────────────────

# Core AdTech expertise — highest weight
ADTECH_KEYWORDS = [
    "adtech", "ad tech", "ad server", "ad serving", "ssp", "supply-side platform",
    "supply side platform", "dsp", "demand-side platform", "demand side platform",
    "ssai", "server-side ad insertion", "ctv", "ott", "connected tv",
    "programmatic", "rtb", "real-time bidding", "real time bidding",
    "monetization", "direct io", "ad operations", "ad platform", "ad network",
    "publisher monetization", "media monetization", "video advertising",
    "digital advertising", "display advertising", "header bidding", "prebid",
    "openrtb", "ad inventory", "ad impression", "ad trafficking",
    "campaign management", "ad measurement", "ad tracking", "ad beacon",
    "mediatailor", "freewheel", "xandr", "magnite", "appnexus", "pubmatic",
    "the trade desk", "liveramp", "iab", "video streaming", "streaming platform",
    "ott platform", "broadcast", "video platform", "media platform",
]

# Technical PM skills
TECHNICAL_PM_KEYWORDS = [
    "technical product manager", "technical pm", "sr. technical", "senior technical",
    "api", "microservices", "platform engineering", "agile", "scrum", "kanban",
    "sql", "data analysis", "aws", "cloud", "backend", "infrastructure",
    "mobile", "android", "ios", "architecture", "saas", "b2b", "b2c",
    "analytics platform", "dashboard", "measurement platform", "experimentation",
    "a/b test", "a/b testing", "monitoring", "ci/cd", "devops", "scalability",
    "latency", "data pipeline", "machine learning", "ai", "llm",
    "product analytics", "event tracking", "sdk",
]

# General PM signals
PM_KEYWORDS = [
    "product manager", "product management", "product strategy", "roadmap",
    "product roadmap", "stakeholder management", "cross-functional", "go-to-market",
    "gtm strategy", "backlog", "sprint planning", "okr", "kpi", "user research",
    "product owner", "product discovery", "product vision", "product lifecycle",
]

# Senior-level title signals
SENIOR_TITLE_SIGNALS = [
    "senior", "sr.", "sr ", "staff product", "principal product",
    "lead product", "director of product", "director, product",
    "vp of product", "vice president of product", "head of product",
    "group product manager", "gpm",
]

# Phrases that indicate junior roles — auto-disqualify
JUNIOR_SIGNALS = [
    "entry level", "entry-level", "junior", "associate product manager",
    "apm program", "new grad", "recent graduate", "0-2 years", "1-2 years",
    "intern", "internship",
]

# Bonus: well-known companies Vanessa would likely target
TOP_COMPANIES = [
    "amazon", "aws", "google", "alphabet", "meta", "apple", "netflix",
    "microsoft", "hulu", "disney", "comcast", "nbcu", "roku", "peacock",
    "paramount", "spotify", "twitch", "youtube", "adobe", "salesforce",
    "oracle", "snap", "pinterest", "linkedin", "twitter", "x corp",
    "verizon media", "iheartmedia", "fox", "cbs", "viacom", "warner",
    "discovery", "showtime", "hbo", "max", "pluto tv", "tubi", "crackle",
    "freewheel", "magnite", "pubmatic", "openx", "criteo", "trade desk",
]


# ─────────────────────────────────────────────────────────────────────────────
# JOB SCORING
# ─────────────────────────────────────────────────────────────────────────────

def score_job(job: dict) -> tuple[int, list[str]]:
    """
    Score a job posting 0–100 based on alignment with Vanessa's profile.
    Returns (score, [reason strings]).
    score = 0 means skip this job entirely.
    """
    title = (job.get("job_title") or "").lower()
    description = (job.get("job_description") or "").lower()
    employer = (job.get("employer_name") or "").lower()
    full_text = f"{title} {employer} {description}"

    # ── Hard disqualifiers ──────────────────────────────────────────────────
    for signal in JUNIOR_SIGNALS:
        if signal in full_text:
            return 0, []

    # Must be a product management role
    if not any(k in full_text for k in [
        "product manager", "product owner", "product lead",
        "head of product", "vp of product", "director of product",
    ]):
        return 0, []

    # ── Senior level check ──────────────────────────────────────────────────
    is_senior = any(s in title for s in SENIOR_TITLE_SIGNALS)
    if not is_senior:
        # Rescue if description is clearly senior-scoped
        desc_top = description[:600]
        is_senior = any(s in desc_top for s in ["7+ years", "8+ years", "10+ years",
                                                  "senior", "staff", "principal", "lead"])
    if not is_senior:
        return 0, []

    score = 20  # base for qualifying senior PM
    reasons = []

    # ── AdTech match (Vanessa's core expertise, highest weight) ────────────
    adtech_hits = [k for k in ADTECH_KEYWORDS if k in full_text]
    if adtech_hits:
        adtech_score = min(40, len(set(adtech_hits)) * 8)
        score += adtech_score
        display = sorted(set(adtech_hits), key=lambda x: -len(x))[:4]
        reasons.append(("🎯 AdTech match", ", ".join(display)))

    # ── Technical PM match ─────────────────────────────────────────────────
    tech_hits = [k for k in TECHNICAL_PM_KEYWORDS if k in full_text]
    if tech_hits:
        tech_score = min(25, len(set(tech_hits)) * 5)
        score += tech_score
        display = sorted(set(tech_hits), key=lambda x: -len(x))[:3]
        reasons.append(("⚙️ Technical skills", ", ".join(display)))

    # ── General PM match ───────────────────────────────────────────────────
    pm_hits = [k for k in PM_KEYWORDS if k in full_text]
    if pm_hits:
        score += min(10, len(set(pm_hits)) * 2)
        display = sorted(set(pm_hits))[:2]
        reasons.append(("📋 PM competencies", ", ".join(display)))

    # ── Company bonus ──────────────────────────────────────────────────────
    for co in TOP_COMPANIES:
        if co in employer:
            score += 5
            reasons.append(("🏢 Notable company", job.get("employer_name", "")))
            break

    # ── Reframe indicator ─────────────────────────────────────────────────
    # If AdTech score is low but general platform/monetization work exists
    reframe_keywords = ["platform", "monetization", "revenue", "publisher",
                        "media", "streaming", "measurement", "analytics"]
    reframe_hits = [k for k in reframe_keywords if k in full_text]
    if adtech_hits == [] and len(reframe_hits) >= 3:
        score += 8
        reasons.append(("🔄 Transferable fit", ", ".join(reframe_hits[:3])))

    return min(score, 100), reasons


def is_portland_or_remote(job: dict) -> bool:
    """Return True if the job is in Portland, OR or is remote-eligible."""
    city = (job.get("job_city") or "").lower()
    state = (job.get("job_state") or "").lower()
    is_remote = job.get("job_is_remote", False)
    description = (job.get("job_description") or "").lower()[:400]
    title = (job.get("job_title") or "").lower()

    if is_remote:
        return True
    if "remote" in title:
        return True
    if "remote" in description and "not remote" not in description:
        return True
    if "portland" in city:
        return True
    # Broad remote signals in description
    if any(phrase in description for phrase in [
        "work from home", "work from anywhere", "fully remote", "100% remote",
        "us remote", "remote us", "remote, us",
    ]):
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# JOB FETCHING (JSearch via RapidAPI)
# ─────────────────────────────────────────────────────────────────────────────

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"

SEARCH_QUERIES = [
    # Portland-specific
    {"query": "Senior Product Manager Portland Oregon", "num_pages": "2", "date_posted": "3days"},
    {"query": "Senior Technical Product Manager Portland Oregon", "num_pages": "2", "date_posted": "week"},
    # Remote
    {"query": "Senior Technical Product Manager AdTech remote USA", "num_pages": "2", "date_posted": "3days"},
    {"query": "Senior Product Manager programmatic advertising remote", "num_pages": "2", "date_posted": "week"},
    {"query": "Senior Product Manager CTV OTT streaming remote", "num_pages": "2", "date_posted": "week"},
    {"query": "Staff Principal Product Manager AdTech monetization remote", "num_pages": "2", "date_posted": "week"},
]


def fetch_jobs(api_key: str) -> list[dict]:
    """Fetch jobs from JSearch API across multiple queries, deduplicated."""
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    all_jobs = {}  # job_id → job dict (deduplication)

    for params_base in SEARCH_QUERIES:
        params = {**params_base, "country": "us", "language": "en"}
        try:
            resp = requests.get(JSEARCH_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            jobs = data.get("data", [])
            for job in jobs:
                jid = job.get("job_id") or job.get("job_apply_link", "")
                if jid and jid not in all_jobs:
                    all_jobs[jid] = job
        except requests.exceptions.RequestException as e:
            print(f"[WARN] JSearch query '{params_base['query']}' failed: {e}")
            continue

    return list(all_jobs.values())


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL RENDERING
# ─────────────────────────────────────────────────────────────────────────────

def render_source_badge(publisher: str) -> str:
    """Return a colored HTML badge for the job source."""
    pub = (publisher or "").lower()
    if "linkedin" in pub:
        color, label = "#0077b5", "LinkedIn"
    elif "indeed" in pub:
        color, label = "#003a9b", "Indeed"
    elif "glassdoor" in pub:
        color, label = "#0caa41", "Glassdoor"
    elif "ziprecruiter" in pub:
        color, label = "#4a154b", "ZipRecruiter"
    else:
        color, label = "#555", publisher or "Job Board"
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:bold;'
        f'letter-spacing:.5px">{label}</span>'
    )


def score_bar(score: int) -> str:
    """Render a small colored progress bar for the match score."""
    if score >= 75:
        bar_color = "#22c55e"   # green
        label = "Strong Match"
    elif score >= 50:
        bar_color = "#f59e0b"   # amber
        label = "Good Match"
    else:
        bar_color = "#94a3b8"   # slate
        label = "Potential Fit"
    width = score
    return (
        f'<div style="display:flex;align-items:center;gap:8px;margin:6px 0">'
        f'<div style="flex:1;background:#e2e8f0;border-radius:99px;height:6px">'
        f'<div style="width:{width}%;background:{bar_color};height:6px;border-radius:99px"></div>'
        f'</div>'
        f'<span style="font-size:11px;color:{bar_color};font-weight:600;white-space:nowrap">'
        f'{score}% — {label}</span>'
        f'</div>'
    )


def render_job_card(job: dict, score: int, reasons: list[tuple]) -> str:
    """Render a single job as an HTML card."""
    title = job.get("job_title") or "Product Manager"
    company = job.get("employer_name") or "Company"
    city = job.get("job_city") or ""
    state = job.get("job_state") or ""
    is_remote = job.get("job_is_remote", False)
    apply_link = job.get("job_apply_link") or "#"
    publisher = job.get("job_publisher") or ""
    logo = job.get("employer_logo") or ""

    # Location string
    if is_remote and city:
        location = f"{city}, {state} · Remote"
    elif is_remote:
        location = "Remote · USA"
    elif city:
        location = f"{city}, {state}"
    else:
        location = "Portland, OR"

    # Posted date
    posted_ts = job.get("job_posted_at_timestamp")
    if posted_ts:
        posted_dt = datetime.fromtimestamp(posted_ts, tz=timezone.utc)
        days_ago = (datetime.now(timezone.utc) - posted_dt).days
        if days_ago == 0:
            posted_str = "Today"
        elif days_ago == 1:
            posted_str = "Yesterday"
        else:
            posted_str = f"{days_ago} days ago"
    else:
        posted_str = "Recently"

    # Salary (if available)
    sal_min = job.get("job_min_salary")
    sal_max = job.get("job_max_salary")
    sal_currency = job.get("job_salary_currency") or "USD"
    salary_html = ""
    if sal_min and sal_max:
        salary_html = (
            f'<span style="color:#0f766e;font-weight:600">'
            f'${int(sal_min):,} – ${int(sal_max):,} {sal_currency}</span> · '
        )
    elif sal_max:
        salary_html = f'<span style="color:#0f766e;font-weight:600">Up to ${int(sal_max):,} {sal_currency}</span> · '

    # Description snippet
    desc_raw = (job.get("job_description") or "").strip()
    # Take first ~300 chars, strip markdown-ish noise
    desc_snippet = re.sub(r"\s+", " ", desc_raw[:350]).strip()
    if len(desc_raw) > 350:
        desc_snippet += "…"

    # Reason tags
    reason_tags_html = ""
    for icon_label, value in reasons[:4]:
        reason_tags_html += (
            f'<div style="background:#f1f5f9;border-radius:6px;padding:4px 10px;'
            f'margin:3px 0;font-size:12px;color:#334155">'
            f'<strong>{icon_label}:</strong> {value}</div>'
        )

    # Logo
    logo_html = ""
    if logo:
        logo_html = (
            f'<img src="{logo}" alt="{company}" '
            f'style="width:40px;height:40px;object-fit:contain;border-radius:6px;'
            f'border:1px solid #e2e8f0;flex-shrink:0" onerror="this.style.display=\'none\'">'
        )

    return f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;
                padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.05)">

      <!-- Header row -->
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
        <div style="flex:1">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
            {render_source_badge(publisher)}
            <span style="color:#64748b;font-size:12px">Posted {posted_str}</span>
          </div>
          <h3 style="margin:0 0 4px;font-size:17px;font-weight:700;color:#0f172a">{title}</h3>
          <div style="color:#475569;font-size:13px;margin-bottom:4px">
            <strong>{company}</strong> · {salary_html}{location}
          </div>
        </div>
        {logo_html}
      </div>

      <!-- Match score bar -->
      {score_bar(score)}

      <!-- Description snippet -->
      <p style="font-size:13px;color:#64748b;margin:8px 0;line-height:1.5">{desc_snippet}</p>

      <!-- Match reasons -->
      <div style="margin:10px 0 12px">
        {reason_tags_html}
      </div>

      <!-- Apply button -->
      <a href="{apply_link}" target="_blank"
         style="display:inline-block;background:#1e40af;color:#fff;text-decoration:none;
                padding:8px 20px;border-radius:8px;font-size:13px;font-weight:600">
        View &amp; Apply →
      </a>
    </div>
    """


def build_email_html(scored_jobs: list[tuple], today: str) -> str:
    """Build the full HTML email body."""
    strong = [j for j in scored_jobs if j[0] >= 75]
    good = [j for j in scored_jobs if 50 <= j[0] < 75]
    potential = [j for j in scored_jobs if j[0] < 50]

    def section(title_text: str, emoji: str, jobs_subset: list) -> str:
        if not jobs_subset:
            return ""
        cards = "".join(render_job_card(job, score, reasons)
                        for score, job, reasons in jobs_subset)
        return f"""
        <div style="margin-bottom:32px">
          <h2 style="font-size:18px;font-weight:700;color:#0f172a;
                     border-left:4px solid #1e40af;padding-left:12px;margin-bottom:16px">
            {emoji} {title_text} <span style="font-size:14px;color:#64748b;font-weight:400">({len(jobs_subset)})</span>
          </h2>
          {cards}
        </div>
        """

    total = len(scored_jobs)
    body_sections = (
        section("Strong Match", "🎯", strong)
        + section("Good Match", "✅", good)
        + section("Potential Fit", "🔄", potential)
    )

    if not body_sections:
        body_sections = """
        <div style="text-align:center;padding:40px;color:#64748b">
          <p style="font-size:16px">No new matching jobs found today.</p>
          <p style="font-size:13px">Check back tomorrow — new roles are posted daily.</p>
        </div>
        """

    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">

  <div style="max-width:680px;margin:0 auto;padding:24px 16px">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1e3a8a,#1e40af);color:#fff;
                border-radius:16px;padding:28px 32px;margin-bottom:24px">
      <div style="font-size:12px;opacity:.8;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px">
        Job Scout · {today}
      </div>
      <h1 style="margin:0 0 8px;font-size:24px;font-weight:800">
        Your Daily PM Job Alert
      </h1>
      <p style="margin:0;opacity:.85;font-size:14px">
        {total} Senior Product Manager role{"s" if total != 1 else ""} matched your profile today ·
        Portland, OR &amp; Remote
      </p>
    </div>

    <!-- Profile tag line -->
    <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;
                padding:14px 18px;margin-bottom:24px;font-size:13px;color:#1e40af">
      <strong>Matching criteria:</strong> Senior+ level · AdTech / Technical PM focus ·
      Portland, OR or Remote · 9 years PM experience · AWS / Microsoft background
    </div>

    <!-- Job sections -->
    {body_sections}

    <!-- Footer -->
    <div style="text-align:center;padding:24px 0;color:#94a3b8;font-size:12px;
                border-top:1px solid #e2e8f0;margin-top:8px">
      <p style="margin:0 0 4px">Job Scout · Automated daily digest</p>
      <p style="margin:0">Sources: LinkedIn · Indeed · Glassdoor · ZipRecruiter via JSearch API</p>
    </div>

  </div>

</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL SENDING
# ─────────────────────────────────────────────────────────────────────────────

def send_email(config: dict, subject: str, html_body: str):
    """Send HTML email via Gmail SMTP using App Password."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["gmail_address"]
    msg["To"] = config["recipient_email"]
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(config["gmail_address"], config["gmail_app_password"])
        server.sendmail(config["gmail_address"], config["recipient_email"], msg.as_string())


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    config = load_config()

    # ── Validate config ──────────────────────────────────────────────────────
    if mode != "--test":
        missing = [k for k in ("rapidapi_key", "gmail_address", "gmail_app_password")
                   if not config.get(k)]
        if missing:
            print(f"[ERROR] Missing credentials in config.json: {missing}")
            print("        See SETUP.md for instructions.")
            sys.exit(1)

    today_str = datetime.now().strftime("%B %d, %Y")  # e.g. "March 22, 2026"
    today_short = datetime.now().strftime("%a %b %d")  # e.g. "Sat Mar 22"

    # ── Fetch jobs ────────────────────────────────────────────────────────────
    if mode == "--test":
        print("[TEST MODE] Using sample job data — no API call made.")
        raw_jobs = _sample_jobs()
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching jobs from JSearch API...")
        raw_jobs = fetch_jobs(config["rapidapi_key"])
        print(f"  → {len(raw_jobs)} raw jobs fetched")

    # ── Filter & score ────────────────────────────────────────────────────────
    scored = []
    for job in raw_jobs:
        if not is_portland_or_remote(job):
            continue
        score, reasons = score_job(job)
        if score >= 30:  # minimum threshold to appear
            scored.append((score, job, reasons))

    # Sort by score descending, cap at 30 jobs to keep email digestible
    scored.sort(key=lambda x: -x[0])
    scored = scored[:30]

    print(f"  → {len(scored)} jobs passed scoring threshold")

    # ── Build email ───────────────────────────────────────────────────────────
    html = build_email_html(scored, today_str)
    subject = f"🔍 Job Scout: {len(scored)} Senior PM Role{'s' if len(scored) != 1 else ''} · {today_short}"

    # ── Output ────────────────────────────────────────────────────────────────
    if mode == "--preview":
        # Print job summaries to console
        print(f"\n{'='*60}")
        print(f"  Job Scout Preview — {today_str}")
        print(f"  {len(scored)} roles matched")
        print(f"{'='*60}\n")
        for score, job, reasons in scored:
            print(f"[{score:>3}%] {job.get('job_title','')} @ {job.get('employer_name','')}")
            loc = "Remote" if job.get("job_is_remote") else f"{job.get('job_city','')}, {job.get('job_state','')}"
            print(f"       {loc} · {job.get('job_publisher','')}")
            for label, val in reasons[:2]:
                print(f"       {label}: {val}")
            print()
        return

    if mode == "--test":
        # Save HTML preview to disk for inspection
        preview_path = SCRIPT_DIR / "email_preview.html"
        with open(preview_path, "w") as f:
            f.write(html)
        print(f"[TEST] Email preview saved → {preview_path}")
        print(f"[TEST] Subject would be: {subject}")
        # Still attempt to send if credentials exist
        if config.get("gmail_app_password"):
            print("[TEST] Credentials found — sending test email...")
            send_email(config, f"[TEST] {subject}", html)
            print(f"[TEST] Email sent to {config['recipient_email']}")
        return

    # Normal run — send email
    print(f"  → Sending email to {config['recipient_email']}...")
    send_email(config, subject, html)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Email sent: {subject}")


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE DATA (for --test mode when no API key yet)
# ─────────────────────────────────────────────────────────────────────────────

def _sample_jobs() -> list[dict]:
    return [
        {
            "job_id": "sample1",
            "job_title": "Senior Technical Product Manager – AdTech Platform",
            "employer_name": "Roku Inc.",
            "job_city": "San Jose",
            "job_state": "CA",
            "job_is_remote": True,
            "job_publisher": "LinkedIn",
            "job_apply_link": "https://www.linkedin.com",
            "job_description": (
                "We're looking for a Senior Technical Product Manager to lead our CTV/OTT ad serving "
                "platform. You'll own the product roadmap for our SSP and DSP integrations, drive "
                "programmatic advertising strategy, and work closely with engineering on our SSAI pipeline. "
                "7+ years PM experience, strong technical background in API and microservices architecture, "
                "experience with RTB and ad measurement required. Remote US."
            ),
            "job_posted_at_timestamp": int(datetime.now().timestamp()) - 86400,
            "employer_logo": "",
        },
        {
            "job_id": "sample2",
            "job_title": "Senior Product Manager – Streaming Monetization",
            "employer_name": "Hulu",
            "job_city": "Portland",
            "job_state": "OR",
            "job_is_remote": False,
            "job_publisher": "Indeed",
            "job_apply_link": "https://www.indeed.com",
            "job_description": (
                "Hulu is hiring a Senior Product Manager to join our Ads Monetization team. "
                "You'll define the strategy for ad inventory management, direct IO campaigns, "
                "and publisher monetization tools. Strong background in CTV advertising, "
                "stakeholder management, and cross-functional leadership required. "
                "Agile/Scrum experience preferred. Portland, OR."
            ),
            "job_posted_at_timestamp": int(datetime.now().timestamp()) - 3600,
            "employer_logo": "",
        },
        {
            "job_id": "sample3",
            "job_title": "Senior Product Manager, Platform",
            "employer_name": "Acme Tech",
            "job_city": "Portland",
            "job_state": "OR",
            "job_is_remote": True,
            "job_publisher": "Glassdoor",
            "job_apply_link": "https://www.glassdoor.com",
            "job_description": (
                "We are looking for a Senior Product Manager for our platform team. "
                "You'll work on API integrations, analytics dashboards, and measurement tools. "
                "Experience with data-driven product strategy and cross-functional leadership needed. "
                "Remote-friendly. AWS experience a plus."
            ),
            "job_posted_at_timestamp": int(datetime.now().timestamp()) - 172800,
            "employer_logo": "",
        },
    ]


if __name__ == "__main__":
    main()
