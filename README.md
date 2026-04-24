
# JobScout

JobScout is an automated job discovery and resume tailoring system that fetches relevant jobs, scores them intelligently, and generates AI-tailored resumes.
## Tech Stack

**Core Language:**
- Python 3.8+

**Primary Dependencies:**
- **requests** ≥2.31.0 — HTTP client for API calls
- **anthropic** ≥0.25.0 — Claude AI API for intelligent resume tailoring
- **python-docx** ≥1.1.0 — Word document generation (.docx files)
- **pytest** — Testing framework

**External APIs & Services:**
- **JSearch API** (via RapidAPI) — Job aggregation from LinkedIn, Indeed, Glassdoor, ZipRecruiter
- **Claude AI API** (Anthropic) — LLM-powered resume tailoring and job-profile matching
- **Gmail SMTP** — Email delivery for job alerts and tailored resumes

**Architecture & Key Features:**
- Two-script pipeline architecture:
  - **job_scout.py** — Daily job fetcher with semantic scoring engine
  - **resume_tailor.py** — AI-powered resume customization with .docx generation
- HTML email templating with responsive design
- Config-based credential management (environment variables + config.json)
- Intelligent job filtering with keyword-based profile matching
- Resume tailoring using Claude with semantic job-to-profile alignment

**Development & Testing:**
- pytest for unit and integration tests
- Python standard library: json, re, smtplib, datetime, pathlib
