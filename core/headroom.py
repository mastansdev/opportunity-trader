"""
==========================================================
How far can this stock still go today?
==========================================================

    "for that calculations bot needs to know the Upper & lower circuit
     of the stock. gapup on the day compared?"
                                -- operator, 8 August 2026

WHY THIS EXISTS
---------------
core/position_plan.py sets the target at twice the stop distance. So a
wide stop produces a distant target, and nothing else is consulted:

    TATAINVEST  7 Aug   entry 706.50
                        stop  669.20   -5.3%   (the day's low)
                        target 781.10  +10.6%  (2 x the stop)

                        it moved Rs 4. The target was Rs 74.60 away.

Across 30 replayed trades and two completely different selectors, ZERO
targets were ever reached. The number was unreachable by construction,
so every winner drifted sideways until the trail or the close took it
out small, while every loser hit its stop cleanly.

That is "lose small, never win big" -- the exact inversion of the rule
he has repeated since the beginning.

WHAT HE POINTED AT
------------------
The exchange already publishes the answer. Every NSE stock trades
inside a daily price band, and once the band is reached the stock is
frozen -- there is no price beyond it, however good the news:

    band     stocks
    20%       1,933
    10%         164
    5%          110
    2%            1
    No Band     208     (mostly F&O names)

A stock in a 5% band that has already gapped 3% has TWO PERCENT of
headroom left, by exchange rule. A 10% target there is not unlikely.
It is impossible.

And the gap matters as much as the band. The ceiling is measured from
YESTERDAY'S CLOSE, not from today's open -- so a stock that gapped up
4% has already spent that much of its allowance before the session
began.

WHAT THIS DOES
--------------
    ceiling   = previous close x (1 + band%)
    headroom  = ceiling - price now

Nothing more. It does not decide the target; it says what the target
cannot exceed, and how much of the day's allowance is already gone.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import glob
import os

BAND_GLOB = os.path.join("data", "sec_list_*.csv")

# What NSE calls a stock with no daily band -- F&O names, which move
# on their own limits rather than a fixed percentage.
NO_BAND = "NO BAND"

# A stock this close to its ceiling has nowhere left to go today, and
# a position opened here can only be stopped out or frozen.
NEARLY_FROZEN_PCT = 1.0

_bands = {}


def _load():
    """{symbol: band_pct or None} from NSE's own securities list."""
    if _bands:
        return _bands
    files = sorted(glob.glob(BAND_GLOB))
    if not files:
        return _bands
    try:
        with open(files[-1], newline="", encoding="utf-8",
                  errors="ignore") as handle:
            for row in csv.DictReader(handle):
                if (row.get("Series") or "").strip().upper() != "EQ":
                    continue
                symbol = (row.get("Symbol") or "").strip().upper()
                raw = (row.get("Band") or "").strip()
                if not symbol:
                    continue
                if raw.upper().replace(" ", "") in ("NOBAND", ""):
                    _bands[symbol] = None
                    continue
                try:
                    _bands[symbol] = float(raw)
                except ValueError:
                    _bands[symbol] = None
    except Exception:                                      # noqa: BLE001
        pass
    return _bands


def band_of(symbol):
    """The daily band percentage, or None for an unbanded stock."""
    return _load().get(str(symbol or "").upper())


def of(symbol, price, prev_close, day_open=None):
    """How much room is left above, and how much has been spent.

    Returns {"ok", "band_pct", "ceiling", "floor", "headroom_pct",
             "gap_pct", "spent_pct", "why"}.

    ok is False when we cannot say -- no band on file, or no previous
    close. That is a "cannot say", never a "no room": refusing a trade
    on missing data is how a whole universe quietly disappears.
    """
    symbol = str(symbol or "").upper()
    band = band_of(symbol)
    try:
        price = float(price or 0) or None
        prev_close = float(prev_close or 0) or None
    except (TypeError, ValueError):
        price = prev_close = None

    if band is None or not prev_close or not price:
        return {"ok": False, "band_pct": band,
                "why": ("no daily band on file -- F&O or unlisted"
                        if band is None else "no previous close")}

    ceiling = prev_close * (1.0 + band / 100.0)
    floor = prev_close * (1.0 - band / 100.0)
    headroom_pct = (ceiling - price) / price * 100.0

    gap_pct = None
    if day_open:
        try:
            gap_pct = (float(day_open) - prev_close) / prev_close * 100.0
        except (TypeError, ValueError):
            gap_pct = None

    # How much of today's allowance is already used up.
    spent_pct = (price - prev_close) / prev_close * 100.0

    if headroom_pct <= NEARLY_FROZEN_PCT:
        why = (f"only {headroom_pct:.1f}% below its {band:.0f}% upper "
               f"circuit -- nowhere left to go today")
    else:
        why = (f"{headroom_pct:.1f}% of room left under a {band:.0f}% "
               f"band ({spent_pct:+.1f}% of it already used)")

    return {"ok": True, "band_pct": band, "ceiling": round(ceiling, 2),
            "floor": round(floor, 2),
            "headroom_pct": round(headroom_pct, 2),
            "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
            "spent_pct": round(spent_pct, 2),
            "frozen_soon": headroom_pct <= NEARLY_FROZEN_PCT,
            "why": why}


def cap_target(symbol, target, price, prev_close):
    """The highest target this stock can actually reach today.

    Returns (capped_target, why). A target beyond the circuit is not
    ambitious, it is arithmetic that cannot happen -- and it is the
    reason no target has ever been hit.
    """
    got = of(symbol, price, prev_close)
    if not got.get("ok") or not target:
        return target, None
    ceiling = got["ceiling"]
    if target <= ceiling:
        return target, None
    return ceiling, (f"target {target:.2f} is above the {got['band_pct']:.0f}% "
                     f"upper circuit at {ceiling:.2f} -- capped there")
