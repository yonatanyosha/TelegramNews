"""
Central configuration for YoshaNewsBot.
Edit TOPICS, RATE_LIMITS, and SCHEDULE to tune behaviour.
"""

# ── Telegram groups to scan for dedup (articles already seen by user) ────────
WATCH_GROUPS = [
    "@asafroz",
    "@abualiexpress",
    "@Intellinews",
    "@amitsegal",
    "@salehdesk1",
    "@SuperInvestorIL",
]

# ── Topics ────────────────────────────────────────────────────────────────────
# bias_score:  -3=far left, -2=left, -1=center-left, 0=center, +1=center-right, +2=right, +3=far right
# max_articles: hard cap on how many articles this topic may contribute per run
#
# Target proportions (20 total per run):
#   Geopolitics 60% → 12  |  Israel 15% → 3  |  Finance 15% → 3  |  Other 10% → 2

TOPICS = {
    "geopolitics": {
        "name": "גיאופוליטיקה",
        "emoji": "🌍",
        "priority": 1,
        "max_articles": 12,   # 60%
        "sources": [
            # --- Center / Wire services ---
            {"name": "Reuters",           "url": "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en",              "bias": "CENTER", "bias_score": 0},
            {"name": "AP News",           "url": "https://news.google.com/rss/search?q=site:apnews.com&hl=en-US&gl=US&ceid=US:en",                    "bias": "CENTER", "bias_score": 0},
            # --- Left-leaning ---
            {"name": "BBC",               "url": "http://feeds.bbci.co.uk/news/world/rss.xml",                                                          "bias": "LEFT",   "bias_score": -1},
            {"name": "Al Jazeera",        "url": "http://www.aljazeera.com/xml/rss/all.xml",                                                            "bias": "LEFT",   "bias_score": -2},
            {"name": "The Guardian",      "url": "https://www.theguardian.com/world/rss",                                                               "bias": "LEFT",   "bias_score": -2},
            # --- Right-leaning ---
            {"name": "Fox News",          "url": "https://moxie.foxnews.com/google-publisher/world.xml",                                                "bias": "RIGHT",  "bias_score": 2},
            {"name": "Breitbart",         "url": "https://feeds.feedburner.com/breitbart",                                                              "bias": "RIGHT",  "bias_score": 3},
            # --- International / regional diversity ---
            {"name": "Deutsche Welle",    "url": "https://rss.dw.com/rdf/rss-en-all",                                                                  "bias": "CENTER", "bias_score": -1},
            {"name": "France 24",         "url": "https://www.france24.com/en/rss",                                                                    "bias": "CENTER", "bias_score": 0},
            {"name": "NHK World",         "url": "https://www3.nhk.or.jp/nhkworld/en/news/feeds/rss.xml",                                              "bias": "CENTER", "bias_score": 0},
            {"name": "Asia (Google News)","url": "https://news.google.com/rss/search?q=asia+india+china+south+korea+world+news&hl=en-US&gl=US&ceid=US:en", "bias": "CENTER", "bias_score": 0},
            {"name": "Africa (Google News)", "url": "https://news.google.com/rss/search?q=africa+breaking+world+news&hl=en-US&gl=US&ceid=US:en",        "bias": "CENTER", "bias_score": 0},
            {"name": "LatAm (Google News)","url": "https://news.google.com/rss/search?q=latin+america+south+america+world+news&hl=en-US&gl=US&ceid=US:en", "bias": "CENTER", "bias_score": 0},
            {"name": "World Breaking",    "url": "https://news.google.com/rss/search?q=unprecedented+breaking+world+crisis&hl=en-US&gl=US&ceid=US:en", "bias": "CENTER", "bias_score": 0},
        ],
    },

    "israel": {
        "name": "פוליטיקה ישראלית",
        "emoji": "🇮🇱",
        "priority": 2,
        "max_articles": 3,    # 15%
        "sources": [
            {"name": "Times of Israel",   "url": "https://www.timesofisrael.com/feed/",                                                                 "bias": "CENTER", "bias_score": 0},
            {"name": "Jerusalem Post",    "url": "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",                                                    "bias": "RIGHT",  "bias_score": 1},
            {"name": "Arutz Sheva",       "url": "https://news.google.com/rss/search?q=site:israelnationalnews.com&hl=en-US&gl=US&ceid=US:en",          "bias": "RIGHT",  "bias_score": 3},
            {"name": "Haaretz",           "url": "https://news.google.com/rss/search?q=site:haaretz.com&hl=en-US&gl=US&ceid=US:en",                    "bias": "LEFT",   "bias_score": -2},
            {"name": "i24 News",          "url": "https://news.google.com/rss/search?q=site:i24news.tv+israel&hl=en-US&gl=US&ceid=US:en",              "bias": "CENTER", "bias_score": 0},
            {"name": "Channel 14 (Kan14)","url": "https://news.google.com/rss/search?q=site:14tv.co.il&hl=he&gl=IL&ceid=IL:he",                        "bias": "RIGHT",  "bias_score": 3},
        ],
    },

    "markets": {
        "name": "שוקי הון",
        "emoji": "📈",
        "priority": 3,
        "max_articles": 2,    # 10% (shared financial quota with crypto)
        "sources": [
            {"name": "Reuters Finance",   "url": "https://news.google.com/rss/search?q=site:reuters.com+markets+finance&hl=en-US&gl=US&ceid=US:en",    "bias": "CENTER", "bias_score": 0},
            {"name": "Yahoo Finance",     "url": "https://finance.yahoo.com/news/rssindex",                                                             "bias": "CENTER", "bias_score": 0},
            {"name": "CNBC",             "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",                                               "bias": "CENTER", "bias_score": -1},
            {"name": "Zero Hedge",        "url": "https://feeds.feedburner.com/zerohedge/feed",                                                         "bias": "RIGHT",  "bias_score": 2},
            {"name": "MarketWatch",       "url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",                                   "bias": "CENTER", "bias_score": 0},
        ],
    },

    "crypto": {
        "name": "קריפטו",
        "emoji": "₿",
        "priority": 4,
        "max_articles": 1,    # 5%
        "sources": [
            {"name": "CoinDesk",          "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",                                                     "bias": "CENTER", "bias_score": 0},
            {"name": "CoinTelegraph",     "url": "https://cointelegraph.com/rss",                                                                       "bias": "CENTER", "bias_score": 0},
            {"name": "Bitcoin Magazine",  "url": "https://bitcoinmagazine.com/.rss/full/",                                                              "bias": "RIGHT",  "bias_score": 1},
        ],
    },

    "mediwound": {
        "name": "MediWound",
        "emoji": "💊",
        "priority": 5,
        "max_articles": 1,    # ~5% of other
        "sources": [
            {"name": "Google News",       "url": "https://news.google.com/rss/search?q=MediWound&hl=en-US&gl=US&ceid=US:en",                           "bias": "CENTER", "bias_score": 0},
            {"name": "Yahoo MDWD",        "url": "https://finance.yahoo.com/rss/headline?s=MDWD",                                                       "bias": "CENTER", "bias_score": 0},
        ],
    },

    "kanye": {
        "name": "קניה ווסט",
        "emoji": "🎤",
        "priority": 6,
        "max_articles": 1,
        "sources": [
            {"name": "Google News",       "url": "https://news.google.com/rss/search?q=Kanye+West&hl=en-US&gl=US&ceid=US:en",                          "bias": "CENTER", "bias_score": 0},
        ],
    },

    "messi": {
        "name": "ליאונל מסי",
        "emoji": "⚽",
        "priority": 7,
        "max_articles": 1,
        "sources": [
            {"name": "Google News",       "url": "https://news.google.com/rss/search?q=Lionel+Messi&hl=en-US&gl=US&ceid=US:en",                       "bias": "CENTER", "bias_score": 0},
        ],
    },

    "positive": {
        "name": "חדשות טובות",
        "emoji": "🌟",
        "priority": 8,
        "max_articles": 2,    # guarantee 2 positive articles
        "sources": [
            {"name": "Positive News",     "url": "https://www.positive.news/feed/",                                                                    "bias": "CENTER", "bias_score": 0},
            {"name": "Good News Network", "url": "https://www.goodnewsnetwork.org/feed/",                                                               "bias": "CENTER", "bias_score": 0},
            {"name": "Upworthy",          "url": "https://www.upworthy.com/feed",                                                                       "bias": "LEFT",   "bias_score": -1},
        ],
    },
}

# ── Rate limits ───────────────────────────────────────────────────────────────
RATE_LIMITS = {
    "max_per_run": 20,               # Hard cap: total articles sent per run
    "dedup_window_days": 7,          # Don't re-send articles seen this week
    "headline_sim_threshold": 75,    # % similarity → duplicate headline
    "cross_match_threshold": 65,     # % similarity → same story (for cross-match)
    "delay_between_messages": 2,     # Seconds between Telegram sends
    "min_significance_score": 5,     # Skip articles with global_significance < this
}

# ── Scheduler ─────────────────────────────────────────────────────────────────
SCHEDULE = {
    "interval_minutes": 60,
    "active_hour_start": 7,
    "active_hour_end": 23,
}

# ── Gemini model ──────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-flash-lite-latest"
GEMINI_MAX_INPUT_CHARS = 2000
