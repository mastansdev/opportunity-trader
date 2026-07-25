"""
==========================================================
News Bot
==========================================================

Independent, self-contained news intelligence pipeline.
Ingests -> matches -> (later) classifies -> tiers news, and
hands only HIGH-priority items to Brain Bot (the trading
engine). Brain Bot never sees a raw headline directly.

Build order (see ../PHASE3_NEWS_DESIGN.md, section 3.2):
    Stage 1 - ingestion.py       DONE
    Stage 2 - matching.py        DONE
    Stage 3 - classification.py  DONE (Claude Haiku, budget-capped
                                   by call_budget.py)
    Stage 4 - priority.py        DONE (DUMMY/MID/HIGH tiering)
    Interface - news_queue.py    DONE (audit log + HIGH-only queue)
    pipeline.py ties all four stages into one poll cycle, run every
    news_bot.config.POLL_INTERVAL_SECONDS by main.py's news thread.

Nothing in this package places trades or talks to the broker.
It only reads news, classifies/tiers it, and writes matched
items to a log. core/news_gate.py is the ONLY bridge to the
trading engine, and it is advisory/logging-only -- News Bot's
output does not block or arm any trade decision yet.

Author : H&M Opportunity Trader
==========================================================
"""
