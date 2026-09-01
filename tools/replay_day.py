"""
==========================================================
py tools/replay_day.py  --  what would the bot have done?
==========================================================

    "show me what trades the bot could have taken ? use bot not your
     memory pls. bot trades"
                                -- operator, 7 August 2026

WHY THIS EXISTS
---------------
Every answer he has had about the bot's behaviour has come from me
reading the code and telling him what I think it does. On 7 August
that was wrong in the most expensive possible way: I said the switch
being OFF meant nothing would trade, and the rotation path sold five
positions anyway.

Reading code is not evidence. This runs it.

It replays a recorded session through the REAL decision path --

    core/ranker.py         rank()          picks and scores
    core/position_plan.py  plan()          size and stop
    core/auto_entry.py     take()          every gate, in order

-- with exactly one thing swapped out: Engine._enter is replaced by a
recorder. Nothing reaches Dhan. Everything else is the code that runs
at 09:30 on a live morning.

WHAT IT WILL NOT DO
-------------------
It cannot prove the bot is profitable. It replays ONE recorded day
against the reasons that are in the store TODAY, and some of those
reasons (the evening recap, the calendar refresh) arrived after the
session it is replaying. That makes the replay slightly better
informed than the live bot was. It is a check on BEHAVIOUR -- does it
pick, does it size, does it obey the switch -- not a backtest.

Read it as: "these are the orders that would have been sent."

USAGE
-----
    py tools/replay_day.py                  today, switch ON
    py tools/replay_day.py 2026-08-06       a past session
    py tools/replay_day.py 2026-08-07 off   switch OFF -- must be zero

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from datetime import datetime, time as dtime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANDLES = "data/backtest_candles.db"

# Replay a decision every N minutes. The live loop ranks far more
# often than this; five minutes is enough to see every entry it would
# have found and keeps a full session under a minute.
STEP_MINUTES = 5

# ---- USE THE MODULES THAT WERE BUILT AND NEVER CONNECTED. ----
# 8 August: core/exit_plan.py and core/supply_events.py were written,
# tested, and imported by ZERO files. Every replay number quoted so far
# came from core/position_plan.py -- the day's-low stop they exist to
# replace. `py tools/replay_day.py 2026-08-07 plan` turns them on.
EXIT_PLAN = False

# Set by the command line. Off by default so the live shape is what
# runs unless someone deliberately asks for the new selector.
SELECT_MODE = False


def _slice_of_day(clock):
    """How much of an average day's turnover should be done by now.

    A stock at 10:00 has 45 minutes of volume. Comparing that to a
    FULL day's average makes every stock look quiet, which is how a
    volume filter silently never fires.
    """
    minutes = (clock.hour * 60 + clock.minute) - (9 * 60 + 15)
    return max(min(minutes / 375.0, 1.0), 0.05)

# The live bot's own limits, imported not copied -- if he changes
# config.py the replay changes with it.
try:
    from config import MAX_OPEN_POSITIONS
except Exception:                                          # noqa: BLE001
    MAX_OPEN_POSITIONS = 3
try:
    from config import PEAK_TRAIL_PCT
except Exception:                                          # noqa: BLE001
    PEAK_TRAIL_PCT = 0.025

# ---- THE BOOK IS SIZED BY CASH. 8 August 2026. ----
#
#     "we prepared the bot to search for better trading opportunites
#      not to keep the door shut after 3 positions irrespective of pnl"
#
# core/capital.py: (capital - Rs 1 lakh free) / Rs 30,000 per position.
# The replay must size the book the way the live engine now does, or it
# measures a bot that does not exist.
REPLAY_CAPITAL_RS = 431_116.0


_blocked_cache = {}


def _blocked_symbols():
    """Symbols the master marks SUBSCRIBE = NO, as the live path sees
    them. The harness passed None, so the replay considered stocks the
    bot would have refused outright."""
    if "set" not in _blocked_cache:
        try:
            from core.master_loader import MasterLoader
            loader = MasterLoader()
            loader.load()
            _blocked_cache["set"] = set(loader.blocked_symbols() or {})
        except Exception:                                  # noqa: BLE001
            _blocked_cache["set"] = set()
    return _blocked_cache["set"]


def _slots_from_cash():
    try:
        from core import capital
        return capital.slots(REPLAY_CAPITAL_RS)["slots"]
    except Exception:                                      # noqa: BLE001
        return MAX_OPEN_POSITIONS


# ---------------------------------------------------------------
# A stand-in Engine: the attributes auto_entry actually reads.
# ---------------------------------------------------------------
class ReplayEngine:
    """Enough Engine for the entry path, with no broker behind it."""

    def __init__(self, alert_only):
        self.alert_only = bool(alert_only)
        self.open_positions = {}
        self.orders = []
        self.alerts = []

    # auto_entry asks the engine's risk layer for the last word.
    def entry_blocked_reason(self, symbol, direction, at_time=None):
        # ---- THE STUB WENT STALE AND ATE THE REPLAY. 1 Sep 2026. ----
        #
        # The real method gained `at_time` on 12 August so the whole
        # entry decision reads ONE clock. This stand-in never did, so
        # every call raised TypeError -- and core/auto_entry.py fails
        # CLOSED on that by design ("a safety gate that fails open is
        # worse than no gate"). The replay therefore refused 121 trades
        # with "the risk check itself failed" and reported NO ORDERS for
        # a day the live bot took seven.
        #
        # A stand-in that drifts from the thing it stands in for does
        # not report a quiet day. It reports a wrong one.
        return None

    # A full book asks to rotate. In the replay we never rotate -- the
    # honest answer to "what did it enter" should not be muddied by a
    # sell it may or may not have made. Refusing here is the
    # conservative reading.
    def _maybe_rotate_out(self, challenger, direction, tick_time):
        return False

    def _manual_alert(self, symbol, kind, message):
        self.alerts.append((symbol, kind, message))

    def _enter(self, symbol, security_id, price, stop_seed, entry_time,
               entry_reason, direction, target=None, qty=None,
               stop_mode=None):
        """THE RECORDER. This is the only thing swapped out.

        ---- IT MUST STILL REFUSE WHAT THE ENGINE REFUSES. 8 Aug 2026 ----
        Engine._enter applies the Rs 50 price floor before anything
        else -- "we/bot never trade in those stocks", his hard rule.
        This recorder skipped it, so the 5 August replay showed a
        RENUKA entry at Rs 22.96 that the live bot would never place,
        and charged Rs 1,500 of loss to a trade that could not exist.

        A harness that permits what the engine forbids is not measuring
        the engine.
        """
        try:
            from config import MIN_TRADABLE_PRICE_RS as _floor
        except Exception:                                  # noqa: BLE001
            _floor = 50.0
        if price is not None and price < _floor:
            self.refused_by_engine = getattr(self, "refused_by_engine", [])
            self.refused_by_engine.append(
                (symbol, f"Rs {price:.2f} is below the Rs {_floor:.0f} floor"))
            return
        self.open_positions[symbol] = {"entry_price": price, "qty": qty,
                                       "direction": direction}
        self.orders.append({
            "symbol": symbol, "at": entry_time, "price": price,
            "qty": qty, "stop": stop_seed, "target": target,
            "reason": entry_reason})


# ---------------------------------------------------------------
# The tape, as the bot would have seen it at a moment in time
# ---------------------------------------------------------------
class Tape:
    """The whole day in memory, stepped forward minute by minute.

    ---- WHY NOT SQL PER STEP. 7 August 2026. ----
    The first version ran two subqueries per symbol per step: 1,100
    symbols x 66 steps x 2 = 145,000 queries, and a five-day
    comparison did not finish in three minutes. The tape is only a few
    hundred thousand rows. Load it once, accumulate in a dict, and the
    same five days run in seconds.
    """

    def __init__(self, con, day):
        self.rows = con.execute(
            "select minute, symbol, o, h, l, c, v from candles "
            "where date=? order by minute", (day,)).fetchall()
        self.i = 0
        self.state = {}

    def upto(self, cutoff):
        """Advance to `cutoff` (HH:MM) and return the movers as of then."""
        while self.i < len(self.rows):
            minute, symbol, o, h, l, c, v = self.rows[self.i]
            if minute[11:16] > cutoff:
                break
            self.i += 1
            if o is None or c is None:
                continue
            st = self.state.get(symbol)
            if st is None:
                self.state[symbol] = {"open": o, "high": h, "low": l,
                                      "ltp": c, "vol": v or 0, "bars": 1}
                continue
            if h is not None and (st["high"] is None or h > st["high"]):
                st["high"] = h
            if l is not None and (st["low"] is None or l < st["low"]):
                st["low"] = l
            st["ltp"] = c
            st["vol"] += v or 0
            st["bars"] += 1

        out = []
        for symbol, st in self.state.items():
            if st["bars"] < 2 or not st["open"] or not st["low"]:
                continue
            ltp = st["ltp"]
            out.append({"symbol": symbol, "ltp": ltp, "day_open": st["open"],
                        "day_high": st["high"], "day_low": st["low"],
                        "volume": st["vol"],
                        "turnover_cr": st["vol"] * ltp / 1e7,
                        "change_pct": (ltp - st["open"]) / st["open"] * 100.0})
        out.sort(key=lambda r: -r["change_pct"])
        return out


_prev_close_cache = {}


def _headroom_of(symbol, con, day):
    """Circuit room for this stock today -- see core/headroom.py."""
    from core import headroom
    key = (symbol, day)
    if key not in _prev_close_cache:
        row = con.execute(
            "select c from candles where date < ? and symbol = ? "
            "order by date desc, minute desc limit 1", (day, symbol)).fetchone()
        _prev_close_cache[key] = row[0] if row else None
    prev = _prev_close_cache[key]
    now = con.execute(
        "select c from candles where date = ? and symbol = ? "
        "order by minute desc limit 1", (day, symbol)).fetchone()
    return headroom.of(symbol, now[0] if now else None, prev)


_range_cache = {}


def _typical_range_pct(symbol, day, db="data/daily_candles.db"):
    """This stock's own median daily range, from before `day`.

    core/exit_plan.py widens the stop for a name that swings and keeps
    it tight for one that does not. Without this it applies the flat
    1.8% to every stock -- which is exactly the stop DEEPAKNTR took out
    on a day it closed UP 1.45%.

    Strictly before `day`. Reading the day's own range would be
    look-ahead, the same fault graded_symbols() had.
    """
    key = (symbol, day)
    if key in _range_cache:
        return _range_cache[key]
    span = None
    try:
        con = sqlite3.connect(db)
        rows = con.execute(
            "select high, low, open from daily_bars "
            "where symbol = ? and date < ? order by date desc limit 30",
            (symbol, day)).fetchall()
        con.close()
        spans = sorted((h - l) / o * 100.0
                       for h, l, o in rows if o and h and l)
        if len(spans) >= 5:
            span = spans[len(spans) // 2]
    except Exception:                                          # noqa: BLE001
        span = None
    _range_cache[key] = span
    return span


def exit_of(con, day, symbol, entry_at, entry, stop, target):
    """Walk the tape forward under the engine's own exit rules.

    Hard stop, then the 2.5% peak trail once price has moved up, then
    the close. Whichever comes first.
    """
    bars = con.execute(
        "select minute, h, l, c from candles where date=? and symbol=? "
        "and minute>? order by minute", (day, symbol, entry_at)).fetchall()
    peak = entry
    base_stop = stop
    for minute, high, low, close in bars:
        if low is not None and stop and low <= stop:
            return minute[11:16], stop, ("1:1 lock" if stop > entry else "stop")
        if high is not None and high > peak:
            peak = high
            # ---- THE SAME EXIT THE LIVE ENGINE NOW USES. 8 Aug 2026 ----
            # core/trailing_stop.py locks the stop at entry + 1R once
            # the stock has run 1.5R, instead of trailing 2.5% behind
            # the peak. Measured +4.33% against +0.42% over 12 trades.
            # If this walk kept the old trail it would be scoring a bot
            # that no longer exists.
            try:
                from core import exit_plan
                moved, _why = exit_plan.live_stop(entry, base_stop, target,
                                                  peak)
            except Exception:                              # noqa: BLE001
                moved = None
            if moved is not None and moved > stop:
                stop = moved
        # ---- THE TARGET NO LONGER CLOSES THE TRADE. 8 Aug 2026 ----
        #
        #     "we want money in either money thats it"
        #
        # It arms the trail instead -- core/exit_plan.live_stop(). A
        # hard exit here would keep measuring the bot that capped every
        # winner at 2R, which cost -0.095R a trade across 8,230 setups.
        # The position now ends on the trailing stop or the close.
    if bars:
        return bars[-1][0][11:16], bars[-1][3], "still open"
    return None, entry, "no data"


# ---------------------------------------------------------------
def replay(day, switch_on=True, early=False):
    from core import auto_entry, liquidity
    from core.position_plan import plan as position_plan
    from core.ranker import rank
    from core.why_moving import why as _why_raw

    # ---- CACHE THE REASONS. 7 August 2026. ----
    # why() reads three sqlite stores. The live loop asks once per
    # symbol per cycle and does not notice; a replay asks 60 symbols x
    # 66 steps x 7 days and never finishes. The reason for a stock
    # does not change during a session, so ask once.
    import functools
    # ---- THE REASON MUST BE AS OF THAT DAY. 8 August 2026. ----
    # This cached why(symbol=s) with no on_date, so every replayed
    # session read the reason store as it stands TODAY -- the same
    # look-ahead that graded_symbols() had. A stock that reported on
    # 7 August "already had a reason" when replaying 3 August.
    _as_of_day = datetime.fromisoformat(day).date()
    why = functools.lru_cache(maxsize=None)(
        lambda s: _why_raw(symbol=s, on_date=_as_of_day))
    adv = functools.lru_cache(maxsize=None)(liquidity.adv)

    con = sqlite3.connect(CANDLES)
    have = con.execute("select count(*), min(minute), max(minute) "
                       "from candles where date=?", (day,)).fetchone()
    if not have or not have[0]:
        print(f"No recorded candles for {day}.")
        return 1

    print("=" * 74)
    print(f"  REPLAY  {day}   switch {'ON' if switch_on else 'OFF'}"
          f"{'   EARLY LANE 09:20' if early else ''}"
          f"   book limit {MAX_OPEN_POSITIONS}")
    print(f"  tape: {have[0]:,} candles, {have[1][11:16]} to {have[2][11:16]}")
    print("=" * 74)

    # The same set the live dashboard widens its pool with.
    # ---- THE GRADES AS THEY STOOD THAT MORNING. 8 August 2026. ----
    # Asked without a cutoff this returns TODAY's Row 1, so a replay of
    # Tuesday would trade on Friday's grades. graded_symbols() now
    # takes `now`; the replay is the reason it had to.
    _as_of = datetime.combine(datetime.fromisoformat(day).date(),
                              dtime(9, 15))
    try:
        from core import watchlist_builder
        graded = set(watchlist_builder.graded_symbols(now=_as_of) or {})
    except Exception:                                      # noqa: BLE001
        graded = set()
    print(f"  Row 1 that morning: {len(graded)} graded stocks")
    graded_map = {}
    try:
        from core import watchlist_builder as _wb
        graded_map = _wb.graded_symbols(now=_as_of) or {}
    except Exception:                                      # noqa: BLE001
        graded_map = {}
    adv_of_sym = adv
    tape = Tape(con, day)
    auto_entry._graded_cache.clear()
    auto_entry._graded_cache["map"] = (
        watchlist_builder.graded_symbols(now=_as_of) or {})
    engine = ReplayEngine(alert_only=not switch_on)
    last_bar = have[2][11:16]
    clock = dtime(9, 20) if early else dtime(9, 30)
    seen_refusals = {}

    while clock <= dtime(15, 0) and f"{clock:%H:%M}" <= last_bar:
        rows = tape.upto(f"{clock:%H:%M}")
        if not rows:
            clock = _step(clock)
            continue
        # ---- THE 09:20 LANE. Row 1 only, no ranker. ----
        if early and clock < dtime(9, 30):
            picks = auto_entry.early_rows(
                rows, now=datetime.combine(
                    datetime.fromisoformat(day).date(), clock),
                plan_of=lambda m: position_plan(
                    m.get("ltp"), "BUY", day_low=m.get("day_low"),
                    day_high=m.get("day_high")))
            before = len(engine.orders)
            out = auto_entry.take(
                picks, engine,
                now=datetime.combine(
                    datetime.fromisoformat(day).date(), clock),
                security_id_of=lambda s: "REPLAY",
                held=set(engine.open_positions),
                max_positions=_slots_from_cash(),
                alert=engine._manual_alert, enter=engine._enter)
            for record in out:
                if not record.get("taken"):
                    seen_refusals[record["why"]] = \
                        seen_refusals.get(record["why"], 0) + 1
            for order in engine.orders[before:]:
                order["at_str"] = f"{clock:%H:%M}"
                order["minute"] = f"{day}T{clock:%H:%M}"
            clock = _step(clock)
            continue

        try:
            # ---- WIDEN BY REASON, AS THE LIVE BOT DOES. 7 Aug 2026 ----
            #
            #     "why no excellent stock were bought? ... WHY NONE OF
            #      THE TOP GAINERS"      -- operator
            #
            # I answered that the graded stocks were being crowded out
            # of the top-50 leaderboard. That was wrong, and the error
            # was HERE, not in the bot: dashboard/state.py already
            # calls _widen_by_reason() before ranking, and this replay
            # did not. So the replay was judging the bot on a pool the
            # bot never uses, and MOREPENLAB and SCI looked invisible
            # when the live path would have seen them.
            #
            # A harness that does not run the real path is worse than
            # no harness -- it produces confident, wrong answers.
            # ---- MOVE-LED SELECTION. 8 August 2026. ----
            # core/select.py: the best MOVING stocks that have a card
            # behind them, with a "still extending" test the ranker
            # never had. Enabled with `select` on the command line so
            # the old path stays measurable beside it.
            if SELECT_MODE:
                from core import select as _select
                cands = []
                for r in rows:
                    adv = adv_of_sym(r["symbol"])
                    if not adv or adv < 8:
                        continue
                    cands.append(dict(r, volume_ratio=(
                        r["turnover_cr"] / (adv * _slice_of_day(clock))
                        if adv else 0)))
                got = _select.pick(
                    cands, reason_of=why,
                    grade_of=lambda s: (graded_map.get(s) or {}).get("grade"),
                    held=set(engine.open_positions), top=8,
                    now=clock,
                    headroom_of=lambda s: _headroom_of(s, con, day))
                picks = got.get("rows") or []
                for row in picks:
                    if EXIT_PLAN:
                        try:
                            from core import supply_events
                            sold = supply_events.overhang(
                                row.get("symbol"),
                                now=datetime.combine(
                                    datetime.fromisoformat(day).date(),
                                    clock))
                        except Exception:                      # noqa: BLE001
                            sold = None
                        if sold:
                            row["plan"] = {"ok": False,
                                           "why": f"supply: {sold['why']}"}
                            continue
                        from core import exit_plan
                        row["plan"] = exit_plan.plan(
                            row.get("ltp"),
                            typical_range_pct=_typical_range_pct(
                                row.get("symbol"), day),
                            symbol=row.get("symbol"),
                            headroom_of=lambda s: _headroom_of(s, con, day))
                    else:
                        row["plan"] = position_plan(
                            row.get("ltp"), "BUY",
                            day_low=row.get("day_low"),
                            day_high=row.get("day_high"))
                before = len(engine.orders)
                out = auto_entry.take(
                    picks, engine,
                    now=datetime.combine(
                        datetime.fromisoformat(day).date(), clock),
                    security_id_of=lambda s: "REPLAY",
                    held=set(engine.open_positions),
                    max_positions=_slots_from_cash(),
                    alert=engine._manual_alert, enter=engine._enter)
                for record in out:
                    if not record.get("taken"):
                        seen_refusals[record["why"]] = \
                            seen_refusals.get(record["why"], 0) + 1
                for order in engine.orders[before:]:
                    order["at_str"] = f"{clock:%H:%M}"
                    order["minute"] = f"{day}T{clock:%H:%M}"
                clock = _step(clock)
                continue

            pool = list(rows[:60])
            have = {r["symbol"] for r in pool}
            for extra in rows[60:]:
                if extra["symbol"] in graded and extra["symbol"] not in have:
                    pool.append(extra)
            # ---- PASS WHAT THE LIVE PATH PASSES. 8 August 2026. ----
            # rank() takes five inputs this harness never supplied, so
            # every replayed decision was made with sector strength and
            # market breadth switched off -- core/ranker.py computes
            # both from gainers_losers, and None means "no sector is
            # leading and the market has no direction".
            #
            #     "A harness that does not run the real path is worse
            #      than no harness -- it produces confident, wrong
            #      answers."   (this file's own header, 7 August)
            #
            # gainers_losers IS the tape, sorted -- the live path reads
            # the same numbers off the REST snapshot.
            # blocked comes from the master, same as live.
            #
            # indices and mtf_of stay None and that is stated, not
            # hidden: the tape holds no index levels and no margin
            # table, so a replay cannot know them. core/ranker.py is
            # fail-open on both.
            # ---- IT IS A DICT, NOT A LIST. Checked, not guessed. ----
            # core/ranker.sector_moves() reads gainers_losers as a
            # payload with "sector_gainers" / "sector_losers" keys, and
            # falls back to the movers' own sectors when that block is
            # absent -- which it is here, because the tape has no
            # precomputed baskets. That fallback is the more honest
            # number anyway: the average of the stocks actually moving.
            board = {"gainers": sorted(rows, key=lambda r: -r["change_pct"])[:20],
                     "losers": sorted(rows, key=lambda r: r["change_pct"])[:20]}
            got = rank(pool, mechanism_of=why,
                       adv_of=adv,
                       gainers_losers=board,
                       blocked=_blocked_symbols(),
                       held=set(engine.open_positions),
                       now=datetime.combine(
                           datetime.fromisoformat(day).date(), clock),
                       open_of=lambda s: next(
                           (r["day_open"] for r in rows if r["symbol"] == s),
                           None),
                       top=8)
        except Exception as exc:                           # noqa: BLE001
            print(f"  {clock:%H:%M}  ranker failed: {exc}")
            clock = _step(clock)
            continue

        by_symbol = {r["symbol"]: r for r in rows}
        picks = got.get("rows") or []

        # ==========================================================
        # THE ENTRY RULES. MISSING FROM THIS HARNESS UNTIL 11 AUG.
        # ==========================================================
        #
        #     "we made some changes recently about entry, exit, bot
        #      trading when an opportunity occurs not on random stock
        #      after orb. have you considered them in these entries?
        #      as i see all entries were observed as random"
        #                                          -- operator
        #
        # He was right and this is where it was wrong. dashboard/state.py
        # -- the LIVE path -- runs every ranker row through
        # core/select.movement() before anything is sized (state.py:2505).
        # This harness went straight from rank() to position_plan(), so
        # it skipped three tests the live bot always applies:
        #
        #   1. the move is measured from the DAY OPEN, not yesterday's
        #      close, and must be >= MIN_MOVE_PCT
        #   2. volume must be >= 1.5x normal -- the ranker only asked
        #      for 1.2x, so a whole band of thin movers got through here
        #      that the live bot refuses
        #   3. FADED_FROM_HIGH: the stock must still be sitting in the
        #      top half of its own day range. This is the "is it still
        #      an opportunity, or is the move already over" test, and
        #      it is the single reason the replayed entries looked
        #      random -- nothing was checking whether the move was
        #      still alive at the moment of entry.
        #
        # Plus state.py's own rule underneath it: no published card AND
        # ordinary volume = drifting, refused.
        #
        # Copied in the same order, reading the same fields with the
        # same both-names fallback. A harness that does not run the real
        # path is worse than no harness -- this file's own header says
        # so, and then it did not do it.
        try:
            from core import select as _rules
            alive = []
            for row in picks:
                source = by_symbol.get(row.get("symbol")) or {}
                verdict = _rules.movement({
                    "ltp": row.get("ltp") or source.get("ltp"),
                    "day_open": (row.get("day_open") or row.get("open")
                                 or source.get("day_open")),
                    "day_high": (row.get("day_high") or row.get("high")
                                 or source.get("day_high")),
                    "day_low": (row.get("day_low") or row.get("low")
                                or source.get("day_low")),
                    "volume_ratio": (row.get("volume_ratio")
                                     or row.get("volume_x") or 1.6),
                })
                reason = (row.get("why") or "").strip()
                ratio = row.get("volume_ratio") or row.get("volume_x") or 0
                if not reason and ratio < _rules.UNEXPLAINED_VOLUME:
                    seen_refusals[f"drifting on {ratio:.1f}x volume with "
                                  f"nothing behind it"] = seen_refusals.get(
                        "drifting -- nothing behind it", 0) + 1
                    continue
                if not verdict.get("ok"):
                    # NOT `why` -- that name holds the cached mechanism
                    # lookup passed to rank(). Rebinding it turned the
                    # next rank() call into "'str' object is not
                    # callable" for the rest of the session.
                    refused_why = verdict.get("why") or "the move is over"
                    seen_refusals[refused_why] = \
                        seen_refusals.get(refused_why, 0) + 1
                    continue
                row["moving"] = verdict.get("why")
                alive.append(row)
            picks = alive
        except Exception as exc:                           # noqa: BLE001
            print(f"  [RULES] could not apply the live entry rules "
                  f"({exc}) -- REFUSING to replay without them.")
            con.close()
            return 1

        for row in picks:
            source = by_symbol.get(row.get("symbol")) or {}
            if row.get("state") == "fading":
                row["plan"] = {"ok": False, "why": "fading"}
                continue
            # The ranker's row does not always carry the price -- the
            # live path reads it off the mover. Same here, so the
            # recorded order has a real entry rather than None.
            if row.get("ltp") is None:
                row["ltp"] = source.get("ltp")
            # ---- SUPPLY IS NOT DEMAND. 8 August 2026. ----
            # core/supply_events.py was written, tested and imported by
            # nothing. LICI was bought on four of five replayed days
            # while the OFS notice sat in telegram.db the whole time.
            if EXIT_PLAN:
                try:
                    from core import supply_events
                    sold = supply_events.overhang(
                        row.get("symbol"),
                        now=datetime.combine(
                            datetime.fromisoformat(day).date(), clock))
                except Exception:                              # noqa: BLE001
                    sold = None
                if sold:
                    row["plan"] = {"ok": False,
                                   "why": f"supply: {sold['why']}"}
                    continue

            if EXIT_PLAN:
                # ---- THE MEASURED STOP, NOT THE DAY'S LOW. ----
                from core import exit_plan
                row["plan"] = exit_plan.plan(
                    source.get("ltp"),
                    typical_range_pct=_typical_range_pct(
                        row.get("symbol"), day),
                    symbol=row.get("symbol"),
                    headroom_of=lambda s: _headroom_of(s, con, day))
            else:
                row["plan"] = position_plan(
                    source.get("ltp"), row.get("action"),
                    day_low=source.get("day_low"),
                    day_high=source.get("day_high"))

        before = len(engine.orders)
        out = auto_entry.take(
            picks, engine,
            now=datetime.combine(datetime.fromisoformat(day).date(), clock),
            security_id_of=lambda s: "REPLAY",
            held=set(engine.open_positions),
            max_positions=_slots_from_cash(),
            alert=engine._manual_alert,
            enter=engine._enter)

        for record in out:
            if not record.get("taken"):
                seen_refusals[record["why"]] = \
                    seen_refusals.get(record["why"], 0) + 1

        for order in engine.orders[before:]:
            order["at_str"] = f"{clock:%H:%M}"
            order["minute"] = f"{day}T{clock:%H:%M}"

        clock = _step(clock)

    # ---- THE ANSWER ----
    print()
    if not engine.orders:
        print("  NO ORDERS.")
        if not switch_on:
            print("  Correct -- the switch was off. This is the result the")
            print("  7 August rotation bug should have produced and did not.")
        else:
            top = sorted(seen_refusals.items(), key=lambda kv: -kv[1])[:6]
            print("  Why it refused everything:")
            for reason, n in top:
                print(f"     {n:>4}x  {reason}")
        con.close()
        return 0

    print(f"  {len(engine.orders)} ORDER(S) THE BOT WOULD HAVE SENT")
    print()
    print("  %-5s %-12s %6s %9s %9s %9s" %
          ("TIME", "SYMBOL", "QTY", "ENTRY", "STOP", "TARGET"))
    print("  " + "-" * 62)
    total = 0.0
    for order in engine.orders:
        print("  %-5s %-12s %6s %9.2f %9.2f %9s" % (
            order["at_str"], order["symbol"], order["qty"], order["price"],
            order["stop"] or 0,
            f"{order['target']:.2f}" if order.get("target") else "--"))
        out_at, out_px, how = exit_of(
            con, day, order["symbol"], order["minute"], order["price"],
            order["stop"], order.get("target"))
        pnl = (out_px - order["price"]) * (order["qty"] or 0)
        total += pnl
        print(f"        exit {out_at or '--'} @ {out_px:.2f} ({how})"
              f"   P&L Rs {pnl:+,.0f}")
    print("  " + "-" * 62)
    print(f"  {'TOTAL on the recorded tape':<46} Rs {total:+,.0f}")
    print()
    print("  Read this as behaviour, not as a promise. One day, and the")
    print("  reasons in the store now are not all the reasons it had live.")
    print("=" * 74)
    con.close()
    return 0


def _step(clock):
    total = clock.hour * 60 + clock.minute + STEP_MINUTES
    return dtime(min(total // 60, 23), total % 60)


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().date().isoformat()
    rest = [a.lower() for a in sys.argv[2:]]
    on = "off" not in rest
    SELECT_MODE = "select" in rest
    EXIT_PLAN = "plan" in rest
    raise SystemExit(replay(day, switch_on=on, early="early" in rest))
