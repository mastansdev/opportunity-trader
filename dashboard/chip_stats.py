"""
==========================================================
What each chip is WORTH -- served to the screen, kept off the path
==========================================================

    "have you linked these chips grading into pipeline = dashboard ?"
                                -- operator, 12 August 2026

The numbers in the chip tooltips were measured by hand on 1 August and
typed into the HTML, where they had been ageing for eleven days. On
re-measurement ONE-OFF had gone from "-1.61%, fell 72%" on n=25 to
"-0.02%, up 48.6%" on n=109 -- a live warning resting on a number that
had quietly evaporated. So the tooltips now read the measurement.

WHY THIS IS NOT IN dashboard/state.py
-------------------------------------
It was, for about ten minutes, and tests/test_outcomes.py caught it:

    "Acting on a week of data is the mistake refused_review.py already
     warns about in as many words. When this DOES earn its way into a
     score it should be a decision someone made on purpose, not an
     import that crept in."

state.py decides what the panel shows and ranks; it is on that guarded
list on purpose. Displaying a chip's past performance is harmless
today and is exactly how a measurement starts leaking into a decision,
which is the thing the guard exists to prevent. So the import lives
here, in a module nothing on the trading path touches, and only
dashboard/server.py -- the HTTP layer -- reaches it.

If this ever WANTS to change a score, that should be someone deciding
to, in daylight, not this file quietly growing a caller.

NEVER BLOCKS, NEVER RAISES
--------------------------
The measurement walks the whole event store and rebuilds 207 grids out
of telegram.db: about 45 seconds. The first caller starts a thread and
gets {} back; the panel keeps its hardcoded fallbacks until the real
numbers land. A grading module falling over costs the footnote, never
the trading screen.

Author : H&M Opportunity Trader
==========================================================
"""

from __future__ import annotations

import threading
from datetime import datetime

_cache = {"day": None, "stats": {}}
_running = False
_lock = threading.Lock()


def _measure():
    """Both graders, flattened to one {chip: {...}}. Swallows everything."""
    stats = {}
    try:
        from core import outcomes
        for label, row in (outcomes.measure() or {}).items():
            if label.startswith("_") or not isinstance(row, dict):
                continue
            stats[label] = {"n": row["n"], "edge": row["edge_median"],
                            "up_pct": row["up_pct"], "enough": row["enough"]}
        # What it PAYS, not just which way it points. Seven chips change
        # SIGN between the median and the stopped mean, because a median
        # throws away the tail and the tail is the whole book.
        for label, row in (outcomes.expectancy() or {}).items():
            if label in stats and isinstance(row, dict):
                stats[label]["paid"] = row["mean_stopped"]
                stats[label]["rupees"] = row["rupees"]
                stats[label]["tail_share"] = row["tail_share"]
    except Exception:                                      # noqa: BLE001
        pass
    try:
        from core import margin_outcomes
        for label, row in (margin_outcomes.measure() or {}).items():
            if label.startswith("_") or not isinstance(row, dict):
                continue
            stats[label] = {"n": row["n"], "edge": row["edge_median"],
                            "up_pct": row["up_pct"], "enough": row["enough"]}
    except Exception:                                      # noqa: BLE001
        pass
    return stats


def _work(day):
    global _running
    try:
        stats = _measure()
        if stats:
            _cache["day"], _cache["stats"] = day, stats
    finally:
        _running = False


def current():
    """{chip: {n, edge, up_pct, enough, paid, rupees, tail_share}}.

    Returns whatever is cached -- {} on the very first call -- and
    kicks off today's measurement in the background if it is stale.
    """
    global _running
    day = datetime.now().strftime("%Y-%m-%d")
    if _cache["day"] == day:
        return _cache["stats"]
    with _lock:
        if not _running:
            _running = True
            try:
                threading.Thread(target=_work, args=(day,), daemon=True,
                                 name="chip-stats").start()
            except Exception:                              # noqa: BLE001
                _running = False
    return _cache["stats"]


def ready():
    return _cache["day"] == datetime.now().strftime("%Y-%m-%d")
