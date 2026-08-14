"""
==========================================================
py tools/study_picks.py  --  what actually separates a winner
==========================================================

    "bot must pick the best of the available not like the first moving
     as it picked in old model as a first come = first buy"
                                -- operator, 8 August 2026

WHY THIS EXISTS
---------------
Three days replayed through core/select.py: 33 trades, 8 winners, a
24% hit rate against the 33% that a 2:1 payoff needs to break even.
And the three stocks it ranked HIGHEST were the three that lost worst.

So the weights in core/select.py are not sorting by anything. They
were chosen by me, from reasoning, and never measured. This measures
them -- and every other number the bot can see at 09:30 -- against
what the stock actually went on to do.

THE ONE RULE THIS FILE OBEYS
----------------------------
Every feature must be computable at 09:30 from data that existed at
09:30. Nothing from later in the day, nothing from the daily bar,
nothing from a card that arrived at lunchtime.

    "i don't believe your backdata & you know the reason"

He was right that time -- a "has a card today" flag had been applied
to bars recorded before the card existed. The volume baseline here
uses days STRICTLY BEFORE the day being scored, and the 09:30 snapshot
is built only from 09:15-09:30 bars.

WHAT AN OUTCOME MEANS
---------------------
Entry at the 09:30 price, then the live exit rules exactly:

    stop     -1.8%   (core/exit_plan.STOP_PCT)
    target   +3.6%   (2:1, agreed 8 August)
    lock      +1R once the stock runs 1.5R
    else      the close

Result is stated in R -- multiples of the risk -- so a Rs 300 stock
and a Rs 3,000 stock are directly comparable. +2R is a target, -1R is
a stop.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANDLES = "data/backtest_candles.db"
DAILY = "data/daily_candles.db"
TELEGRAM = "data/telegram.db"

DECIDE_AT = "09:30"        # the snapshot, and the entry
STOP_PCT = 1.8
TARGET_R = 2.0
LOCK_AFTER_R = 1.5
LOCK_AT_R = 1.0

# Below this a stock is untradeable by his hard rule, so it must not
# appear in a study that shapes what the bot picks.
MIN_PRICE_RS = 50.0

# Below this the tape is too thin for the numbers to mean anything.
MIN_TURNOVER_CR_BY_0930 = 0.30

IST_OFFSET = timedelta(hours=5, minutes=30)


# ---------------------------------------------------------------
def _snapshot(con, day):
    """Every symbol as it looked at 09:30, from 09:15-09:30 bars only."""
    rows = con.execute(
        "select symbol, minute, o, h, l, c, v from candles "
        "where date = ? and substr(minute, 12, 5) <= ? order by symbol, minute",
        (day, DECIDE_AT)).fetchall()
    out = {}
    for symbol, minute, o, h, l, c, v in rows:
        st = out.setdefault(symbol, {"open": o, "high": h, "low": l,
                                     "ltp": c, "vol": 0.0, "bars": 0})
        if h is not None:
            st["high"] = max(st["high"], h)
        if l is not None:
            st["low"] = min(st["low"], l)
        st["ltp"] = c
        st["vol"] += (v or 0.0)
        st["bars"] += 1
    return out


def _history(day, symbols):
    """Per symbol, from days STRICTLY BEFORE `day`:
    prev close, average daily volume, average daily range, 5-day run-up."""
    con = sqlite3.connect(DAILY)
    con.execute("create index if not exists ix_sym_date "
                "on daily_bars(symbol, date)")
    got = {}
    for symbol in symbols:
        rows = con.execute(
            "select date, open, high, low, close, volume from daily_bars "
            "where symbol = ? and date < ? order by date desc limit 30",
            (symbol, day)).fetchall()
        if len(rows) < 6:
            continue
        closes = [r[4] for r in rows]
        vols = [r[5] or 0.0 for r in rows]
        spans = sorted((r[2] - r[3]) / r[1] * 100.0
                       for r in rows if r[1] and r[2] and r[3])
        got[symbol] = {
            "prev_close": closes[0],
            "avg_vol": sum(vols[:20]) / max(len(vols[:20]), 1),
            "range_pct": spans[len(spans) // 2] if spans else None,
            # How much of the move already happened before today. A
            # stock up 12% in a week has paid for its own news.
            "runup_5d": ((closes[0] - closes[5]) / closes[5] * 100.0
                         if len(closes) > 5 and closes[5] else None),
        }
    con.close()
    return got


def _cards(day):
    """{symbol: {"kind", "grade"}} from messages that arrived BEFORE the
    open on `day`. A card at 11:40 cannot inform a 09:30 decision."""
    ceiling = (datetime.fromisoformat(day).replace(hour=9, minute=15)
               - IST_OFFSET).isoformat()
    floor = (datetime.fromisoformat(day).replace(hour=9, minute=15)
             - IST_OFFSET - timedelta(hours=40)).isoformat()
    out = {}
    try:
        con = sqlite3.connect(TELEGRAM)
        rows = con.execute(
            "select symbols, coalesce(grade,''), coalesce(kind,'') "
            "from messages where at >= ? and at <= ? "
            "and symbols is not null and symbols != ''", (floor, ceiling)
        ).fetchall()
        con.close()
    except Exception:                                      # noqa: BLE001
        return out
    for symbols, grade, kind in rows:
        names = [s.strip().upper() for s in str(symbols).split(",") if s.strip()]
        # A card naming many companies is a list, not evidence about
        # any one of them -- core/subject.py's rule.
        if len(names) > 5:
            continue
        for name in names:
            slot = out.setdefault(name, {"grade": "", "kind": "", "cards": 0})
            slot["cards"] += 1
            if grade and not slot["grade"]:
                slot["grade"] = grade.upper()
            if kind and not slot["kind"]:
                slot["kind"] = kind.upper()
    return out


def _outcome(con, day, symbol, entry):
    """What the trade did, in R. None when the tape runs out."""
    bars = con.execute(
        "select h, l, c from candles where date = ? and symbol = ? "
        "and substr(minute, 12, 5) > ? order by minute",
        (day, symbol, DECIDE_AT)).fetchall()
    if len(bars) < 30:
        return None
    risk = entry * STOP_PCT / 100.0
    stop = entry - risk
    target = entry + risk * TARGET_R
    peak = entry
    for high, low, close in bars:
        if low is not None and low <= stop:
            return (stop - entry) / risk
        if high is not None:
            if high > peak:
                peak = high
                if (peak - entry) / risk >= LOCK_AFTER_R:
                    stop = max(stop, entry + risk * LOCK_AT_R)
            if high >= target:
                return TARGET_R
    return (bars[-1][2] - entry) / risk


# ---------------------------------------------------------------
def build(days=None):
    con = sqlite3.connect(CANDLES)
    con.execute("create index if not exists ix_day_sym "
                "on candles(date, symbol, minute)")
    if not days:
        days = [r[0] for r in con.execute(
            "select distinct date from candles order by date")]

    dataset = []
    for day in days:
        snap = _snapshot(con, day)
        hist = _history(day, list(snap))
        cards = _cards(day)
        for symbol, st in snap.items():
            past = hist.get(symbol)
            if not past or st["bars"] < 10 or not st["open"]:
                continue
            price = st["ltp"]
            if not price or price < MIN_PRICE_RS:
                continue
            turnover_cr = st["vol"] * price / 1e7
            if turnover_cr < MIN_TURNOVER_CR_BY_0930:
                continue
            prev = past["prev_close"]
            span = st["high"] - st["low"]
            expected = (past["avg_vol"] or 0) * (15.0 / 375.0)
            card = cards.get(symbol) or {}
            got = _outcome(con, day, symbol, price)
            if got is None:
                continue
            dataset.append({
                "day": day, "symbol": symbol, "price": price,
                "gap_pct": (st["open"] - prev) / prev * 100.0 if prev else None,
                "move_pct": (price - st["open"]) / st["open"] * 100.0,
                "range15_pct": span / st["open"] * 100.0,
                "pos_in_range": (price - st["low"]) / span if span > 0 else 0.5,
                "vol_ratio": st["vol"] / expected if expected > 0 else None,
                "turnover_cr": turnover_cr,
                "runup_5d": past["runup_5d"],
                "own_range_pct": past["range_pct"],
                "cards": card.get("cards", 0),
                "grade": card.get("grade", ""),
                "kind": card.get("kind", ""),
                "R": got,
            })
        print(f"  {day}  {len(snap):>5} symbols seen  "
              f"{sum(1 for r in dataset if r['day'] == day):>5} scored")
    con.close()
    return dataset


if __name__ == "__main__":
    import json
    rows = build(sys.argv[1:] or None)
    out = os.path.join("data", "pick_study.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)
    wins = sum(1 for r in rows if r["R"] > 0)
    print(f"\n  {len(rows)} stock-days  {wins} positive "
          f"({wins / max(len(rows), 1) * 100:.0f}%)  -> {out}")
