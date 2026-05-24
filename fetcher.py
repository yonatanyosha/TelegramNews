"""
RSS fetcher — pulls articles from all configured sources in parallel.
Uses requests+certifi for HTTPS (fixes Windows SSL certificate issues),
then passes the raw bytes to feedparser so it never has to open a socket.
"""

import logging
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import certifi
import feedparser
import requests
from config import GEMINI_MAX_INPUT_CHARS, TOPICS

logger = logging.getLogger(__name__)

# Single requests Session reused across threads (connection pooling)
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "YoshaNewsBot/1.0 (RSS reader)"
_SESSION.verify = certifi.where()   # fixes Windows SSL cert-store issues (e.g. Al Jazeera)

_FETCH_WORKERS = 10   # concurrent RSS fetches
_FETCH_TIMEOUT = 12   # seconds per HTTP request


def _parse_date(entry) -> str:
    """Extract a publish date from an RSS entry, fallback to now."""
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def _clean_text(text: str) -> str:
    """Strip HTML tags and trim whitespace from RSS descriptions."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)      # remove HTML tags
    text = re.sub(r"&[a-z]+;", " ", text)      # remove HTML entities
    text = re.sub(r"\s+", " ", text).strip()
    return text[:GEMINI_MAX_INPUT_CHARS]


def fetch_source(source: dict, topic_key: str) -> list[dict]:
    """
    Fetch one RSS source.
    Downloads with requests (certifi SSL), parses with feedparser.
    Returns a list of article dicts.
    """
    articles = []
    try:
        resp = _SESSION.get(source["url"], timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        if feed.bozo and not feed.entries:
            logger.warning("Bad RSS feed from %s: %s", source["name"], feed.bozo_exception)
            return []

        for entry in feed.entries[:30]:   # cap at 30 entries per feed
            url   = entry.get("link", "").strip()
            title = _clean_text(entry.get("title", ""))
            summary = _clean_text(
                entry.get("summary", "")
                or entry.get("description", "")
                or entry.get("content", [{}])[0].get("value", "")
            )
            if not url or not title:
                continue

            articles.append({
                "title":             title,
                "summary":           summary,
                "url":               url,
                "published":         _parse_date(entry),
                "source_name":       source["name"],
                "source_bias":       source["bias"],
                "source_bias_score": source.get("bias_score", 0),
                "topic":             topic_key,
            })

    except requests.RequestException as e:
        logger.warning("Fetch failed for %s: %s", source["name"], e)
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", source["name"], e)

    return articles


def fetch_all() -> dict[str, list[dict]]:
    """
    Fetch ALL sources for ALL topics in parallel.
    Each topic's sources run concurrently; results are collected per topic.
    Returns: {topic_key: [article, ...]}
    """
    result: dict[str, list[dict]] = {}

    for topic_key, topic_cfg in TOPICS.items():
        sources = topic_cfg["sources"]
        topic_articles: list[dict] = []

        # Submit all sources for this topic concurrently
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as executor:
            futures = {
                executor.submit(fetch_source, src, topic_key): src
                for src in sources
            }
            for future in as_completed(futures):
                try:
                    topic_articles.extend(future.result())
                except Exception as e:
                    src = futures[future]
                    logger.error("Future error for %s: %s", src["name"], e)

        logger.info("Fetched %d articles for topic '%s'", len(topic_articles), topic_key)
        result[topic_key] = topic_articles

    return result
