"""How fast is this stock trading RIGHT NOW, against its own normal.

    "i want bot trade by finding opportunity as they arrives not by its
     own timing limitations"          -- operator, 23 August 2026

THE BUG THIS EXISTS TO FIX

ranker.volume_ratio() divides today's traded value by adv_cr, the
stock's average value for a WHOLE day. Before the close, the numerator
is a part-day and the denominator is a full day, so the answer is not
"how busy is this stock" -- it is "what time is it".

Measured from this stock's own 1-minute history, the share of a normal
day already traded by each hour:

    stock        09:20    09:30    10:00    11:00    13:00    15:00
    SBIN          3.8%     7.0%    15.4%    28.7%    55.1%    85.1%
    RAILTEL       9.7%    16.7%    30.2%    46.7%    64.3%    83.2%

A stock running at FIVE TIMES its normal pace at 09:30 reads 0.5x and
is refused as quiet. A dull stock at 15:00 reads 0.85x and outranks it.
The field the seats are SORTED ON is dominated by the clock.

That is the whole reason nothing could be named before 09:30: the
number was meaningless that early. It was no more meaningful at 10:00,
only less obviously so.

WHAT THIS DOES INSTEAD

Divides by what THIS stock normally has traded BY THIS MINUTE. Then
5x pace reads 5x at 09:20 and 5x at 14:50, and an opportunity can be
recognised when it arrives instead of once the day has caught up.

    "never pool all stocks , never average the stocks data. thats not
     stock working mechanism"          -- operator, 22 August 2026

Every curve is built from that one symbol's own days. SBIN has traded
7.0% of its day by 09:30 and RAILTEL 16.7% -- a single shared curve
would misprice both. There is no fallback curve and no default: a
stock without enough history of its own is UNMEASURED, which
finders.TradeBrain already sorts last.
"""

import json
import os
import sqlite3
import statistics

HISTORY_DB = os.path.join("data", "history_candles.db")
PROFILE_PATH = os.path.join("data", "volume_profile.json")

# Below this many days of its own the curve is noise, not a normal.
MIN_DAYS = 20

# Dividing by a very small fraction turns a rounding error into a
# headline multiple. At 09:16 a stock has traded well under 1% of its
# day; one block trade reads as 40x pace. Under this, say UNMEASURED.
MIN_EXPECTED_FRACTION = 0.02

_CACHE = None
_CACHE_AT = 0.0


def _hhmm(value):
    """A clock reading as "HH:MM", or None."""
    if value is None:
        return None
    try:
        return "%02d:%02d" % (value.hour, value.minute)
    except AttributeError:
        pass
    text = str(value).strip()
    if len(text) >= 16 and text[10] in "T ":
        text = text[11:16]
    if len(text) == 5 and text[2] == ":":
        return text
    return None


def build_profile(history_db=HISTORY_DB, out_path=PROFILE_PATH,
                  min_days=MIN_DAYS):
    """Write each symbol's own intraday volume curve. Returns the count."""
    con = sqlite3.connect(history_db)
    try:
        rows = con.execute(
            "select symbol, date, substr(minute, 12, 5) hm, sum(v) "
            "from candles group by symbol, date, hm"
        ).fetchall()
    finally:
        con.close()

    # symbol -> date -> [(hm, volume)]
    days = {}
    for symbol, date, hm, vol in rows:
        if not hm or vol is None:
            continue
        days.setdefault(symbol, {}).setdefault(date, []).append((hm, vol))

    # The minute grid every curve is expressed on. Building one grid
    # and forward-filling onto it once per day keeps this linear; the
    # first version compared every minute against every other and took
    # longer than the trading day it was measuring.
    grid = []
    for hour in range(9, 16):
        for minute in range(0, 60):
            if (hour, minute) < (9, 15) or (hour, minute) > (15, 30):
                continue
            grid.append("%02d:%02d" % (hour, minute))

    profile = {}
    for symbol, by_date in days.items():
        per_day = []
        for bars in by_date.values():
            total = sum(v for _, v in bars)
            if total <= 0:
                continue
            bars.sort()
            seen = 0.0
            exact = {}
            for hm, vol in bars:
                seen += vol
                exact[hm] = seen / total
            # Forward-fill: a minute with no bar carries the running
            # total, it has NOT traded nothing for the day.
            filled = []
            carry = 0.0
            for hm in grid:
                if hm in exact:
                    carry = exact[hm]
                filled.append(carry)
            per_day.append(filled)

        if len(per_day) < min_days:
            continue

        merged = {}
        for i, hm in enumerate(grid):
            merged[hm] = round(statistics.median(d[i] for d in per_day), 6)
        profile[symbol] = {"days": len(per_day), "curve": merged}

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(profile, handle, separators=(",", ":"), sort_keys=True)
    return len(profile)


def load(path=PROFILE_PATH, force=False):
    """The profile, cached. {} when it has never been built.

    An EMPTY result is never cached as final. If the file is missing
    at the first lookup of the session -- the nightly build failed, or
    it is a fresh clone -- caching {} would silently fall back to the
    whole-day divisor for the entire day, which is the exact bug this
    module exists to fix and would be invisible. Retried at most once
    a minute so a permanently missing file costs nothing.
    """
    global _CACHE, _CACHE_AT
    import time
    now = time.time()
    if _CACHE and not force:
        return _CACHE
    if _CACHE is not None and not force and (now - _CACHE_AT) < 60:
        return _CACHE
    try:
        with open(path, encoding="utf-8") as handle:
            _CACHE = json.load(handle)
    except (OSError, ValueError):
        _CACHE = {}
    _CACHE_AT = now
    return _CACHE


def expected_fraction(symbol, now, profile=None):
    """How much of a normal day THIS stock has traded by now, or None."""
    if not symbol:
        return None
    clock = _hhmm(now)
    if clock is None:
        return None
    entry = (load() if profile is None else profile).get(str(symbol).upper())
    if not entry or entry.get("days", 0) < MIN_DAYS:
        return None
    curve = entry.get("curve") or {}
    # The last minute at or before now.
    below = [v for m, v in curve.items() if m <= clock]
    if not below:
        return None
    fraction = max(below)
    if fraction < MIN_EXPECTED_FRACTION:
        return None
    return fraction


def pace_ratio(traded_cr, adv_cr, symbol, now, profile=None):
    """Today's pace against this stock's own normal pace by this minute.

    None means UNMEASURED -- not quiet. Callers must not score it as 0.
    """
    if not adv_cr or traded_cr is None:
        return None
    fraction = expected_fraction(symbol, now, profile=profile)
    if fraction is None:
        return None
    expected_cr = adv_cr * fraction
    if expected_cr <= 0:
        return None
    return (traded_cr / expected_cr)
