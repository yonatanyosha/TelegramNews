"""
SQLite persistence layer.
Tracks sent articles, topic weights, feedback, and interactive state.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "news.db"

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    """Return a database connection with row_factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sent_articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT    NOT NULL UNIQUE,
                headline    TEXT    NOT NULL,
                topic       TEXT    NOT NULL,
                source      TEXT    NOT NULL,
                sent_at     TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topic_weights (
                topic       TEXT PRIMARY KEY,
                weight      REAL NOT NULL DEFAULT 1.0
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT    NOT NULL,
                action      TEXT    NOT NULL,   -- 'like' or 'dislike'
                comment     TEXT,               -- optional user explanation
                created_at  TEXT    NOT NULL
            );

            -- Article details stored for the "elaborate" follow-up feature
            CREATE TABLE IF NOT EXISTS article_details (
                url_hash    TEXT    PRIMARY KEY,
                topic       TEXT    NOT NULL,
                title       TEXT    NOT NULL,
                summary_he  TEXT    NOT NULL,
                url         TEXT    NOT NULL,
                stored_at   TEXT    NOT NULL
            );

            -- Pending interactions: elaborate Q&A or feedback explanation
            -- Keyed by the Telegram message_id of the bot's ForceReply prompt
            CREATE TABLE IF NOT EXISTS pending_interactions (
                trigger_msg_id  INTEGER PRIMARY KEY,
                interaction_type TEXT   NOT NULL,  -- 'elaborate' or 'feedback'
                topic           TEXT,
                url_hash        TEXT,
                created_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_articles(sent_at);
            CREATE INDEX IF NOT EXISTS idx_stored_at ON article_details(stored_at);
        """)
    logger.info("Database initialised at %s", DB_PATH)


# ── Sent articles ─────────────────────────────────────────────────────────────

def is_url_sent(url: str, days: int = 7) -> bool:
    """Return True if this URL was already sent within the last `days` days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_articles WHERE url = ? AND sent_at > ?",
            (url, cutoff),
        ).fetchone()
    return row is not None


def mark_sent(url: str, headline: str, topic: str, source: str):
    """Record that an article was sent."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO sent_articles (url, headline, topic, source, sent_at) VALUES (?,?,?,?,?)",
                (url, headline, topic, source, datetime.utcnow().isoformat()),
            )
        except sqlite3.Error as e:
            logger.error("DB mark_sent error: %s", e)


def get_recent_sent_headlines(hours: int = 48) -> list[str]:
    """Return headlines sent in the last `hours` hours — used for fuzzy dedup."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT headline FROM sent_articles WHERE sent_at > ?",
            (cutoff,),
        ).fetchall()
    return [r["headline"] for r in rows]


# ── Topic weights ─────────────────────────────────────────────────────────────

def get_topic_weight(topic: str) -> float:
    """Return the current weight for a topic (default 1.0)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT weight FROM topic_weights WHERE topic = ?", (topic,)
        ).fetchone()
    return row["weight"] if row else 1.0


def set_topic_weight(topic: str, weight: float):
    """Upsert a topic weight (nudged by feedback buttons)."""
    weight = max(0.1, min(5.0, weight))  # clamp to [0.1, 5.0]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO topic_weights (topic, weight) VALUES (?,?) "
            "ON CONFLICT(topic) DO UPDATE SET weight=excluded.weight",
            (topic, weight),
        )


# ── Feedback ──────────────────────────────────────────────────────────────────

def record_feedback(topic: str, action: str, comment: str = None):
    """Record a 👍/👎 feedback click, optionally with a text explanation."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feedback (topic, action, comment, created_at) VALUES (?,?,?,?)",
            (topic, action, comment, datetime.utcnow().isoformat()),
        )


# ── Article details (for elaborate Q&A) ───────────────────────────────────────

def save_article_details(url_hash: str, topic: str, title: str, summary_he: str, url: str):
    """Store an article's Hebrew summary so the elaborate feature can retrieve it."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO article_details "
            "(url_hash, topic, title, summary_he, url, stored_at) VALUES (?,?,?,?,?,?)",
            (url_hash, topic, title, summary_he, url, datetime.utcnow().isoformat()),
        )


def get_article_details(url_hash: str) -> dict | None:
    """Retrieve stored article details by URL hash."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM article_details WHERE url_hash = ?", (url_hash,)
        ).fetchone()
    return dict(row) if row else None


def cleanup_old_article_details(days: int = 7):
    """Remove article details older than `days` days to keep DB small."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM article_details WHERE stored_at < ?", (cutoff,))


# ── Pending interactions (elaborate + feedback explanation) ───────────────────

def save_pending_interaction(
    trigger_msg_id: int,
    interaction_type: str,
    topic: str = None,
    url_hash: str = None,
):
    """
    Store a pending interaction keyed by the Telegram message_id
    of the bot's ForceReply prompt.
    """
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_interactions "
            "(trigger_msg_id, interaction_type, topic, url_hash, created_at) "
            "VALUES (?,?,?,?,?)",
            (trigger_msg_id, interaction_type, topic, url_hash, datetime.utcnow().isoformat()),
        )


def get_pending_interaction(trigger_msg_id: int) -> dict | None:
    """Get a pending interaction by the trigger message ID."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pending_interactions WHERE trigger_msg_id = ?",
            (trigger_msg_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_pending_interaction(trigger_msg_id: int):
    """Remove a processed pending interaction."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM pending_interactions WHERE trigger_msg_id = ?",
            (trigger_msg_id,),
        )


# ── Bot state (update_id tracking) ───────────────────────────────────────────

def get_last_update_id() -> int:
    """Return the last processed Telegram update_id (for callback polling)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key = 'last_update_id'"
        ).fetchone()
    return int(row["value"]) if row else 0


def set_last_update_id(update_id: int):
    """Store the last processed Telegram update_id."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bot_state (key, value) VALUES ('last_update_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(update_id),),
        )
