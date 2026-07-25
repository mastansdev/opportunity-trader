"""
==========================================================
Backtest -- session replay (baseline: current ORB + sizing/stops)
==========================================================

Walks a recorded session's 1-minute candles through the SAME decision
code the live bot uses -- the real OrbEngine (opening range), the real
Strategy (fresh-cross breakout + priming), the real compute_atr, and
the real round_trip_charges -- with the current sizing/stop config. It
produces the honest baseline: what the strategy you have would have
done on a clean session, with no restarts, no manual fat-fingers, no
feed lag.

FIDELITY / HONEST ASSUMPTIONS (stated, not hidden):
  - 1-minute granularity. Entries at the signal candle's CLOSE.
  - Intra-bar ordering is CONSERVATIVE: the adverse side is assumed to
    hit first (a long checks its stop against the bar LOW before its
    target against the bar HIGH), so wins are never overstated.
  - Exits modelled: initial ATR stop, chandelier ATR trail (activates
    once in profit), one ATR partial scale-out, and 15:15 square-off.
  - NOT modelled here: slippage, the volume-surge filter (the log
    candles have no volume), the news gate, the breadth regime gate.
    These are toggles for later; this is the pure price-action baseline.

Run:  py backtest/replay.py 2026-07-24
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg
from core.orb_engine import OrbEngine
from core.strategy import Strategy
from core.atr import compute_atr
from trading.charges import round_trip_charges
from backtest.candle_store import CandleStore

LAST_ENTRY = cfg.LAST_ENTRY_TIME       # "14:30"
SQUARE_OFF = cfg.SQUARE_OFF_TIME        # "15:15"
ORB_END = cfg.ORB_WINDOW_END            # "09:30"


def _hhmm(minute_iso):
    return minute_iso[11:16]            # "YYYY-MM-DDTHH:MM" -> "HH:MM"


def _cd(row):
    """Store row -> the candle dict shape Strategy/atr expect."""
    return {"high": row["h"], "low": row["l"], "close": row["c"],
            "open": row["o"], "time": row["minute"]}


class Position:
    __slots__ = ("sym", "dir", "entry", "qty", "qty_total", "atr0", "stop",
                 "t0", "peak", "partial_done", "realized")

    def __init__(self, sym, d, entry, qty, atr0, stop, t0):
        self.sym, self.dir, self.entry, self.qty = sym, d, entry, qty
        self.qty_total = qty
        self.atr0, self.stop, self.t0 = atr0, stop, t0
        self.peak = entry
        self.partial_done = False
        self.realized = 0.0


def _trend_shortlist(all_rows, top_n):
    """Operator's thesis (2026-07-24): 'sail with the trend'. Rank every
    symbol by its % move vs the 09:15 open, measured at the end of the
    ORB window (09:30). The top_n strongest are LONG-eligible, the top_n
    weakest are SHORT-eligible. Only trade a breakout that AGREES with
    the stock's own trend -- long the leaders, short the laggards, never
    the first-to-fire. Returns (eligible_long, eligible_short) sets."""
    day_open, ref_close = {}, {}
    for r in all_rows:
        s = r["symbol"]
        if s not in day_open:
            day_open[s] = r["o"]
        if _hhmm(r["minute"]) < ORB_END:
            ref_close[s] = r["c"]
    pct = {}
    for s, o in day_open.items():
        c = ref_close.get(s)
        if c is not None and o:
            pct[s] = (c - o) / o
    ranked = sorted(pct, key=lambda s: pct[s])
    eligible_short = set(ranked[:top_n])            # weakest
    eligible_long = set(ranked[-top_n:])             # strongest
    return eligible_long, eligible_short, pct


def run_replay(date, store=None, verbose=False, trend_top_n=None):
    store = store or CandleStore()
    all_rows = store.candles_for(date)              # ordered (minute, symbol)
    if not all_rows:
        print(f"No candles for {date}. Import first.")
        return None

    eligible_long = eligible_short = None
    if trend_top_n is not None:
        eligible_long, eligible_short, _ = _trend_shortlist(all_rows, trend_top_n)

    orb = OrbEngine()
    strat = Strategy(orb)

    # --- Build the opening range from 09:15-09:29 bars ---
    for r in all_rows:
        if _hhmm(r["minute"]) < ORB_END:
            t = datetime.fromisoformat(r["minute"])
            orb.update(r["symbol"], r["h"], t)
            orb.update(r["symbol"], r["l"], t)
    orb.force_complete_all()

    history = {}          # symbol -> [candle dicts], oldest first
    open_pos = {}          # symbol -> Position
    trades = []            # closed trades
    open_count = 0

    def size(entry, atr0):
        stop_dist = max(atr0 * cfg.ATR_STOP_MULTIPLIER,
                        entry * cfg.MIN_STOP_DISTANCE_PCT)
        qty = min(int(cfg.RISK_PER_TRADE_RS / stop_dist),
                  int(cfg.MAX_NOTIONAL_PER_TRADE_RS / entry))
        return qty, stop_dist

    def close_trade(p, exit_price, reason, tend):
        # realized already holds any partial; add the remaining leg
        if p.dir == "LONG":
            p.realized += (exit_price - p.entry) * p.qty
        else:
            p.realized += (p.entry - exit_price) * p.qty
        ch = round_trip_charges(p.entry, exit_price, p.qty_total, p.dir) \
            if hasattr(p, "qty_total") else None
        trades.append(dict(sym=p.sym, dir=p.dir, entry=p.entry,
                           exit=exit_price, reason=reason,
                           pnl=p.realized, t0=p.t0, tend=tend,
                           qty=getattr(p, "qty_total", p.qty)))

    # --- Walk the session bar by bar, in time order ---
    for r in all_rows:
        sym = r["symbol"]; minute = r["minute"]; hhmm = _hhmm(minute)
        if hhmm < ORB_END:
            continue
        cd = _cd(r)
        history.setdefault(sym, []).append(cd)
        past_squareoff = hhmm >= SQUARE_OFF

        # ---- manage an open position on this bar ----
        p = open_pos.get(sym)
        closed_this_bar = False
        if p is not None:
            hi, lo, c = r["h"], r["l"], r["c"]
            if past_squareoff:
                close_trade(p, c, "SQUARE_OFF", minute)
                del open_pos[sym]; open_count -= 1; closed_this_bar = True
            else:
                atr_now = compute_atr(history[sym], cfg.ATR_PERIOD) or p.atr0
                if p.dir == "LONG":
                    # adverse first: stop vs low
                    if lo <= p.stop:
                        close_trade(p, p.stop, "STOP", minute)
                        del open_pos[sym]; open_count -= 1; closed_this_bar = True
                    else:
                        # partial scale-out at the ATR milestone
                        milestone = p.entry + cfg.PARTIAL_EXIT_ATR_MULTIPLE * p.atr0
                        if (cfg.ENABLE_PARTIAL_EXIT and not p.partial_done
                                and hi >= milestone
                                and (milestone - p.entry) >= cfg.PARTIAL_EXIT_MIN_PCT * p.entry):
                            cut = int(p.qty * cfg.PARTIAL_EXIT_FRACTION)
                            if cut > 0:
                                p.realized += (milestone - p.entry) * cut
                                p.qty -= cut; p.partial_done = True
                        # chandelier trail
                        p.peak = max(p.peak, c)
                        if c - p.entry >= cfg.ATR_TRAIL_ACTIVATION_MULT * p.atr0:
                            new_stop = p.peak - cfg.ATR_TRAIL_MULTIPLIER * atr_now
                            floor = c * cfg.MIN_STOP_DISTANCE_PCT
                            p.stop = max(p.stop, min(new_stop, c - floor))
                else:  # SHORT
                    if hi >= p.stop:
                        close_trade(p, p.stop, "STOP", minute)
                        del open_pos[sym]; open_count -= 1; closed_this_bar = True
                    else:
                        milestone = p.entry - cfg.PARTIAL_EXIT_ATR_MULTIPLE * p.atr0
                        if (cfg.ENABLE_PARTIAL_EXIT and not p.partial_done
                                and lo <= milestone
                                and (p.entry - milestone) >= cfg.PARTIAL_EXIT_MIN_PCT * p.entry):
                            cut = int(p.qty * cfg.PARTIAL_EXIT_FRACTION)
                            if cut > 0:
                                p.realized += (p.entry - milestone) * cut
                                p.qty -= cut; p.partial_done = True
                        p.peak = min(p.peak, c)
                        if p.entry - c >= cfg.ATR_TRAIL_ACTIVATION_MULT * p.atr0:
                            new_stop = p.peak + cfg.ATR_TRAIL_MULTIPLIER * atr_now
                            floor = c * cfg.MIN_STOP_DISTANCE_PCT
                            p.stop = min(p.stop, max(new_stop, c + floor))

        # ---- consider a NEW entry (only if flat & allowed) ----
        entries_allowed = (not past_squareoff and hhmm < LAST_ENTRY
                           and open_count < cfg.MAX_OPEN_POSITIONS
                           and r["c"] >= cfg.MIN_TRADABLE_PRICE_RS)
        if entries_allowed and sym not in open_pos and not closed_this_bar:
            hist = history[sym]
            if len(hist) >= cfg.MIN_ATR_CANDLES:
                buy = strat.is_buy_signal(sym, cd, already_open=False)
                short = strat.is_short_signal(sym, cd, already_open=False)
                # Operator's trend filter: only trade breakouts that agree
                # with the stock's own trend rank (long the strongest,
                # short the weakest). No filter -> original clock-order.
                if trend_top_n is not None:
                    if buy and sym not in eligible_long:
                        buy = False
                    if short and sym not in eligible_short:
                        short = False
                if buy or short:
                    atr0 = compute_atr(hist, cfg.ATR_PERIOD)
                    if atr0 and atr0 > 0:
                        entry = r["c"]
                        qty, sd = size(entry, atr0)
                        if qty > 0:
                            d = "LONG" if buy else "SHORT"
                            stop = entry - sd if buy else entry + sd
                            pos = Position(sym, d, entry, qty, atr0, stop, minute)
                            pos.qty_total = qty
                            open_pos[sym] = pos; open_count += 1

        # ---- update the strategy's fresh-cross memory every bar ----
        strat.note_candle_close(sym, cd)

    # close anything still open at the last seen bar (safety net)
    last_close = {r["symbol"]: r["c"] for r in all_rows}
    for sym, p in list(open_pos.items()):
        close_trade(p, last_close[sym], "EOD", "")

    rep = _report(date, trades)
    rep["trade_list"] = trades
    return rep


def _report(date, trades):
    n = len(trades)
    if n == 0:
        print(f"=== REPLAY {date}: no trades ==="); return {"trades": 0}
    def _charge(t):
        c = round_trip_charges(t["entry"], t["exit"], t["qty"], t["dir"])
        return c["total_charges"] if isinstance(c, dict) else c

    gross = sum(t["pnl"] for t in trades)
    charges = sum(_charge(t) for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    los = [t for t in trades if t["pnl"] < 0]
    longs = [t for t in trades if t["dir"] == "LONG"]
    shorts = [t for t in trades if t["dir"] == "SHORT"]
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = sum(t["pnl"] for t in los) / len(los) if los else 0
    pf = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in los))) if los else float("inf")
    exp = gross / n

    print(f"=== REPLAY BASELINE {date} (current ORB + sizing/stops, clean) ===")
    print(f"Trades            : {n}  (LONG {len(longs)}, SHORT {len(shorts)})")
    print(f"Win rate          : {100*len(wins)/n:.1f}%  ({len(wins)}W/{len(los)}L)")
    print(f"GROSS P&L         : Rs {gross:,.0f}")
    print(f"Charges           : Rs {charges:,.0f}")
    print(f"NET P&L           : Rs {gross-charges:,.0f}")
    print(f"Avg win / avg loss: Rs {aw:,.0f} / Rs {al:,.0f}")
    print(f"Profit factor     : {pf:.2f}")
    print(f"Expectancy/trade  : Rs {exp:,.0f} (gross)")
    print(f"LONG / SHORT P&L  : Rs {sum(t['pnl'] for t in longs):,.0f} / Rs {sum(t['pnl'] for t in shorts):,.0f}")
    # exit reason mix
    from collections import Counter
    rc = Counter(t["reason"] for t in trades)
    print(f"Exit reasons      : " + ", ".join(f"{k} {v}" for k, v in rc.most_common()))
    print("Top winners       : " + ", ".join(
        f"{t['sym']}({t['dir'][0]}) +{t['pnl']:,.0f}" for t in sorted(trades, key=lambda x:-x['pnl'])[:5]))
    print("Top losers        : " + ", ".join(
        f"{t['sym']}({t['dir'][0]}) {t['pnl']:,.0f}" for t in sorted(trades, key=lambda x:x['pnl'])[:5]))
    return dict(trades=n, gross=gross, charges=charges, net=gross-charges,
                win_rate=100*len(wins)/n, pf=pf, expectancy=exp)


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-07-24"
    run_replay(date)
