# YoshaNewsBot 📰

Telegram bot that fetches global news every hour, summarizes it in **Hebrew** using Gemini AI, detects political bias, cross-matches left/right sources, and avoids sending articles you've already seen in your Telegram groups.

## Quick Start

```cmd
cd C:\Users\user2\yoshanews-bot

REM First time only — authenticate Telethon to read your groups (dedup):
python setup_telethon.py

REM Test one cycle (sends articles once and exits):
python main.py --once

REM Run continuously (every 60 min, 07:00–23:00):
python main.py
```

## Project Structure

| File | Purpose |
|---|---|
| `main.py` | Scheduler — runs the full pipeline every 60 min |
| `config.py` | Topics, sources, rate limits — **edit this to tune the bot** |
| `fetcher.py` | Pulls articles from RSS feeds |
| `processor.py` | Sends articles to Gemini for Hebrew summary + bias detection |
| `deduplicator.py` | Filters already-seen articles + left/right cross-matching |
| `reader.py` | Reads your Telegram groups via Telethon (group dedup) |
| `sender.py` | Formats and sends messages via Telegram Bot API |
| `database.py` | SQLite: tracks sent articles, topic weights |
| `setup_telethon.py` | **Run once** to authenticate Telethon with your account |
| `.env` | All credentials (never commit this) |
| `logs/bot.log` | Full activity log |
| `news.db` | SQLite database |

## Message Format

**Single source:**
```
🌍 גיאופוליטיקה  |  ⬅️ שמאלני  |  😟 שלילי

Article title in Hebrew

📝 3-sentence Hebrew summary

⚠️ הטיה: [bias explanation]

📰 BBC  •  קרא עוד
```

**Cross-matched (left + right source on same story):**
```
🌍 גיאופוליטיקה  |  ⚖️ שני צדדים  |  😟 שלילי

Story title in Hebrew

⬅️ BBC: [left perspective — 2 sentences]

➡️ Fox News: [right perspective — 2 sentences]

🤝 מסקנה משותפת: [what both agree on]

📰 BBC  •  Fox News
```

## Configuration (config.py)

**Rate limits:**
```python
RATE_LIMITS = {
    "max_per_run": 20,       # Total articles per hour
    "max_per_topic": 5,      # Per topic per hour
    "min_positive_per_run": 2,  # Guaranteed positive articles
    "dedup_window_days": 7,  # Don't repeat articles for 7 days
}
```

**Active hours:**
```python
SCHEDULE = {
    "interval_minutes": 60,
    "active_hour_start": 7,   # Start at 07:00
    "active_hour_end": 23,    # Stop at 23:00
}
```

**To add/remove a topic source** — edit the `TOPICS` dict in `config.py`.

## Setting Up Telethon (Group Dedup)

Run this once to log into your Telegram account (separate from the bot):

```cmd
python setup_telethon.py
```

You'll be asked for a verification code sent to your phone. After that, a `yoshanews_reader.session` file is saved and the bot uses it automatically.

## Gemini Free Tier

Using `gemini-flash-lite-latest` (= gemini-3.1-flash-lite) — **free, 15 req/min**.

With 20 articles per hour and a 5-second inter-request delay, the bot uses ~20 API calls per run, well within the 1,500/day free limit.

## Running as a Background Service (Windows)

To keep the bot running when you close the CMD window:

```cmd
REM Start bot in background and log to file:
start /B pythonw main.py > logs\bot.log 2>&1
```

Or use Task Scheduler to start `python main.py` at login.

## Credentials (stored in .env)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHANNEL_ID` | `-1003993965433` (verified) |
| `TELEGRAM_API_ID` | From my.telegram.org |
| `TELEGRAM_API_HASH` | From my.telegram.org |
| `TELEGRAM_PHONE` | Your phone in +972... format |
| `GEMINI_API_KEY` | From aistudio.google.com |
