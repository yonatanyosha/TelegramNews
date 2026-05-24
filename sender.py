"""
Telegram message formatter and sender.
Uses the Bot API directly via requests (no extra library needed).
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
from config import TOPICS, RATE_LIMITS

load_dotenv()

logger = logging.getLogger(__name__)

_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
_API_BASE   = f"https://api.telegram.org/bot{_BOT_TOKEN}"


# ── Bias visual scale (based on known source bias from config) ────────────────

_BIAS_LABELS = {
    -3: "🔴 ◀◀◀ שמאל קיצוני",
    -2: "🟠 ◀◀ שמאלני",
    -1: "🟡 ◀ מרכז-שמאל",
     0: "🟢 ⚖ ניטרלי",
     1: "🟡 ▶ מרכז-ימין",
     2: "🟠 ▶▶ ימני",
     3: "🔴 ▶▶▶ ימין קיצוני",
}


def _bias_display(bias_score: int) -> str:
    """Convert numeric bias score (-3..+3) to a readable Hebrew label with color."""
    clamped = max(-3, min(3, int(bias_score or 0)))
    return _BIAS_LABELS.get(clamped, "🟢 ⚖ ניטרלי")


# ── Country flag emojis ───────────────────────────────────────────────────────

def _country_flags(countries: list) -> str:
    """Convert ISO 3166-1 alpha-2 codes to flag emojis. Returns 🌐 if empty."""
    if not countries:
        return "🌐"
    flags = []
    for code in countries[:4]:
        code = str(code).upper()
        if len(code) == 2 and code.isalpha():
            flag = (
                chr(0x1F1E6 + ord(code[0]) - ord("A"))
                + chr(0x1F1E6 + ord(code[1]) - ord("A"))
            )
            flags.append(flag)
    return "".join(flags) if flags else "🌐"


# ── Publication date ──────────────────────────────────────────────────────────

def _format_date(published: str) -> str:
    """Convert ISO datetime string to a human-readable Hebrew relative time."""
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            return "זה עתה"
        if minutes < 60:
            return f"לפני {minutes} דקות"
        hours = minutes // 60
        if hours < 24:
            return f"לפני {hours} שעות"
        days = hours // 24
        if days < 7:
            return f"לפני {days} ימים"
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return ""


# ── Article URL hash (used in callback data and DB lookup) ────────────────────

def url_hash(url: str) -> str:
    """Return a 16-char MD5 hash of the URL — unique ID for article lookups."""
    return hashlib.md5(url.encode()).hexdigest()[:16]


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _html_escape(text: str) -> str:
    """Escape characters that break Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _topic_header(topic_key: str) -> str:
    cfg = TOPICS.get(topic_key, {})
    return f"{cfg.get('emoji', '')} {cfg.get('name', topic_key)}"


# ── Inline keyboards ──────────────────────────────────────────────────────────

def _feedback_keyboard(topic: str, article_url_hash: str) -> dict:
    """Three-button keyboard: like, dislike (with explanation), elaborate."""
    return {
        "inline_keyboard": [[
            {"text": "👍 מעולה",      "callback_data": f"like:{topic}"},
            {"text": "👎 פחות מזה",   "callback_data": f"dislike:{topic}:{article_url_hash}"},
            {"text": "🔍 פרט יותר",   "callback_data": f"elaborate:{article_url_hash}"},
        ]]
    }


# ── Formatters ────────────────────────────────────────────────────────────────

def format_single(article: dict) -> str:
    """Format a single processed article into Telegram HTML."""
    topic_hdr    = _topic_header(article["topic"])
    # Use source's known political bias score (more reliable than per-article Gemini detection)
    bias_label   = _bias_display(article.get("source_bias_score", 0))
    flags        = _country_flags(article.get("countries") or [])
    date_str     = _format_date(article.get("published", ""))
    positive_hdr = "🌟 <b>חדשות טובות!</b>\n\n" if article.get("is_positive") else ""
    bias_note    = article.get("bias_note")
    bias_line    = f"\n⚠️ <i>הטיה: {_html_escape(bias_note)}</i>" if bias_note else ""

    title     = _html_escape(article.get("title", ""))
    summary   = _html_escape(article.get("summary_he", ""))
    url       = article.get("url", "").replace("&", "&amp;")  # escape & in href
    source    = _html_escape(article.get("source_name", ""))
    date_line = f"🕐 {date_str}\n" if date_str else ""         # own line, before source

    return (
        f"{positive_hdr}"
        f"<b>{topic_hdr}</b>  |  {bias_label}  |  {flags}\n\n"
        f"<b>{title}</b>\n\n"
        f"📝 {summary}"
        f"{bias_line}\n\n"
        f"{date_line}📰 {source}  •  <a href=\"{url}\">קרא עוד</a>"
    )


def format_cross(result: dict) -> str:
    """Format a cross-matched pair into Telegram HTML."""
    topic_hdr    = _topic_header(result["topic"])
    flags        = _country_flags(result.get("countries") or [])
    date_str     = _format_date(result.get("published", ""))
    positive_hdr = "🌟 <b>חדשות טובות!</b>\n\n" if result.get("is_positive") else ""

    story_title = _html_escape(result.get("story_title", ""))
    left_src    = _html_escape(result.get("left_source", ""))
    right_src   = _html_escape(result.get("right_source", ""))
    left_sum    = _html_escape(result.get("left_summary", ""))
    right_sum   = _html_escape(result.get("right_summary", ""))
    common      = _html_escape(result.get("common", ""))
    left_url    = result.get("left_url", "").replace("&", "&amp;")
    right_url   = result.get("right_url", "").replace("&", "&amp;")
    diff        = _html_escape(result.get("key_difference", ""))
    diff_line   = f"⚔️ <b>הבדל מרכזי:</b> {diff}\n" if diff else ""
    date_line   = f"🕐 {date_str}\n" if date_str else ""       # own line, before sources

    return (
        f"{positive_hdr}"
        f"<b>{topic_hdr}</b>  |  <b>⚖️ שני צדדים</b>  |  {flags}\n\n"
        f"<b>{story_title}</b>\n\n"
        f"⬅️ <b>{left_src}:</b>\n{left_sum}\n\n"
        f"➡️ <b>{right_src}:</b>\n{right_sum}\n\n"
        f"{diff_line}"
        f"🤝 <b>מסכימים על:</b> {common}\n\n"
        f"{date_line}📰 <a href=\"{left_url}\">{left_src}</a>  •  <a href=\"{right_url}\">{right_src}</a>"
    )


# ── Sending ───────────────────────────────────────────────────────────────────

def send_message(
    text: str,
    reply_markup: dict = None,
    reply_to_message_id: int = None,
) -> int | None:
    """
    Send a single HTML-formatted message to the configured Telegram channel.
    Returns the Telegram message_id on success, None on failure.
    """
    if not _BOT_TOKEN or not _CHANNEL_ID:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID not set in .env")
        return None

    payload = {
        "chat_id":                  _CHANNEL_ID,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        resp = requests.post(f"{_API_BASE}/sendMessage", json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        logger.error("Telegram API error: %s", data.get("description", "unknown"))
        if "chat not found" in str(data.get("description", "")).lower():
            logger.error("Channel not found — double-check TELEGRAM_CHANNEL_ID in .env.")
        return None
    except Exception as e:
        logger.error("sendMessage request failed: %s", e)
        return None


def send_article(result: dict) -> int | None:
    """
    Format and send one result (single or cross-matched) with a feedback + elaborate keyboard.
    Returns the Telegram message_id on success (used to store interaction state).
    """
    is_cross = result.get("is_cross")
    text     = format_cross(result) if is_cross else format_single(result)
    topic    = result.get("topic", "general")

    # Determine the URL hash to use in keyboard callbacks
    if is_cross:
        uhash = url_hash(result.get("left_url", ""))
    else:
        uhash = url_hash(result.get("url", ""))

    keyboard = _feedback_keyboard(topic, uhash)
    msg_id   = send_message(text, reply_markup=keyboard)
    if msg_id:
        logger.info("Sent: %s", result.get("story_title") or result.get("title", "")[:60])
    time.sleep(RATE_LIMITS["delay_between_messages"])
    return msg_id


# ── Callback / update helpers ─────────────────────────────────────────────────

def get_updates(offset: int = 0) -> list[dict]:
    """Fetch pending Telegram updates (for handling button clicks and replies)."""
    try:
        resp = requests.get(
            f"{_API_BASE}/getUpdates",
            params={"offset": offset, "timeout": 0, "limit": 100},
            timeout=15,
        )
        return resp.json().get("result", [])
    except Exception as e:
        logger.error("getUpdates error: %s", e)
        return []


def answer_callback(callback_query_id: str, text: str = "") -> None:
    """Acknowledge a Telegram inline keyboard button press."""
    try:
        requests.post(
            f"{_API_BASE}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logger.error("answerCallbackQuery error: %s", e)
