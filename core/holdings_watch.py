"""Every position he holds at Dhan, and what the bot knows about it.

==========================================================
    "why i still manually tracking all? didn't i ask you to
     automate everything from tracking my open position to
     search new opportunity?"

    "bot trading - ON/OFF = ON > bot trades + track old positions ;
     OFF > Bot Observe the markets & alerts about opportunities +
     track old positions"
                            -- operator, 21 August 2026
==========================================================

TRACKING IS UNCONDITIONAL. TRADING IS THE ONLY THING THE SWITCH GATES.

That is his specification, in his own words, and it resolves a tension
that had left his account unwatched for two weeks.

WHY THE BOT WAS NOT ALLOWED NEAR THESE POSITIONS

7 August. Bot trading was OFF. He bought KALYANKJIL, AUROPHARMA and
HEROMOTOCO in the Dhan app himself. core/broker_sync.py adopted all
three, armed a trailing stop on each, and SOLD THEM OUT FROM UNDER HIM.

    "i stopped trading button of the bot still it traded ... if button
     is OFF it must not participate along with me, it only book keep
     my manual trades for learning purpose"

Four gates were built after that, and they are all correct:

    1. no broker read in PAPER      (fixed 21 Aug -- that one was a bug)
    2. positions held at STARTUP are never adopted
    3. adopt_with_stops is off by default
    4. adoption refuses entirely while bot trading is OFF

Every one of them stops the bot ACTING on his positions. Not one of
them was ever meant to stop it LOOKING at them, but together that is
what they did: nine real positions at Dhan, and a dashboard showing a
phantom NILKAMAL that had never been bought.

SO THIS READS AND REPORTS. IT HAS NO ORDER PATH.

    reads      -- his holdings, the events store, the sector map
    reports    -- price, P&L, a REFERENCE stop, what filed today
    places     -- nothing, in either switch position, in either mode

There is no call into adopt_positions here and no broker write of any
kind. The number printed beside a stock is a LEVEL, not a resting
order, and it comes from the same core/atr.py the entry stop uses, so
the two can never disagree about what this stock's own range is.

WHAT IT DELIBERATELY WILL NOT DO

It will not say "sell this". The doctrine on holdings was settled on
29 July and MEASURED against 19 filings that day: reporting beats
acting, and on results a stop is MORE useful, not less. He gets the
evidence in one place instead of nine browser tabs, and the decision
stays his.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import warn

# The same bounds the entry stop is sized with, so "reference stop"
# here and "stop" on a bot position mean the same thing.
try:
    from core.rules import MIN_STOP_DISTANCE_PCT, MAX_STOP_DISTANCE_PCT
except Exception:                                           # noqa: BLE001
    MIN_STOP_DISTANCE_PCT, MAX_STOP_DISTANCE_PCT = 0.75, 6.0

try:
    from config import DAILY_ATR_STOP_MULT
except Exception:                                           # noqa: BLE001
    DAILY_ATR_STOP_MULT = 1.2

FALLBACK_STOP_PCT = 2.5


def _num(value, default=0.0):
    try:
        got = float(value)
    except (TypeError, ValueError):
        return default
    return default if got != got else got          # NaN -> default


def _reference_stop_pct(symbol):
    """This stock's own daily range, bounded. Never raises."""
    try:
        from core.atr import scaled_stop_pct
        got = scaled_stop_pct(symbol, DAILY_ATR_STOP_MULT,
                              MIN_STOP_DISTANCE_PCT,
                              MAX_STOP_DISTANCE_PCT,
                              FALLBACK_STOP_PCT)
        return _num(got, FALLBACK_STOP_PCT)
    except Exception:                                       # noqa: BLE001
        return FALLBACK_STOP_PCT


def _event_for(symbol, on_date=None):
    """What this stock filed, from the PRO channels. None if nothing.

    Reads the SAME store the alert card quotes, so a holding line and
    an opportunity line can never tell him different things about the
    same stock on the same morning.
    """
    try:
        from core.why_moving import _events_for, from_events
        rows = _events_for(symbol)
        if not rows:
            return None
        got = from_events(rows, on_date=on_date)
        if not got:
            return None
        # from_events returns {text, weight, direction, source}.
        # The first version of this str()'d the whole dict onto his
        # phone -- "FILED: {'text': 'BEAT Revenue...", braces and all.
        # DIRECTION is the half that matters and it was being thrown
        # away: a filing the channel graded NEGATIVE on a position he
        # is already down on is the whole reason he asked for this.
        if isinstance(got, dict):
            return {"text": str(got.get("text") or "").strip(),
                    "direction": str(got.get("direction") or "").upper(),
                    "source": str(got.get("source") or "")}
        return {"text": str(got).strip(), "direction": "", "source": ""}
    except Exception:                                       # noqa: BLE001
        return None


def _sector_note(symbol, moves):
    if not moves:
        return None
    try:
        from core.sector_map import co_move_reason
        return co_move_reason(symbol, moves)
    except Exception:                                       # noqa: BLE001
        return None


def _day_move_pct(symbol, ltp):
    """How far it has moved TODAY, against yesterday's close.

    P&L against his average tells him where the position stands.
    It does not tell him whether something is happening RIGHT NOW,
    which is the difference between a stock that is quietly down 6%
    and one that is down 6% because it fell 5% this morning.
    """
    if not ltp:
        return None
    try:
        import sqlite3
        from core.atr import DAILY_DB
        con = sqlite3.connect(f"file:{DAILY_DB}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT close FROM daily_bars WHERE symbol=? "
                "ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
        finally:
            con.close()
        if not row or not row[0]:
            return None
        return round((ltp - float(row[0])) / float(row[0]) * 100.0, 2)
    except Exception:                                       # noqa: BLE001
        return None


def row_for(holding, on_date=None, moves=None):
    """One holding -> one plain dict. Never raises on a bad row."""
    symbol = str(holding.get("tradingSymbol")
                 or holding.get("symbol") or "").upper().strip()
    qty = _num(holding.get("totalQty") or holding.get("qty"))
    avg = _num(holding.get("avgCostPrice") or holding.get("avg_price"))
    ltp = _num(holding.get("lastTradedPrice") or holding.get("ltp"))

    pnl_rs = (ltp - avg) * qty if (avg and ltp) else 0.0
    pnl_pct = ((ltp - avg) / avg * 100.0) if avg else 0.0

    stop_pct = _reference_stop_pct(symbol)
    ref_stop = avg * (1.0 - stop_pct / 100.0) if avg else 0.0
    below = bool(ltp and ref_stop and ltp < ref_stop)

    event = _event_for(symbol, on_date=on_date)
    sector = _sector_note(symbol, moves)

    # FACTS AND RULE OUTPUTS ONLY -- never a verdict. See the module
    # docstring: on holdings the bot reports and he decides.
    flags = []
    if below:
        flags.append("BELOW REFERENCE STOP")
    if event:
        way = (event or {}).get("direction") or ""
        flags.append(f"FILED TODAY ({way})" if way else "FILED TODAY")
    if sector:
        flags.append("SECTOR MOVING")
    if not flags:
        flags.append("IN PROFIT" if pnl_pct > 0 else "QUIET")

    return {
        "symbol": symbol,
        "qty": int(qty),
        "avg": round(avg, 2),
        "ltp": round(ltp, 2),
        "pnl_rs": round(pnl_rs, 0),
        "pnl_pct": round(pnl_pct, 2),
        "mtf": bool(_num(holding.get("mtf_qty"))),
        "ref_stop": round(ref_stop, 2),
        "ref_stop_pct": round(stop_pct, 2),
        "below_stop": below,
        "day_pct": _day_move_pct(symbol, ltp),
        "event": event,
        "sector": sector,
        "flags": flags,
    }


def watch(holdings, on_date=None, moves=None):
    """Every holding, worst first.

    `holdings` of None means the question could not be asked, and that
    is NOT the same as holding nothing -- merging those two is how a
    network blip turns into "your positions vanished".

    Worst first because the one needing a decision is the one that has
    moved against him, and a list he has to scan is a list he stops
    reading.
    """
    if holdings is None:
        warn("[HOLDINGS] Dhan did not answer -- nothing to report. "
             "This is not 'you hold nothing'.")
        return []
    rows = []
    for holding in holdings:
        try:
            got = row_for(holding or {}, on_date=on_date, moves=moves)
        except Exception as exc:                            # noqa: BLE001
            warn(f"[HOLDINGS] Could not read one row: {exc}")
            continue
        if got["symbol"]:
            rows.append(got)
    rows.sort(key=lambda r: (not r["below_stop"], r["pnl_pct"]))
    return rows


def digest(rows, max_rows=12):
    """The message he reads on his phone.

    Deliberately not a table -- he asked for those to stop. One block
    per stock, the number that matters first.
    """
    if not rows:
        return "HOLDINGS -- nothing to report."

    total = sum(r["pnl_rs"] for r in rows)
    invested = sum(r["avg"] * r["qty"] for r in rows)
    lines = [f"YOUR {len(rows)} HOLDINGS AT DHAN",
             f"Invested Rs {invested:,.0f}   P&L Rs {total:,.0f}", ""]

    for r in rows[:max_rows]:
        sign = "+" if r["pnl_pct"] >= 0 else ""
        mtf = "  MTF" if r["mtf"] else ""
        lines.append(f"{r['symbol']}  {r['qty']} @ {r['avg']:.2f}{mtf}")
        today = ("" if r.get("day_pct") is None
                 else f"   today {'+' if r['day_pct'] >= 0 else ''}"
                      f"{r['day_pct']:.2f}%")
        lines.append(f"  now {r['ltp']:.2f}  {sign}{r['pnl_pct']:.2f}%  "
                     f"Rs {r['pnl_rs']:,.0f}{today}")
        lines.append(f"  reference stop {r['ref_stop']:.2f} "
                     f"({r['ref_stop_pct']:.2f}% of your average)")
        if r["event"]:
            way = r["event"].get("direction") or ""
            said = r["event"].get("text") or ""
            lines.append(f"  FILED{' ' + way if way else ''}: {said[:160]}")
        if r["sector"]:
            lines.append(f"  SECTOR: {str(r['sector'])[:120]}")
        lines.append(f"  -> {', '.join(r['flags'])}")
        lines.append("")

    if len(rows) > max_rows:
        lines.append(f"... and {len(rows) - max_rows} more.")
    lines.append("The bot placed nothing. These are levels, not orders.")
    return "\n".join(lines)


# ---------------------------------------------------------------
# THE AUTOMATIC HALF
# ---------------------------------------------------------------

# What is worth interrupting him for. "IN PROFIT" and "QUIET" are
# states, not events -- announcing those would train him to swipe the
# notification away, and then the one that mattered goes with it.
ANNOUNCE = ("BELOW REFERENCE STOP", "FILED TODAY", "SECTOR MOVING")


class HoldingsMonitor:
    """Watches his Dhan account across a session and speaks on CHANGE.

    ---- WHY THIS IS NOT JUST digest() ON A TIMER ----

    A digest every heartbeat is 300 identical messages a day, which is
    the same as no messages. The thing worth telling him is the moment
    a position CROSSES a line -- through its reference stop, or into a
    filing -- and each crossing is worth saying exactly once.

    Deliberately consults nothing about the switch or the trading
    mode. His specification, 21 August:

        "ON > bot trades + track old positions ;
         OFF > Bot Observe ... + track old positions"

    Tracking is unconditional. This places nothing in either state.
    """

    def __init__(self):
        self._seen = {}          # symbol -> flags already announced
        self._opened = False     # has the session digest gone out?

    def sweep(self, holdings, on_date=None, moves=None):
        """One pass. Returns (rows, [messages]) -- never raises.

        The first successful sweep of a session returns the full
        digest, so he starts the day knowing where he stands. After
        that only crossings speak.
        """
        try:
            rows = watch(holdings, on_date=on_date, moves=moves)
        except Exception as exc:                            # noqa: BLE001
            warn(f"[HOLDINGS] Sweep failed: {exc}")
            return [], []
        if not rows:
            return [], []

        messages = []
        if not self._opened:
            self._opened = True
            self._seen = {r["symbol"]: set(r["flags"]) for r in rows}
            return rows, [digest(rows)]

        for row in rows:
            symbol = row["symbol"]
            before = self._seen.get(symbol, set())
            now = set(row["flags"])
            fresh = [f for f in ANNOUNCE if f in now and f not in before]
            self._seen[symbol] = now
            if not fresh:
                continue
            messages.append(self._one(row, fresh))
        return rows, messages

    @staticmethod
    def _one(row, fresh):
        """One crossing, as he reads it on the phone. Plain text."""
        sign = "+" if row["pnl_pct"] >= 0 else ""
        lines = [f"HOLDING: {row['symbol']}  {', '.join(fresh)}",
                 f"{row['qty']} @ {row['avg']:.2f}"
                 f"{'  MTF' if row['mtf'] else ''}",
                 f"now {row['ltp']:.2f}  {sign}{row['pnl_pct']:.2f}%  "
                 f"Rs {row['pnl_rs']:,.0f}"
                 + ("" if row.get("day_pct") is None
                    else f"   today {'+' if row['day_pct'] >= 0 else ''}"
                         f"{row['day_pct']:.2f}%"),
                 f"reference stop {row['ref_stop']:.2f}"]
        if row["event"]:
            way = row["event"].get("direction") or ""
            said = row["event"].get("text") or ""
            lines.append(f"FILED{' ' + way if way else ''}: {said[:160]}")
        if row["sector"]:
            lines.append(f"SECTOR: {str(row['sector'])[:120]}")
        lines.append("The bot placed nothing. This is yours to decide.")
        return "\n".join(lines)
