"""
RSS fetcher — pulls articles from all configured sources.
Returns a flat list of article dicts ready for dedup + processing.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional
import feedparser
from config import TOPICS, GEMINI_MAX_INPUT_CHARS

logger = logging.getLogger(__name__)


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
    text = re.sub(r"<[^>]+>", " ", text)          # remove HTML tags
    text = re.sub(r"&[a-z]+;", " ", text)          # remove HTML entities
    text = re.sub(r"\s+", " ", text).strip()
    return text[:GEMINI_MAX_INPUT_CHARS]


def fetch_source(source: dict, topic_key: str) -> list[dict]:
    """
    Fetch articles from a single RSS source.

    Returns a list of article dicts:
      {title, summary, url, published, source_name, source_bias, topic}
    """
    articles = []
    try:
        feed = feedparser.parse(source["url"])
        if feed.bozo and not feed.entries:
            logger.warning("Bad RSS feed from %s: %s", source["name"], feed.bozo_exception)
            return []

        for entry in feed.entries[:30]:  # cap at 30 entries per feed
            url = entry.get("link", "").strip()
            title = _clean_text(entry.get("title", ""))
            summary = _clean_text(
                entry.get("summary", "")
                or entry.get("description", "")
                or entry.get("content", [{}])[0].get("value", "")
            )
            if not url or not title:
                continue

            articles.append({
                "title":            title,
                "summary":          summary,
                "url":              url,
                "published":        _parse_date(entry),
                "source_name":      source["name"],
                "source_bias":      source["bias"],
                "source_bias_score": source.get("bias_score", 0),
                "topic":            topic_key,
            })

    except Exception as e:
        logger.error("Error fetching %s (%s): %s", source["name"], source["url"], e)

    return articles


def fetch_all() -> dict[str, list[dict]]:
    """
    Fetch all sources for all topics.

    Returns: {topic_key: [article, ...]}
    """
    result: dict[str, list[dict]] = {}
    for topic_key, topic_cfg in TOPICS.items():
        topic_articles = []
        for source in topic_cfg["sources"]:
            fetched = fetch_source(source, topic_key)
            topic_articles.extend(fetched)
            time.sleep(0.3)  # polite delay between RSS requests
        logger.info("Fetched %d articles for topic '%s'", len(topic_articles), topic_key)
        result[topic_key] = topic_articles
    return result
