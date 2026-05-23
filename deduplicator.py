"""
Deduplication + left/right cross-matching.

Three dedup layers:
  1. URL exact match against sent_articles DB
  2. URL match against URLs seen in user's Telegram groups (passed in)
  3. Fuzzy headline match against recently sent headlines

Cross-matching:
  Within each topic, find pairs where the same event is covered by
  both a LEFT/CENTER source and a RIGHT source.
"""

import logging
from rapidfuzz import fuzz
import database
from config import RATE_LIMITS

logger = logging.getLogger(__name__)

_CROSS_THRESHOLD = RATE_LIMITS["cross_match_threshold"]
_HEADLINE_THRESHOLD = RATE_LIMITS["headline_sim_threshold"]


# ── Deduplication ─────────────────────────────────────────────────────────────

def filter_new(
    articles: list[dict],
    group_urls: set[str],
) -> list[dict]:
    """
    Return only articles that have NOT been seen before.

    Checks:
      - DB: URL already sent this week?
      - Group scan: URL appeared in user's Telegram groups recently?
      - Fuzzy: Headline ≥ threshold similar to a recently sent headline?
    """
    recent_headlines = database.get_recent_sent_headlines(hours=48)
    new = []

    for article in articles:
        url = article["url"]
        title = article["title"]

        # Layer 1 — exact URL in DB
        if database.is_url_sent(url):
            logger.debug("SKIP (db):     %s", title[:60])
            continue

        # Layer 2 — URL seen in user's Telegram groups
        if url in group_urls:
            logger.debug("SKIP (groups): %s", title[:60])
            continue

        # Layer 3 — fuzzy headline match against recently sent
        if _is_headline_duplicate(title, recent_headlines):
            logger.debug("SKIP (fuzzy):  %s", title[:60])
            continue

        new.append(article)

    logger.info("Dedup: %d articles kept from %d total", len(new), len(articles))
    return new


def _is_headline_duplicate(title: str, recent_headlines: list[str]) -> bool:
    """Return True if title is too similar to any recently sent headline."""
    for sent in recent_headlines:
        score = fuzz.token_sort_ratio(title.lower(), sent.lower())
        if score >= _HEADLINE_THRESHOLD:
            return True
    return False


# ── Cross-matching ────────────────────────────────────────────────────────────

def cross_match(articles: list[dict]) -> tuple[list[tuple], list[dict]]:
    """
    Split a list of same-topic articles into:
      - pairs: [(left_article, right_article), ...]  — cross-matchable pairs
      - singles: [article, ...]                       — articles with no match

    Matching logic:
      - left/center article vs right article
      - headline similarity ≥ CROSS_THRESHOLD
      - each article used at most once
    """
    lefts  = [a for a in articles if a["source_bias"] in ("LEFT", "CENTER")]
    rights = [a for a in articles if a["source_bias"] == "RIGHT"]

    pairs: list[tuple] = []
    used_left: set[int] = set()
    used_right: set[int] = set()

    for li, left in enumerate(lefts):
        if li in used_left:
            continue
        for ri, right in enumerate(rights):
            if ri in used_right:
                continue
            score = fuzz.token_sort_ratio(
                left["title"].lower(), right["title"].lower()
            )
            if score >= _CROSS_THRESHOLD:
                pairs.append((left, right))
                used_left.add(li)
                used_right.add(ri)
                logger.info(
                    "CROSS-MATCH (%.0f%%): %s | %s",
                    score, left["source_name"], right["source_name"],
                )
                break

    singles = [
        a for i, a in enumerate(lefts)  if i not in used_left
    ] + [
        a for i, a in enumerate(rights) if i not in used_right
    ]

    return pairs, singles
