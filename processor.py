"""
Google Gemini AI processor.
Converts raw articles into Hebrew summaries with bias score, sentiment, and country flags.
"""

import json
import logging
import os
import re
import time
import warnings
# Suppress google-generativeai deprecation warning (library still works; migrate to google-genai later)
warnings.filterwarnings("ignore", category=FutureWarning, module="google")
import google.generativeai as genai
from dotenv import load_dotenv
from config import GEMINI_MODEL

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel(GEMINI_MODEL)

logger = logging.getLogger(__name__)

# Retry settings
_MAX_RETRIES = 2
_RETRY_DELAY = 5
_INTER_REQUEST_DELAY = 5  # seconds between calls — free tier is 15 RPM

# Hebrew phrases that indicate Gemini had no real content to summarize
_EMPTY_MARKERS = [
    "EMPTY",
    "אינה מכילה מידע",  # אינה מכילה מידע
    "אין מידע",                                         # אין מידע
    "כותרת כללית",                      # כותרת כללית
    "הידיעה ריקה",                      # הידיעה ריקה
]


def _call_gemini(prompt: str) -> str:
    """Call Gemini with retries on rate-limit errors and inter-request pacing."""
    for attempt in range(_MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(_INTER_REQUEST_DELAY)
            response = model.generate_content(prompt)
            time.sleep(_INTER_REQUEST_DELAY)  # pace every call regardless
            return response.text
        except Exception as e:
            err = str(e)
            if "429" in err:
                m = re.search(r"retry in (\d+)", err)
                wait = int(m.group(1)) + 2 if m else 20
                logger.warning("Rate limited — waiting %ds...", wait)
                time.sleep(wait)
            elif attempt < _MAX_RETRIES - 1:
                logger.warning("Gemini error (attempt %d): %s — retrying...", attempt + 1, e)
                time.sleep(_RETRY_DELAY)
            else:
                logger.error("Gemini failed after %d attempts: %s", _MAX_RETRIES, e)
                raise
    return ""


def _parse_json(raw: str) -> dict:
    """
    Extract and parse JSON from Gemini's response.
    Handles markdown code blocks and Hebrew punctuation that breaks JSON.
    """
    # Strip markdown code blocks
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    # Replace Unicode curly/smart quotes with plain single quotes (use escapes, not literal chars)
    raw = raw.replace("“", "'").replace("”", "'")  # left/right double curly quotes
    raw = raw.replace("‘", "'").replace("’", "'")  # left/right single curly quotes
    raw = raw.replace("«", "'").replace("»", "'")  # guillemets « »
    # Fix unescaped " between Hebrew letters (abbreviations like ח"כ, ב"כ)
    raw = re.sub(r'([א-ת])"([א-ת])', r"\1'\2", raw)
    # Fix unescaped " between digit and Hebrew letter (e.g., 2"ב)
    raw = re.sub(r'(\d)"([א-ת])', r"\1'\2", raw)
    raw = re.sub(r'([א-ת])"(\d)', r"\1'\2", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s\nRaw response: %s", e, raw[:300])
        return {}


def _is_empty_summary(summary: str) -> bool:
    """Return True if Gemini signalled that the article had no real content."""
    if not summary or len(summary.strip()) < 60:
        return True
    s = summary.strip()
    for marker in _EMPTY_MARKERS:
        if marker in s:
            return True
    return False


# ── Single-source processing ──────────────────────────────────────────────────

_SINGLE_PROMPT = """
אתה עוזר עיתונאי ניטרלי שמסכם ידיעות לעברית.

להלן ידיעה מהמקור "{source_name}":
כותרת: {title}
תוכן: {content}

החזר JSON בדיוק במבנה הבא (ללא הסברים נוספים):
{{
  "summary": "5-6 משפטים בעברית — תקציר עובדתי הכולל רקע חשוב, עובדות מרכזיות, והשלכות. כתוב כאילו הקורא לא מכיר את הנושא. אם אין תוכן עיתונאי מעבר לכותרת, החזר בדיוק EMPTY",
  "bias_note": "הסבר קצר בעברית (משפט אחד) אם יש הטיה בכתיבה, null אם אין",
  "sentiment": "POSITIVE or NEGATIVE or NEUTRAL",
  "is_positive": true or false,
  "countries": ["קודי ISO שתי אותיות של המדינות שהידיעה עוסקת בהן ישירות — עד 3 מדינות"],
  "global_significance": מספר שלם 1-10 (10=אירוע חסר תקדים בעל משמעות עולמית, 1=ידיעה מקומית רגילה)
}}

כללים:
- כתוב בעברית תקנית ובהירה, ללא דעה אישית
- sentiment=POSITIVE רק אם הידיעה עוסקת בהישג, שיפור, או חדשות טובות
- countries: קודים כמו "IL", "US", "IR", "UA", "RU", "CN", "IN"
- global_significance: העדף גבוה לאירועים שמשפיעים על מדינות רבות, מלחמות, אסונות טבע, פריצות דרך, משברים כלכליים
- IMPORTANT: Do not use the double-quote character inside Hebrew text — use ׳ or avoid abbreviations
""".strip()


def process_single(article: dict) -> dict | None:
    """
    Process a single article with Gemini.
    Returns the article dict enriched with AI fields, or None on failure/empty.
    """
    prompt = _SINGLE_PROMPT.format(
        source_name=article["source_name"],
        title=article["title"],
        content=article["summary"] or article["title"],
    )
    try:
        raw = _call_gemini(prompt)
        data = _parse_json(raw)
        summary = data.get("summary", "")

        if not summary or _is_empty_summary(summary):
            logger.info("Skipping empty article: %s", article["title"][:60])
            return None

        return {
            **article,
            "summary_he":         summary,
            # source_bias_score comes from config (known editorial bias) — more reliable
            # than per-article Gemini detection for the header display
            "bias_note":          data.get("bias_note"),
            "sentiment":          data.get("sentiment", "NEUTRAL"),
            "is_positive":        bool(data.get("is_positive", False)),
            "countries":          data.get("countries") or [],
            "global_significance": int(data.get("global_significance", 5)),
            "is_cross":           False,
        }
    except Exception as e:
        logger.error("process_single failed for '%s': %s", article["title"][:60], e)
        return None


# ── Cross-match processing ────────────────────────────────────────────────────

_CROSS_PROMPT = """
אתה עורך עיתון ניטרלי שמציג שני צידי הסיפור.

המקור השמאלי/מרכזי "{left_source}" מדווח:
כותרת: {left_title}
תוכן: {left_content}

המקור הימני "{right_source}" מדווח:
כותרת: {right_title}
תוכן: {right_content}

החזר JSON בדיוק במבנה הבא (ללא הסברים נוספים):
{{
  "story_title": "כותרת ניטרלית לסיפור בעברית",
  "left_summary": "3 משפטים בעברית — מה {left_source} מדגיש ולמה זה חשוב",
  "right_summary": "3 משפטים בעברית — מה {right_source} מדגיש ולמה זה חשוב",
  "common": "משפט אחד בעברית — מה שניהם מסכימים עליו",
  "sentiment": "POSITIVE or NEGATIVE or NEUTRAL",
  "is_positive": true or false,
  "countries": ["קודי ISO שתי אותיות של המדינות הקשורות לסיפור"]
}}

כתוב בעברית תקנית. אל תוסיף שיפוט אישי.
IMPORTANT: Do not use double-quote characters inside Hebrew text — use ׳ or avoid abbreviations.
""".strip()


def process_cross_match(pair: tuple[dict, dict]) -> dict | None:
    """
    Process a left/right article pair with Gemini.
    Returns an enriched cross-match result dict, or None on failure.
    """
    left, right = pair
    prompt = _CROSS_PROMPT.format(
        left_source=left["source_name"],
        left_title=left["title"],
        left_content=left["summary"] or left["title"],
        right_source=right["source_name"],
        right_title=right["title"],
        right_content=right["summary"] or right["title"],
    )
    try:
        raw = _call_gemini(prompt)
        data = _parse_json(raw)
        if not data.get("left_summary"):
            logger.warning("Empty cross-match response for: %s", left["title"][:60])
            return None

        return {
            "topic":         left["topic"],
            "is_cross":      True,
            "story_title":   data.get("story_title", left["title"]),
            "left_source":   left["source_name"],
            "right_source":  right["source_name"],
            "left_url":      left["url"],
            "right_url":     right["url"],
            "left_summary":  data.get("left_summary", ""),
            "right_summary": data.get("right_summary", ""),
            "common":        data.get("common", ""),
            "sentiment":     data.get("sentiment", "NEUTRAL"),
            "is_positive":   bool(data.get("is_positive", False)),
            "countries":     data.get("countries") or [],
            "published":     left["published"],
        }
    except Exception as e:
        logger.error("process_cross_match failed: %s", e)
        return None


# ── Elaborate Q&A ─────────────────────────────────────────────────────────────

def answer_question(article_title: str, article_summary: str, question: str) -> str:
    """
    Answer a user's follow-up question about an article using Gemini.
    Called when the user clicks the "🔍 פרט יותר" button and types a question.
    """
    prompt = f"""
כתבה שנשלחה לקורא:
כותרת: {article_title}
תקציר: {article_summary}

שאלת הקורא: {question}

ענה בעברית תקנית — 4-6 משפטים עם רקע, הסבר, ועובדות רלוונטיות.
התחל ישר עם התשובה, ללא הקדמות.
IMPORTANT: Do not use double-quote characters inside Hebrew text.
""".strip()
    try:
        return _call_gemini(prompt).strip()
    except Exception as e:
        logger.error("answer_question failed: %s", e)
        return ""
