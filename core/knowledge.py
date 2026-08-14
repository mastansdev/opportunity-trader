"""
==========================================================
What the bot KNOWS -- and whether it is allowed to use it
==========================================================

    "bot is getting results, news. but i'm not sure whether bot knows
     it. stores it and reuses when ever the same situation arises."
                                -- operator, 12 August 2026

He asked the one question no panel could answer. The bot has eleven
separate stores holding 200,000-odd rows, and the screen showed the
CONTENTS of some of them and the STATUS of none. So "is it working"
could only be answered by opening a database.

Worse, the honest answer to his question is in three parts and the
screen showed none of them:

    KNOWS    the feed arrives and is parsed          mostly yes
    STORES   it survives a restart                   yes, all of it
    REUSES   it changes a decision next time         MOSTLY NO

That last one is not a fault, it is a decision -- made deliberately,
three times, and written into the files themselves:

    core/trade_memory.py    "IT DOES NOT VOTE."
    core/outcomes.py        "nothing in the trading path imports it"
    dashboard/chip_stats.py kept out of state.py on purpose

Every one of those is right on its own terms: acting on a week of data
is the mistake tools/refused_review.py warns about in as many words.
But three separate files each quietly deciding not to vote adds up to a
bot that measures itself and never learns, and nobody looking at the
dashboard could tell.

WHAT THIS MODULE IS
-------------------
A read-only census. For every store: how many rows, how fresh, and --
the column that matters -- WHERE IT REACHES.

    DECIDES      read on the entry path. It can stop or allow a trade.
    SHOWS        drawn on screen. A human may act on it; the bot never.
    RECORDS      written and read by nobody. Measurement only.

Nothing here computes a signal, changes a score or touches a decision.
It reports what is already true, so that "does the bot use this" stops
being a question you have to read the source to answer.

FAIL-SOFT THROUGHOUT. A store that cannot be opened is reported as
unreadable and never raises -- a census that can crash the dashboard
would be worse than no census.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
from datetime import datetime, timedelta

# ---------------------------------------------------------------
# WHERE EACH STORE REACHES
# ---------------------------------------------------------------
# Hand-written on 12 August 2026 by reading the import graph, NOT
# guessed. Each entry names the file that proves the claim, so the next
# person can check it in one grep instead of trusting this comment.

DECIDES = "DECIDES"      # on the entry path -- can stop or allow a trade
SHOWS = "SHOWS"          # on the screen -- a human may act, the bot does not
RECORDS = "RECORDS"      # written, and read by nothing

STORES = (
    # ---- these three can refuse a trade -------------------------
    dict(key="quarterly_results", label="Quarterly results (parsed)",
         db="data/quarterly_results.db", table="quarterly_results",
         date_col="read_at", reach=DECIDES,
         proof="core/results_gate.py grade_for() -> block_reason()",
         note="a MIXED or WEAK grade blocks the stock on its results day"),

    dict(key="results_calendar", label="Who reports, and when",
         db="data/results_calendar.db", table="results_events",
         date_col=None, reach=DECIDES,
         proof="core/results_gate.py reports_today()",
         note="being on the calendar is what makes the gate apply at all"),

    dict(key="stock_memory", label="Corporate actions (split/bonus/rights)",
         db="data/stock_memory.db", table="stock_actions",
         date_col="created_at", reach=DECIDES,
         proof="core/engine.py _memory_block_reason()",
         note="the JLHL fix -- a 2:10 split read as an 80% crash"),

    # ---- these reach the screen and stop there ------------------
    dict(key="stock_events", label="Channel events (results/orders/news)",
         db="data/stock_events.db", table="events", date_col="at",
         reach=SHOWS,
         proof="core/watchlist_builder.py -> Row 1; core/ranker.py",
         note="the published grade IS consulted at entry via "
              "results_gate._published_grade()"),

    dict(key="news_memory", label="News stories, and which stocks they touch",
         db="data/news_memory.db", table="news", date_col="at",
         reach=SHOWS,
         proof="core/news_impact.py -> dashboard/state.py build_news_impact()",
         note="stored always; UNDERSTOOD only when reasoning is on -- "
              "see the reasoning line below"),

    dict(key="telegram", label="Raw channel messages",
         db="data/telegram.db", table="messages", date_col=None,
         reach=SHOWS,
         proof="core/telegram_feed.py -> dashboard/state.py build_telegram()",
         note="read-only to the engine, on purpose"),

    dict(key="delivery", label="Delivery % (churn vs conviction)",
         db="data/delivery.db", table="delivery", date_col="date",
         reach=SHOWS,
         proof="core/delivery.py -> the stock card",
         note="needs ~10 sessions before it says anything at all"),

    dict(key="feeds", label="Stored feed rows",
         db="data/feeds.db", table="feed_rows", date_col=None,
         reach=SHOWS, proof="core/feed_store.py", note=""),

    # ---- these are written and read by nobody --------------------
    dict(key="trade_memory", label="Completed trades, with entry context",
         db="data/trade_memory.db", table="trade_memory",
         date_col="recorded_at", reach=RECORDS,
         proof="core/trade_memory.py -- its own docstring says "
               "'IT DOES NOT VOTE'",
         note="the learning loop. Measured, reported, never consulted",
         # ---- STALE HERE IS NOT A FAULT. 13 August 2026. ----
         # This store only grows when a trade CLOSES. With the bot
         # observing -- which is now the startup default and his
         # deliberate choice -- it cannot grow, so an age check on it
         # reports a problem every single night for a bot behaving
         # exactly as instructed. See _stale_matters() below.
         grows_daily=False),

    dict(key="decisions", label="Picks and refusals",
         db="data/decisions.db", table="refusals", date_col=None,
         reach=RECORDS,
         proof="core/decision_log.py -> tools/refused_review.py",
         note="what the bot said no to, and why"),

    dict(key="signal_journal", label="Every signal, taken and refused",
         db="data/signal_journal.db", table="signals", date_col=None,
         reach=RECORDS,
         proof="core/signal_journal.py -> dashboard build_journal()",
         note="the diagnostic for 'where are we going wrong'"),
)


def _one(store):
    """Row count, freshness and reach for a single store. Never raises."""
    out = dict(key=store["key"], label=store["label"], reach=store["reach"],
               proof=store["proof"], note=store["note"], db=store["db"],
               grows_daily=store.get("grows_daily", True),
               rows=None, latest=None, stale_days=None, readable=False,
               problem=None)
    path = store["db"]
    if not os.path.exists(path):
        out["problem"] = "no such file -- this store has never been written"
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    except Exception as exc:                                # noqa: BLE001
        out["problem"] = f"cannot open ({type(exc).__name__})"
        return out
    try:
        out["rows"] = conn.execute(
            f'select count(*) from "{store["table"]}"').fetchone()[0]
        out["readable"] = True
        if store["date_col"]:
            newest = conn.execute(
                f'select max("{store["date_col"]}") from "{store["table"]}"'
            ).fetchone()[0]
            out["latest"] = str(newest) if newest else None
            out["stale_days"] = _age_days(newest)
    except Exception as exc:                                # noqa: BLE001
        out["problem"] = f"unreadable ({type(exc).__name__}: {exc})"
    finally:
        try:
            conn.close()
        except Exception:                                   # noqa: BLE001
            pass
    return out


def _age_days(stamp):
    """Whole days between `stamp` and now, or None if it cannot be read.

    Deliberately tolerant: these columns hold ISO dates, ISO datetimes
    with and without a timezone, and a couple of plain YYYY-MM-DD
    strings. Parsing all of them is not worth a dependency, and a
    freshness figure we cannot compute must read as unknown rather than
    as zero -- a stale store reported as fresh is the failure this
    whole module exists to catch.
    """
    if not stamp:
        return None
    text = str(stamp).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            when = datetime.strptime(text[:len(datetime.now().strftime(fmt))],
                                     fmt)
            return max(0, (datetime.now() - when).days)
        except ValueError:
            continue
    return None


def census():
    """Every store, with how much is in it and where it reaches.

    Returns a dict shaped for the dashboard. Never raises.
    """
    stores = [_one(s) for s in STORES]
    by_reach = {DECIDES: [], SHOWS: [], RECORDS: []}
    for s in stores:
        by_reach[s["reach"]].append(s)

    problems = [s for s in stores if s["problem"]]
    empty = [s for s in stores if s["readable"] and not s["rows"]]
    # Three sessions is the bar: NSE publishes daily, so anything that
    # has not moved in three CALENDAR days has missed at least one
    # trading session and probably two.
    # ---- STALE MUST MEAN "SOMETHING STOPPED". 13 August 2026. ----
    #
    # The nightly `health` step exited 1 on the first evening it ran,
    # for two states he had chosen on purpose: news reasoning off, and
    # trade_memory three days old because the bot is OBSERVING and no
    # trade has closed.
    #
    # A step that fails every night is a step he stops reading -- the
    # exact trap tools/learning_report.py's own caveat warns about, and
    # walked into within hours of writing it.
    #
    # So staleness is only counted for stores that SHOULD grow every
    # session -- prices, filings, channel events. A store that only
    # grows when something happens cannot be stale for not happening.
    stale = [s for s in stores
             if s["stale_days"] is not None and s["stale_days"] >= 3
             and s.get("grows_daily", True)]

    # Computed ONCE. It opens the news store and reads config, and both
    # the payload and the verdict want the same answer -- calling it
    # twice could report two different states in one response.
    reasoning = _reasoning()

    return {
        "available": True,
        "checked_at": datetime.now().strftime("%H:%M:%S"),
        "stores": stores,
        # ---- STORED IS NOT UNDERSTOOD. 12 August 2026. ----
        # A row count cannot tell these apart, and the difference is the
        # operator's whole question. 1,561 stories arrived between 6 and
        # 11 August and NOT ONE was reasoned about, because
        # config.AI_ENABLED had been off since the 10th. The census
        # would have shown a healthy, growing, fresh store the entire
        # time -- which is true, and useless.
        "reasoning": reasoning,
        "counts": {
            "decides": len(by_reach[DECIDES]),
            "shows": len(by_reach[SHOWS]),
            "records": len(by_reach[RECORDS]),
            "total_rows": sum(s["rows"] or 0 for s in stores),
        },
        "problems": [f"{s['label']}: {s['problem']}" for s in problems],
        "empty": [s["label"] for s in empty],
        "stale": [f"{s['label']}: {s['stale_days']} days old"
                  for s in stale],
        # The sentence he asked for, computed rather than claimed.
        "verdict": _verdict(by_reach, problems, stale, reasoning),
    }


def _reasoning():
    """Is news being UNDERSTOOD, or only filed?

    A keyword match is not a reason, and core/ranker.py agrees -- it
    refuses one outright ("reason is a lookup, not a mechanism"). So a
    news store that is full and fresh and entirely unreasoned starves
    the ranked entry lane while looking perfectly healthy.

    Never raises; an unreadable answer reads as unknown.
    """
    out = {"on": None, "reasoned": None, "total": None, "blocked_by": None,
           "recent_reasoned": None, "recent_total": None,
           # WHICH of the two switches is off. tools/knowledge_report.py
           # needs this to tell "he turned it off" from "it should be
           # working and is not" -- the first is a decision, the second
           # is a fault, and only the second may fail the nightly.
           "ai_enabled": None, "has_key": None}
    try:
        from core.news_impact import NewsImpact
        status = NewsImpact().status()
        out["on"] = status.get("reasoning_on")
        out["reasoned"] = status.get("reasoned")
        out["total"] = status.get("news")
        out["blocked_by"] = status.get("blocked_by")
        out["ai_enabled"] = status.get("ai_enabled")
        out["has_key"] = status.get("has_key")
    except Exception:                                       # noqa: BLE001
        return out
    # The last week specifically. A lifetime total of 1,065 reasoned
    # looks fine and hid six days of zero.
    try:
        conn = sqlite3.connect(f"file:{os.path.join('data', 'news_memory.db')}"
                               f"?mode=ro", uri=True, timeout=2.0)
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(reasoned), 0) FROM news "
            "WHERE substr(at, 1, 10) >= ?", (cutoff,)).fetchone()
        conn.close()
        out["recent_total"], out["recent_reasoned"] = int(row[0]), int(row[1])
    except Exception:                                       # noqa: BLE001
        pass
    return out


def _verdict(by_reach, problems, stale, reasoning=None):
    """One plain sentence. This is the answer to his actual question."""
    decides = sum(1 for s in by_reach[DECIDES] if s["rows"])
    records = len(by_reach[RECORDS])
    parts = [
        f"{decides} of {len(by_reach[DECIDES])} stores can stop or allow a "
        f"trade. {len(by_reach[SHOWS])} reach the screen only. "
        f"{records} are measured and never consulted -- the learning loop "
        f"does not vote yet, by design."
    ]
    # ---- THE LOUDEST THING BELONGS IN THE SENTENCE. ----
    # A store can be full, fresh and completely misunderstood. Between
    # 6 and 11 August the news store grew by 1,561 rows and reasoned
    # ZERO of them, and every count on every panel read healthy.
    if reasoning and reasoning.get("on") is False:
        recent, got = reasoning.get("recent_total"), reasoning.get(
            "recent_reasoned")
        if recent:
            parts.append(
                f"NEWS IS NOT BEING UNDERSTOOD: only {got} of {recent} "
                f"stories in the last 7 days were reasoned about. The rest "
                f"are keyword matches carrying no direction, and "
                f"core/ranker.py refuses those outright.")
        else:
            parts.append("NEWS REASONING IS OFF.")
        if reasoning.get("blocked_by"):
            parts.append(reasoning["blocked_by"])
    if problems:
        parts.append(f"{len(problems)} store(s) could not be read.")
    if stale:
        parts.append(f"{len(stale)} store(s) have gone stale.")
    return " ".join(parts)
