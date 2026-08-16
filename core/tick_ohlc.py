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

# The rest of what a Quote packet carries. Kept separate from
# _LIVE_KEYS because those four are PRICES and must be > 0 to mean
# anything, while a book side of 0 is a real reading -- nothing bid.
# See pressure() and the note inside remember().
_BOOK_KEYS = ("total_buy_quantity", "total_sell_quantity", "avg_price",
              "LTQ", "LTP")

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

        # ---- THE ORDER BOOK, ARRIVING FREE AND READ BY NOTHING ----
        #
        # 16 August 2026, from the feed audit. main.py has printed this
        # at startup every session since 30 July:
        #
        #   [FEED] Arriving but UNUSED: ['LTQ', 'avg_price', 'close',
        #          'high', 'low', 'open', 'total_buy_quantity',
        #          'total_sell_quantity']
        #
        # OHLC came off that list on 10 August. These three are still
        # on it, and a grep confirms it: the only mention of
        # total_buy_quantity anywhere outside a test is the docstring
        # above, quoting the log line.
        #
        # They matter because his own definition of an opportunity
        # asks for something price cannot show:
        #
        #     "Volume confirms it -- money changing hands above this
        #      stock's own normal for this time of day"
        #
        # total_buy_quantity and total_sell_quantity are the aggregate
        # depth standing on each side. avg_price is the day's ATP, so
        # LTP above it means the last trades printed above where the
        # day's money actually changed hands.
        #
        # REMEMBERED, NOT ACTED ON -- exactly like the OHLC above, and
        # for the same stated reason: "i'd rather show you the real
        # size of the drift before rewriting the tick path". Nothing
        # here may reach an entry; tests/test_tick_pressure.py fails
        # the build if it does.
        for key in _BOOK_KEYS:
            got = _num(message.get(key))
            if got is not None and got >= 0:
                row[key] = got

        row["at"] = datetime.now()
        _latest[str(symbol).upper()] = row
        return row
    except Exception:                                          # noqa: BLE001
        return None


def pressure(symbol):
    """Which side of the book is heavier, and by how much.

    {"buy", "sell", "ratio", "skew_pct", "atp", "above_atp"} or None.

    ratio    total_buy / total_sell. Above 1 means more size is bid
             than offered. It is a SNAPSHOT of resting orders, not a
             record of what traded -- resting orders can be pulled.
    skew_pct (buy - sell) / (buy + sell) x 100. -100 .. +100, which is
             comparable across stocks in a way the raw ratio is not.
    above_atp  is the last price above the day's average traded price.

    None when the packet did not carry the fields. None is not zero:
    a missing book and a balanced book are opposite readings.
    """
    row = _latest.get(str(symbol or "").upper())
    if not row:
        return None
    buy, sell = row.get("total_buy_quantity"), row.get("total_sell_quantity")
    if buy is None or sell is None or (buy + sell) <= 0:
        return None
    atp = row.get("avg_price")
    ltp = row.get("LTP")
    out = {
        "buy": buy,
        "sell": sell,
        "ratio": round(buy / sell, 3) if sell else None,
        "skew_pct": round((buy - sell) / (buy + sell) * 100.0, 1),
        "atp": atp,
        "above_atp": None if (atp is None or not ltp) else bool(ltp > atp),
    }
    return out


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
