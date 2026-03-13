# AGENTS.md

## Project goal

A low-resource Telegram bot for downloading Instagram media and polling subscribed accounts for new media on an Oracle E2 Micro VM.

## Constraints

- Low RAM / low CPU / low disk
- No Selenium / Playwright / browsers
- No heavy infra
- Keep downloader backends isolated behind adapters
- Delete temp files after successful send
- SQLite only unless explicitly changed

## Preferred stack

- Python 3.11+
- aiogram 3.x
- Instaloader primary
- gallery-dl and yt-dlp fallback
- APScheduler
- systemd deployment

## Commands

- Install: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run: `python -m app.main`
- Test: `pytest -q`

## Done means

- `/tg <url>` works through adapter routing
- subscriptions persist and poll every 5–10 minutes
- dedupe prevents resends
- files are deleted after send
- README, env example, and systemd service exist
