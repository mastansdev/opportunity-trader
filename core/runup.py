"""
==========================================================
Was the good news already bought before it was announced?
==========================================================

    "some stocks will move even though good grade. as we both know
     market rewards by anticipating future ... by seeing them many
     FII/DII, retail Algos started to accumalte stocks"
                                -- operator, 7 August 2026

WHY THIS EXISTS
---------------
The bot reads the result grade and stops there. It has no idea whether
the stock spent the previous fortnight climbing into that result.

Researched 7 August 2026, and the operator had already read it off the
tape himself. Three separate causes, all documented:

  * PROFIT-TAKING. Whoever anticipated the result sells into the
    announcement. The good news is consumed on the way up.
  * PRICED IN. A stock that has already run needs an EXCEPTIONAL
    number to go further; merely meeting consensus removes the
    catalyst entirely.
  * GUIDANCE OUTRANKS THE PRINT. A beat with soft guidance sells off.

He described exactly this to me about TRENT before I had read a word
of the research:

    "in trent case the results were good but conviction on future
     growth expected higher but results agreed but store growth & some
     business updates not liked by investors"

WHAT IT MEASURES
----------------
The move into the result, over the sessions BEFORE it was announced.
Nothing after. That is the whole point -- this is the one question the
grade cannot answer, and it is answerable from data already on disk
(data/daily_candles.db). No new source, no download, no OCR.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not veto. Same standing rule as forensic quality:

    "nothing from the guides becomes a rule until scored against real
     outcomes"

It returns a reading and a number. Whether a 15% run-in should shrink
the size, drop the stock, or do nothing is a decision to be made from
scored outcomes, not from a paper. The bot must be able to SEE this
before anyone can argue about what to do with it.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3
from datetime import datetime, timedelta

DAILY_DB = "data/daily_candles.db"

# Sessions before the result to measure. Ten trading days is about a
# fortnight of calendar time -- long enough to catch a deliberate
# accumulation, short enough that it is still about THIS result.
LOOKBACK_SESSIONS = 10

# Readings. Chosen to describe, not to judge.
SPENT_PCT = 15.0        # the move has probably already happened
WARM_PCT = 7.0          # some anticipation in the price
COLD_PCT = -5.0         # sold off into the result


def _rows(db_path, sql, args=()):
    try:
        con = sqlite3.connect(db_path)
        got = con.execute(sql, args).fetchall()
        con.close()
        return got
    except Exception:                                      # noqa: BLE001
        return []


def run_up(symbol, result_date, sessions=LOOKBACK_SESSIONS, db_path=DAILY_DB):
    """How far the stock travelled INTO its result.

    Returns {"ok", "pct", "reading", "from", "to", "sessions", "text"}
    or {"ok": False, "why": ...} when the history is not there.

    `result_date` is the day the result was announced. Everything
    measured is strictly BEFORE it -- a run-up that includes the
    result day is just the reaction, which we already have.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return {"ok": False, "why": "no symbol"}

    if isinstance(result_date, str):
        try:
            result_date = datetime.fromisoformat(result_date[:10]).date()
        except Exception:                                  # noqa: BLE001
            return {"ok": False, "why": "unreadable result date"}
    elif hasattr(result_date, "date"):
        result_date = result_date.date()

    # A generous calendar window; the session count does the real work.
    start = (result_date - timedelta(days=sessions * 3)).isoformat()
    bars = _rows(
        db_path,
        "select date, close from daily_bars where symbol = ? "
        "and date < ? and date >= ? and close is not null "
        "order by date", (symbol, result_date.isoformat(), start))

    if len(bars) < 3:
        return {"ok": False,
                "why": f"only {len(bars)} session(s) of history before "
                       f"the result -- cannot say"}

    window = bars[-sessions:] if len(bars) > sessions else bars
    first_date, first_close = window[0]
    last_date, last_close = window[-1]
    if not first_close:
        return {"ok": False, "why": "no usable close"}

    pct = (last_close - first_close) / first_close * 100.0

    if pct >= SPENT_PCT:
        reading = "SPENT"
        text = (f"already ran {pct:+.1f}% in the {len(window)} sessions "
                f"before the result -- the good news may be bought")
    elif pct >= WARM_PCT:
        reading = "WARM"
        text = (f"climbed {pct:+.1f}% into the result -- some of it is "
                f"anticipated")
    elif pct <= COLD_PCT:
        reading = "SOLD OFF"
        text = (f"fell {pct:+.1f}% into the result -- nothing was "
                f"anticipated, a good number is a surprise")
    else:
        reading = "FLAT"
        text = (f"went {pct:+.1f}% into the result -- the market was not "
                f"positioned either way")

    return {"ok": True, "pct": round(pct, 2), "reading": reading,
            "from": first_date, "to": last_date,
            "sessions": len(window), "text": text}


def for_symbols(symbols, result_date, **kwargs):
    """run_up() across a list, skipping the ones with no history."""
    out = {}
    for symbol in (symbols or []):
        got = run_up(symbol, result_date, **kwargs)
        if got.get("ok"):
            out[str(symbol).upper()] = got
    return out


# ---------------------------------------------------------------
# The live entry point -- "when did this stock report, and how far had
# it already travelled by then?"
# ---------------------------------------------------------------
RESULTS_DB = "data/results_calendar.db"

# A result older than this is history, not a setup. Ten sessions is
# roughly the horizon over which the drift is still being traded.
RECENT_RESULT_DAYS = 12

_reported_cache = {}


def reported_on(symbol, on_date=None, results_db=RESULTS_DB,
                within_days=None):
    """The most recent results date for this stock at or before
    `on_date`, or None.

    Time-bounded on purpose. graded_symbols() had to learn the same
    lesson on 8 August: a function that can only answer "right now"
    cannot be replayed, and every number built on it is unfalsifiable.

    `within_days` defaults to RECENT_RESULT_DAYS (12), which is the
    window a RUN-UP reading needs -- there is no run-up into a result
    three weeks old. Callers asking a different question pass their
    own: core/engine.py stamps days_since_results onto every position
    and 24 days since results is a real answer, not a None.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return None
    on_date = on_date or datetime.now()
    if hasattr(on_date, "date"):
        on_date = on_date.date()
    key = (symbol, on_date.isoformat(), results_db, within_days)
    if key in _reported_cache:
        return _reported_cache[key]

    window = RECENT_RESULT_DAYS if within_days is None else int(within_days)
    floor = (on_date - timedelta(days=window)).isoformat()
    rows = _rows(
        results_db,
        "select results_date from results_events where upper(symbol) = ? "
        "and results_date <= ? and results_date >= ? "
        "order by results_date desc limit 1",
        (symbol, on_date.isoformat(), floor))
    got = None
    if rows and rows[0] and rows[0][0]:
        try:
            got = datetime.fromisoformat(str(rows[0][0])[:10]).date()
        except Exception:                                  # noqa: BLE001
            got = None
    if len(_reported_cache) > 4000:
        _reported_cache.clear()
    _reported_cache[key] = got
    return got


def reading(symbol, on_date=None, results_db=RESULTS_DB, db_path=DAILY_DB):
    """The run-up reading for a stock that has recently reported.

    None when it has not reported inside the window -- there is no
    "run-up into a result" for a stock with no result behind it, and
    inventing one would be exactly the kind of confident noise this
    module is meant to replace.
    """
    when = reported_on(symbol, on_date=on_date, results_db=results_db)
    if when is None:
        return None
    got = run_up(symbol, when, db_path=db_path)
    if not got.get("ok"):
        return None
    got["result_date"] = when.isoformat()
    return got
