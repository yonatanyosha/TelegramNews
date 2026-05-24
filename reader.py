"""
Telethon reader — scans the user's existing Telegram groups to collect
URLs that were already shared there. Used by the deduplicator to avoid
sending news the user has already seen.

Caching: scan results are cached in the DB for RATE_LIMITS["telethon_cache_minutes"]
(default 60 min). Most cycles reuse the cache; a fresh scan only runs when stale.

First-time setup: run `setup_telethon.py` once to authenticate.
After that, the session is saved in `yoshanews_reader.session`.
"""

import logging
import os
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import database

load_dotenv()

logger = logging.getLogger(__name__)

SESSION_FILE = Path(__file__).parent / "yoshanews_reader"
_URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")


async def get_seen_urls_from_groups(hours: int = 48) -> set[str]:
    """
    Return a set of all URLs seen in the user's configured Telegram groups
    in the past `hours` hours.

    Returns cached result if cache is fresh (< telethon_cache_minutes old).
    Falls back to empty set if the Telethon session doesn't exist yet.
    """
    # ── Cache check ───────────────────────────────────────────────────────────
    cached = database.get_telethon_cache()
    if cached:
        logger.info(
            "Telethon cache hit — %d URLs, %.0f min old (skipping live scan)",
            len(cached["urls"]), cached["age_minutes"],
        )
        return cached["urls"]

    # ── Session guard ─────────────────────────────────────────────────────────
    if not SESSION_FILE.with_suffix(".session").exists():
        logger.warning(
            "Telethon session not found — skipping group scan. "
            "Run setup_telethon.py once to enable group dedup."
        )
        return set()

    # ── Live scan ─────────────────────────────────────────────────────────────
    try:
        from telethon import TelegramClient
        from config import WATCH_GROUPS

        api_id   = int(os.getenv("TELEGRAM_API_ID", "0"))
        api_hash = os.getenv("TELEGRAM_API_HASH", "")
        client   = TelegramClient(str(SESSION_FILE), api_id, api_hash)

        urls: set[str] = set()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Telethon session expired — re-run setup_telethon.py")
            await client.disconnect()
            return set()

        for group_username in WATCH_GROUPS:
            try:
                entity = await client.get_entity(group_username)
                async for message in client.iter_messages(entity, limit=500):
                    if message.date and message.date.replace(tzinfo=timezone.utc) < cutoff:
                        break
                    text  = message.text or ""
                    found = _URL_RE.findall(text)
                    urls.update(found)
                    # Also grab URLs from embedded link previews
                    if message.media and hasattr(message.media, "webpage"):
                        wp_url = getattr(message.media.webpage, "url", None)
                        if wp_url:
                            urls.add(wp_url)
                logger.info("Scanned %s — %d total URLs so far", group_username, len(urls))
            except Exception as e:
                logger.warning("Could not scan group %s: %s", group_username, e)

        await client.disconnect()
        logger.info("Group scan complete: %d unique URLs seen in past %dh", len(urls), hours)

        # ── Persist to cache ──────────────────────────────────────────────────
        database.set_telethon_cache(urls)
        return urls

    except ImportError:
        logger.error("telethon not installed — run: pip install telethon")
        return set()
    except Exception as e:
        logger.error("Telethon reader error: %s", e)
        return set()
