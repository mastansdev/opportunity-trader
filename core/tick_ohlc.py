"""
==========================================================
The exchange's own OHLC, arriving on every tick, unused
==========================================================

    "i want our bot must work aligned with NSE website in calculating
     gap , down, %'s."
                                -- operator, 10 August 2026

WHAT THE FEED ACTUALLY SENDS
----------------------------
main.py printed this on 10 August, at startup, every session:

    [FEED] Arriving but UNUSED: ['LTQ', 'avg_price', 'close', 'high',
           'low', 'open', 'total_buy_quantity', 'total_sell_quantity']
           sample: {'close': '576.90', 'high': '592.00',
                    'low': '566.65', 'open': '580.00'}

`close` in a live Dhan Quote packet is the PREVIOUS CLOSE -- the exact
denominator NSE uses for percentage change. It arrives on every tick,
for all 1,223 stocks, at no cost, and the bot discarded it.

Instead core/circuit_monitor.py polls REST for the same four numbers.
Two sources for one fact, refreshed on different clocks. The formula
was never wrong -- verified 10 August against NSE's own bhavcopy,
2,416 EQ symbols, zero mismatches on close, previous close, open and
volume -- but the LIVE side ran on the slower of the two.

WHAT THIS DOES, AND DELIBERATELY DOES NOT DO
--------------------------------------------
It keeps the tick's own OHLC per symbol, and it MEASURES the two
sources against each other. It does not replace anything yet.

    "i'd rather show you the real size of the drift before rewriting
     the tick path"

If the two agree to the paisa, swapping them is a refactor with no
payoff on the hottest path in the bot. If they drift, this says by how
much, on which stocks, and at what time of day -- and then the change
is justified by a number rather than by my opinion.

Nothing here can affect a trade. It records and reports.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

# A packet whose fields are all zero is the pre-open shape -- Dhan
# sends the previous close and nothing else until the first trade.
# Those are not disagreements, they are silence.
_LIVE_KEYS = ("open", "high", "low", "close")

# Below this the two are the same number to any decision the bot makes.
# One paisa on a Rs 500 stock is 0.002%.
AGREE_PAISA = 0.05

_latest = {}
_drift = []
_MAX_DRIFT_ROWS = 4000


def _num(value):
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return None if got != got else got


def remember(symbol, message):
    """Keep the exchange's own OHLC off one Quote packet. Never raises.

    `close` is the PREVIOUS day's close -- during the session today's
    close obviously is not known. Same meaning circuit_monitor gives
    the field it reads from REST.
    """
    try:
        row = {}
        for key in _LIVE_KEYS:
            got = _num(message.get(key))
            if got is not None and got > 0:
                row[key] = got
        if not row:
            return None                       # pre-open: nothing traded
        row["at"] = datetime.now()
        _latest[str(symbol).upper()] = row
        return row
    except Exception:                                          # noqa: BLE001
        return None


def of(symbol):
    """{"open","high","low","close","at"} from the tick, or None."""
    return _latest.get(str(symbol or "").upper())


def prev_close(symbol):
    """The exchange's own previous close, straight off the tick."""
    row = of(symbol)
    return row.get("close") if row else None


def compare(symbol, rest_row):
    """Measure the tick against what REST said. Returns the differences.

    `rest_row` is circuit_monitor's snapshot row: prev_close, open,
    high, low. Anything missing on either side is skipped rather than
    counted as a disagreement -- an unasked question is not a failure.
    """
    tick = of(symbol)
    if not tick or not rest_row:
        return None
    pairs = (("close", "prev_close"), ("open", "open"),
             ("high", "high"), ("low", "low"))
    out = {}
    for mine, theirs in pairs:
        a = _num(tick.get(mine))
        b = _num(rest_row.get(theirs))
        if a is None or b is None or a <= 0 or b <= 0:
            continue
        gap = abs(a - b)
        if gap > AGREE_PAISA:
            out[mine] = {"tick": a, "rest": b, "gap": round(gap, 2),
                         "gap_pct": round(gap / b * 100.0, 3)}
    if out and len(_drift) < _MAX_DRIFT_ROWS:
        _drift.append({"symbol": str(symbol).upper(),
                       "at": datetime.now().strftime("%H:%M:%S"),
                       "fields": out})
    return out or None


def report():
    """What disagreed today, worst first. Read after the close."""
    if not _drift:
        return {"rows": 0, "symbols": 0, "worst": [],
                "note": "the tick and the REST snapshot never disagreed "
                        "by more than 5 paise"}
    worst = sorted(
        _drift,
        key=lambda r: -max(f["gap_pct"] for f in r["fields"].values()))[:12]
    return {"rows": len(_drift),
            "symbols": len({r["symbol"] for r in _drift}),
            "worst": worst,
            "note": "the live path runs on the REST snapshot; these are "
                    "the moments it differed from the exchange's own "
                    "numbers arriving on the tick"}


def reset():
    _latest.clear()
    _drift.clear()
