"""
News Bot -- own config, deliberately separate from the main
bot's config.py. Keeps News Bot runnable and testable in
total isolation from the trading engine (see
PHASE3_NEWS_DESIGN.md, section 3.1).
"""

# How often to poll RSS sources during market hours. RSS is
# poll-based, not push -- this is an honest limitation, not a
# bug (see PHASE3_NEWS_DESIGN.md, section 3.4, Concern #1).
POLL_INTERVAL_SECONDS = 45

# Stage 3 (AI classification) daily call cap -- set here now
# so it exists before Stage 3 is built, per the cost-control
# decision in PHASE3_NEWS_DESIGN.md section 4. Not enforced
# yet; Stage 3 will read this when it's built.
MAX_AI_CALLS_PER_DAY = 800

# ----------------------------------------------------------
# Classifier selection, 2026-07-24 -- FREE now, paid Haiku later
# ----------------------------------------------------------
#
# "auto"    -- use Haiku if configured (ANTHROPIC_API_KEY + package),
#              else fall back to the FREE keyword classifier. Best of
#              both: zero cost until the key is added, Haiku after.
# "keyword" -- always use the free keyword classifier (no API cost).
# "haiku"   -- always use Haiku (skip items if not configured, as
#              before).
NEWS_CLASSIFIER_MODE = "auto"

# Whether crude KEYWORD-classified HIGH news is allowed to BLOCK a
# trade (core/engine.py's news-contradiction gate). Default False:
# keyword news is too rough to veto a real-money trade, so it's
# DISPLAY-ONLY (dashboard) until the trustworthy paid Haiku
# classifier is on. Haiku-classified news always blocks regardless.
NEWS_KEYWORD_CAN_BLOCK = False

# ----------------------------------------------------------
# Exchange corporate announcements (NSE + BSE)
# ----------------------------------------------------------

# Both use the `nse` / `bse` PyPI packages (see
# exchange_announcements.py). Both have a known real risk,
# carried over from the old bot: NSE/BSE have been observed
# refusing connections from cloud/datacenter IPs. First real
# run's log output is the actual verdict for your machine --
# these flags exist so either side can be switched off without
# touching code if one of them proves unreliable in practice.
EXCHANGE_NSE_ENABLED = True
EXCHANGE_BSE_ENABLED = True

EXCHANGE_NSE_LOOKBACK_DAYS = 1
EXCHANGE_BSE_PAGES_PER_POLL = 1  # BSE paginates; start conservative

# ----------------------------------------------------------
# Persistent store (news_bot/news_store.py), 2026-07-24 -- the
# 24/7 engine + per-stock "brain". SQLite locally, Postgres on
# Railway (set via the DATABASE_URL env var, which overrides
# NEWS_DB_URL_DEFAULT). See news_store.resolve_database_url().
# ----------------------------------------------------------

# Local fallback when DATABASE_URL isn't set (i.e. not on Railway).
# A plain file next to the other data files -- survives restarts, so
# dedup memory and the per-stock history persist across runs.
NEWS_DB_URL_DEFAULT = "sqlite:///data/news.db"

# How long a HIGH item stays ACTIONABLE for the brain bot after we
# record it. The store keeps everything forever (the per-stock brain);
# this only bounds what still counts as "fresh enough to trade on".
# 72h so Friday-evening / weekend news carries into Monday's session
# but a genuinely stale headline stops vetoing trades. Tunable.
NEWS_ACTIONABLE_WINDOW_HOURS = 72

# How many recent MID+HIGH items the dashboard news panel shows.
NEWS_RECENT_FEED_LIMIT = 60

# 2026-07-24 -- who runs the poll loop. True: the engine runs as its
# own 24/7 process (run_news_engine.py, e.g. on Railway), so main.py
# must NOT run its own in-process news loop (that would double-write);
# the brain bot just READS the shared store. False: main.py runs the
# news loop in-process (original behavior, fine for pure-local dev
# with no separate worker). Reading the store works either way.
NEWS_ENGINE_EXTERNAL = True

# Standalone 24/7 news dashboard (news_dashboard.py) -- its OWN page on
# its OWN port, separate from the trading dashboard (which lives inside
# main.py and only runs during market hours). Runs day or night,
# reading the shared store. Different port from the trading dashboard
# (8000) so both can run at once.
NEWS_DASHBOARD_HOST = "127.0.0.1"
NEWS_DASHBOARD_PORT = 8050
# How often (seconds) the page auto-refreshes its data.
NEWS_DASHBOARD_REFRESH_SECONDS = 20

# 2026-07-24 -- do NOT store NEUTRAL / no-signal news. Diagnosed live:
# 78.6% of stored rows were neutral "no directional keywords" items
# (general filings, "board meeting scheduled", a sector headline
# fanned across a dozen stocks) -- exactly the vague/dummy updates
# that carry ZERO trade signal and were meant to be discarded from
# the start. Only genuinely directional news (bullish/bearish) and
# HIGH items are worth keeping in the per-stock brain. Set True only
# if you ever want the raw firehose back.
NEWS_STORE_NEUTRAL = False

# 2026-07-24 -- BUDGET CONTROL for the paid AI (Haiku) classifier.
# The operator wants the API on but on a tight budget: "I do not want
# every junk to move to AI & waste money." Two rules enforce that:
#
#   1. Only COMPANY-tier news (a headline that names the specific
#      stock, or a direct exchange filing) is worth a paid call. The
#      broad SECTOR/THEME/COMMODITY fan-out (one story -> a dozen
#      stocks, ~93% of volume) stays on the FREE keyword classifier.
#      Set False to send every matched item to AI (the old, costly
#      behavior) if you ever want it.
#
#   2. The pipeline skips anything already in the store BEFORE
#      classifying (news_store.exists()), so a story re-seen on later
#      poll cycles is never re-sent to the AI. Each (story, stock) is
#      billed at most once, ever. Combined with MAX_AI_CALLS_PER_DAY,
#      spend is bounded and predictable.
NEWS_AI_ONLY_COMPANY_TIER = True
