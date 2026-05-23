"""
YoshaNewsBot — main entry point.

Usage:
  python main.py          Run continuously (every 60 min)
  python main.py --once   Run one cycle and exit (good for testing)
"""

import asyncio
import logging
import sys
from datetime import datetime
from rapidfuzz import fuzz

import database
import deduplicator
import fetcher
import processor
import reader
import sender
from config import RATE_LIMITS, SCHEDULE, TOPICS

# ── Logging setup ─────────────────────────────────────────────────────────────
import pathlib
pathlib.Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")


# ── Active hours guard ────────────────────────────────────────────────────────

def _is_active_hour() -> bool:
    hour = datetime.now().hour
    return SCHEDULE["active_hour_start"] <= hour < SCHEDULE["active_hour_end"]


# ── Article priority sort ─────────────────────────────────────────────────────

def _priority(result: dict) -> tuple:
    """Sort key: cross-matches first, then by global significance (desc), then topic priority."""
    is_cross = 0 if result.get("is_cross") else 1
    significance = -result.get("global_significance", 5)   # negate: higher = better
    topic_priority = TOPICS.get(result.get("topic", ""), {}).get("priority", 99)
    return (is_cross, significance, topic_priority)


# ── Cross-cycle dedup ─────────────────────────────────────────────────────────

def _dedup_within_cycle(results: list[dict]) -> list[dict]:
    """Remove near-duplicate articles that slipped through per-topic dedup."""
    threshold = RATE_LIMITS["headline_sim_threshold"]
    seen_titles: list[str] = []
    final: list[dict] = []
    for r in results:
        title = r.get("story_title") or r.get("title", "")
        is_dup = any(
            fuzz.token_sort_ratio(title.lower(), seen.lower()) >= threshold
            for seen in seen_titles
        )
        if not is_dup:
            final.append(r)
            seen_titles.append(title)
        else:
            logger.debug("SKIP (cycle dedup): %s", title[:60])
    if len(final) < len(results):
        logger.info("Cycle dedup: removed %d cross-topic duplicates", len(results) - len(final))
    return final


# ── Main news cycle ───────────────────────────────────────────────────────────

async def run_cycle():
    """One full fetch → process → send cycle."""
    logger.info("=== Starting news cycle ===")

    seen_in_groups = await reader.get_seen_urls_from_groups(hours=48)
    all_by_topic   = fetcher.fetch_all()

    results: list[dict] = []
    topic_counts: dict[str, int] = {}

    for topic_key, articles in all_by_topic.items():
        topic_cfg = TOPICS.get(topic_key, {})
        # Per-topic quota from config (replaces the old global max_per_topic)
        cap = topic_cfg.get("max_articles", 5)

        new_articles = deduplicator.filter_new(articles, seen_in_groups)
        if not new_articles:
            continue

        pairs, singles = deduplicator.cross_match(new_articles)

        # Apply cap BEFORE Gemini to save quota (each pair = 2 slots)
        pair_slots = cap // 2
        pairs   = pairs[:pair_slots]
        singles = singles[:cap - len(pairs) * 2]

        topic_results: list[dict] = []

        for pair in pairs:
            result = processor.process_cross_match(pair)
            if result:
                topic_results.append(result)

        for article in singles:
            result = processor.process_single(article)
            if result:
                # Filter articles with low global significance (US-centric local news)
                if result.get("global_significance", 5) < RATE_LIMITS.get("min_significance_score", 4):
                    logger.info(
                        "SKIP (low significance %d): %s",
                        result["global_significance"], article["title"][:60],
                    )
                    continue
                topic_results.append(result)

        topic_counts[topic_key] = len(topic_results)
        results.extend(topic_results)

    if not results:
        logger.info("No new articles this cycle.")
        return

    # Cross-topic dedup (same story appearing in multiple topic buckets)
    results = _dedup_within_cycle(results)

    # Sort by quality (cross-matches first, then global significance)
    results.sort(key=_priority)

    # Enforce global cap
    final = results[:RATE_LIMITS["max_per_run"]]

    # Send each article, store details for elaborate feature
    sent_count = 0
    for result in final:
        msg_id = sender.send_article(result)
        if msg_id:
            sent_count += 1

            # Store article details so "elaborate" button can retrieve context later
            if result.get("is_cross"):
                uhash = sender.url_hash(result["left_url"])
                database.save_article_details(
                    uhash,
                    result["topic"],
                    result["story_title"],
                    result.get("left_summary", "") + "\n" + result.get("right_summary", ""),
                    result["left_url"],
                )
                database.mark_sent(result["left_url"],  result["story_title"], result["topic"], result["left_source"])
                database.mark_sent(result["right_url"], result["story_title"], result["topic"], result["right_source"])
            else:
                uhash = sender.url_hash(result["url"])
                database.save_article_details(
                    uhash,
                    result["topic"],
                    result["title"],
                    result.get("summary_he", ""),
                    result["url"],
                )
                database.mark_sent(result["url"], result["title"], result["topic"], result["source_name"])

    logger.info(
        "=== Cycle complete: %d sent | topics: %s ===",
        sent_count,
        ", ".join(f"{k}:{v}" for k, v in topic_counts.items()),
    )


# ── Feedback callback polling ─────────────────────────────────────────────────

async def poll_callbacks():
    """
    Background task: handle button clicks and user replies every 30 seconds.

    Handles:
    - 👍 like:      record feedback, nudge topic weight up
    - 👎 dislike:   record feedback, nudge weight down, ask WHY via ForceReply
    - 🔍 elaborate: look up article details, ask for user's question via ForceReply
    - Reply:        answer the user's question (elaborate) or save explanation (dislike)
    """
    while True:
        await asyncio.sleep(30)
        try:
            last_id = database.get_last_update_id()
            updates = sender.get_updates(offset=last_id + 1 if last_id else 0)

            for upd in updates:
                upd_id = upd.get("update_id", 0)
                database.set_last_update_id(upd_id)

                cb  = upd.get("callback_query")
                msg = upd.get("message")

                if cb:
                    await _handle_callback(cb)
                elif msg and msg.get("reply_to_message"):
                    await _handle_reply(msg)

        except Exception as e:
            logger.error("poll_callbacks error: %s", e)


async def _handle_callback(cb: dict):
    """Process a button click from the inline keyboard."""
    data  = cb.get("data", "")
    cb_id = cb.get("id", "")
    parts = data.split(":")

    action = parts[0] if parts else ""

    if action == "like" and len(parts) >= 2:
        topic = parts[1]
        database.record_feedback(topic, "like")
        current = database.get_topic_weight(topic)
        database.set_topic_weight(topic, current + 0.2)
        logger.info("👍 Feedback: like on topic '%s'", topic)
        sender.answer_callback(cb_id, "תודה! 👍")

    elif action == "dislike" and len(parts) >= 3:
        topic    = parts[1]
        uhash    = parts[2]
        database.record_feedback(topic, "dislike")
        # Small weight reduction — only significant after repeated dislikes
        current = database.get_topic_weight(topic)
        database.set_topic_weight(topic, current - 0.1)
        # Ask WHY — don't just reduce weight blindly, get specific feedback
        msg_id = sender.send_message(
            "👎 <b>מה לא אהבת בכתבה הזו?</b>\n\n"
            "תאר בקצרה: נושא, זווית, סגנון, אורך... "
            "הפירוט יעזור לשפר את הסינון בדיוק לפי הטעם שלך.",
            reply_markup={"force_reply": True, "selective": False},
        )
        if msg_id:
            database.save_pending_interaction(msg_id, "feedback", topic=topic)
        logger.info("👎 Feedback: dislike on topic '%s'", topic)
        sender.answer_callback(cb_id, "תודה! ספר לי למה 👇")

    elif action == "elaborate" and len(parts) >= 2:
        uhash   = parts[1]
        details = database.get_article_details(uhash)
        if details:
            title = details["title"]
            msg_id = sender.send_message(
                f"🔍 <b>{sender._html_escape(title)}</b>\n\n"
                "שאל אותי כל שאלה על הכתבה הזו:\n"
                "• מה קרה לפני?\n• מדוע זה קרה?\n• מה ההשלכות?\n• רקע כללי?",
                reply_markup={"force_reply": True, "selective": False},
            )
            if msg_id:
                database.save_pending_interaction(msg_id, "elaborate", url_hash=uhash)
            sender.answer_callback(cb_id, "כתוב לי את שאלתך 🔍")
        else:
            sender.answer_callback(cb_id, "הכתבה לא נמצאה — נסה שוב מאוחר יותר")

    else:
        sender.answer_callback(cb_id)


async def _handle_reply(msg: dict):
    """Process a user's reply to one of the bot's ForceReply prompts."""
    reply_to_id = msg["reply_to_message"]["message_id"]
    interaction = database.get_pending_interaction(reply_to_id)
    if not interaction:
        return

    user_text = msg.get("text", "").strip()
    if not user_text:
        return

    itype = interaction["interaction_type"]

    if itype == "feedback":
        # Save the user's explanation alongside the feedback record
        topic = interaction.get("topic", "unknown")
        database.record_feedback(topic, "dislike_comment", comment=user_text)
        sender.send_message(
            "תודה על הפירוט! 🙏 נשתמש בזה כדי לשפר את הסינון.",
        )
        logger.info("Feedback comment saved for topic '%s': %s", topic, user_text[:80])

    elif itype == "elaborate":
        uhash   = interaction.get("url_hash", "")
        details = database.get_article_details(uhash) if uhash else None
        if details:
            answer = processor.answer_question(
                details["title"],
                details["summary_he"],
                user_text,
            )
            if answer:
                sender.send_message(
                    f"🔍 <b>תשובה:</b>\n\n{sender._html_escape(answer)}",
                    reply_to_message_id=msg["message_id"],
                )
            else:
                sender.send_message("מצטער, לא הצלחתי לענות כרגע — נסה שוב 🙏")
        else:
            sender.send_message("פרטי הכתבה לא נמצאו — ייתכן שעברו יותר מ-7 ימים.")

    database.delete_pending_interaction(reply_to_id)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    database.init_db()
    database.cleanup_old_article_details(days=7)

    run_once = "--once" in sys.argv

    if run_once:
        logger.info("Running in --once mode")
        await run_cycle()
        return

    interval = SCHEDULE["interval_minutes"] * 60
    logger.info(
        "YoshaNewsBot started — running every %d minutes (active %02d:00–%02d:00)",
        SCHEDULE["interval_minutes"],
        SCHEDULE["active_hour_start"],
        SCHEDULE["active_hour_end"],
    )

    # Run news cycle + feedback polling concurrently
    await asyncio.gather(
        _cycle_loop(interval),
        poll_callbacks(),
    )


async def _cycle_loop(interval: int):
    """Infinite loop running a news cycle every `interval` seconds."""
    while True:
        if _is_active_hour():
            await run_cycle()
        else:
            logger.info("Outside active hours — sleeping.")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
