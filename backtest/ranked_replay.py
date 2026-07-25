"""
==========================================================
Backtest -- RANKED / ROTATION replay (operator's thesis)
==========================================================

"Sail with the trend. Trade only the top gainers (long) and top
losers (short) -- not the first names to twitch past their range."

The difference from the baseline (backtest/replay.py):
  - Selection is by LIVE STRENGTH, not clock order. Each minute the
    universe is ranked by % change vs the 09:15 open. Only an ORB
    breakout that is ALSO in the top-N gainers (long) or bottom-N
    losers (short) can be taken.
  - The ranking is DYNAMIC ("flow with the current"): a stock that's
    flat at 9:30 and leads by noon becomes eligible at noon.
  - Slots fill by strength, strongest first.
  - ROTATION: when the book is full and a decisively stronger breakout
    appears, the WEAKEST current holder is dropped to make room. A
    slot is no longer taken for the whole day by whoever grabbed it at
    09:34.

Same sizing/stops/charges as live. Same honest fidelity caveats as
backtest/replay.py (1-min bars, adverse-first intrabar, no slippage).

Run:  py backtest/ranked_replay.py 2026-07-24 20
"""

import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg
from core.orb_engine import OrbEngine
from core.strategy import Strategy
from core.atr import compute_atr
from trading.charges import round_trip_charges
from backtest.candle_store import CandleStore
from backtest.replay import _cd, _hhmm

ORB_END = cfg.ORB_WINDOW_END
LAST_ENTRY = cfg.LAST_ENTRY_TIME
SQUARE_OFF = cfg.SQUARE_OFF_TIME
ROTATE_MARGIN = 0.003     # a challenger must be >0.3% stronger to evict a holder


def _charge(entry, exit_, qty, d):
    c = round_trip_charges(entry, exit_, qty, d)
    return c["total_charges"] if isinstance(c, dict) else c


def run_ranked(date, store=None, top_n=20, rotate=True,
               exclude=frozenset(), orb_stop_pct=None,
               min_strength=None, max_strength=None, take_profit_pct=None,
               target_rs=None, last_entry=None, weight_mode=None,
               weight_span=0.5):
    """
    exclude       : symbols to drop entirely (e.g. APARINDS, INFY).
    orb_stop_pct  : if set (e.g. 0.001), use a FIXED stop at the ORB
                    boundary instead of the ATR trail -- long stop =
                    ORB low x (1 - pct), short stop = ORB high x
                    (1 + pct). Sizing risks the entry-to-that-stop
                    distance, and the stop does NOT trail (stays put).
                    Partial scale-out + square-off still apply.
    """
    entry_cutoff = last_entry or LAST_ENTRY
    store = store or CandleStore()
    rows = store.candles_for(date)
    if exclude:
        rows = [r for r in rows if r["symbol"] not in exclude]
    if not rows:
        print(f"No candles for {date}."); return None
    fixed_orb_stop = orb_stop_pct is not None

    # group by minute -> {sym: row}
    by_min = defaultdict(dict)
    day_open = {}
    for r in rows:
        by_min[r["minute"]][r["symbol"]] = r
        if r["symbol"] not in day_open:
            day_open[r["symbol"]] = r["o"]
    minutes = sorted(by_min)

    # ORB ranges
    orb = OrbEngine(); strat = Strategy(orb)
    for m in minutes:
        if _hhmm(m) >= ORB_END:
            break
        t = datetime.fromisoformat(m)
        for sym, r in by_min[m].items():
            orb.update(sym, r["h"], t); orb.update(sym, r["l"], t)
    orb.force_complete_all()

    history = defaultdict(list)
    last_close = {}
    pct = {}
    open_pos = {}     # sym -> dict
    trades = []

    def size(entry, atr0):
        sd = max(atr0 * cfg.ATR_STOP_MULTIPLIER, entry * cfg.MIN_STOP_DISTANCE_PCT)
        return min(int(cfg.RISK_PER_TRADE_RS / sd),
                   int(cfg.MAX_NOTIONAL_PER_TRADE_RS / entry)), sd

    def strength(sym, d):
        p = pct.get(sym, 0.0)
        return p if d == "LONG" else -p

    def book_realize(p, exit_price, reason, tend):
        if p["dir"] == "LONG":
            p["realized"] += (exit_price - p["entry"]) * p["qty"]
        else:
            p["realized"] += (p["entry"] - exit_price) * p["qty"]
        trades.append(dict(sym=p["sym"], dir=p["dir"], entry=p["entry"],
                           exit=exit_price, reason=reason, pnl=p["realized"],
                           t0=p["t0"], tend=tend, qty=p["qty_total"]))

    for m in minutes:
        hhmm = _hhmm(m)
        if hhmm < ORB_END:
            continue
        bars = by_min[m]
        for sym, r in bars.items():
            history[sym].append(_cd(r))
            last_close[sym] = r["c"]
            o = day_open.get(sym)
            if o:
                pct[sym] = (r["c"] - o) / o
        past_so = hhmm >= SQUARE_OFF

        # ---- exits ----
        for sym in list(open_pos):
            p = open_pos[sym]
            r = bars.get(sym)
            if past_so:
                book_realize(p, last_close.get(sym, p["entry"]), "SQUARE_OFF", m)
                del open_pos[sym]; continue
            if r is None:
                continue
            hi, lo, c = r["h"], r["l"], r["c"]
            atr_now = compute_atr(history[sym], cfg.ATR_PERIOD) or p["atr0"]
            if p["dir"] == "LONG":
                if lo <= p["stop"]:
                    book_realize(p, p["stop"], "STOP", m); del open_pos[sym]; continue
                # Operator's method (2026-07-25): capture points and
                # rotate -- don't ride to the bell. Adverse-first, so
                # the stop above is checked before this target.
                tgt = None
                if target_rs is not None:
                    tgt = p["entry"] + target_rs / max(p["qty"], 1)
                elif take_profit_pct is not None:
                    tgt = p["entry"] * (1 + take_profit_pct)
                if tgt is not None and hi >= tgt:
                    book_realize(p, tgt, "TARGET", m); del open_pos[sym]; continue
                mile = p["entry"] + cfg.PARTIAL_EXIT_ATR_MULTIPLE * p["atr0"]
                if (cfg.ENABLE_PARTIAL_EXIT and not p["partial"] and hi >= mile
                        and (mile - p["entry"]) >= cfg.PARTIAL_EXIT_MIN_PCT * p["entry"]):
                    cut = int(p["qty"] * cfg.PARTIAL_EXIT_FRACTION)
                    if cut > 0:
                        p["realized"] += (mile - p["entry"]) * cut; p["qty"] -= cut; p["partial"] = True
                p["peak"] = max(p["peak"], c)
                if not fixed_orb_stop and c - p["entry"] >= cfg.ATR_TRAIL_ACTIVATION_MULT * p["atr0"]:
                    ns = p["peak"] - cfg.ATR_TRAIL_MULTIPLIER * atr_now
                    p["stop"] = max(p["stop"], min(ns, c - c * cfg.MIN_STOP_DISTANCE_PCT))
            else:
                if hi >= p["stop"]:
                    book_realize(p, p["stop"], "STOP", m); del open_pos[sym]; continue
                tgt = None
                if target_rs is not None:
                    tgt = p["entry"] - target_rs / max(p["qty"], 1)
                elif take_profit_pct is not None:
                    tgt = p["entry"] * (1 - take_profit_pct)
                if tgt is not None and lo <= tgt:
                    book_realize(p, tgt, "TARGET", m); del open_pos[sym]; continue
                mile = p["entry"] - cfg.PARTIAL_EXIT_ATR_MULTIPLE * p["atr0"]
                if (cfg.ENABLE_PARTIAL_EXIT and not p["partial"] and lo <= mile
                        and (p["entry"] - mile) >= cfg.PARTIAL_EXIT_MIN_PCT * p["entry"]):
                    cut = int(p["qty"] * cfg.PARTIAL_EXIT_FRACTION)
                    if cut > 0:
                        p["realized"] += (p["entry"] - mile) * cut; p["qty"] -= cut; p["partial"] = True
                p["peak"] = min(p["peak"], c)
                if not fixed_orb_stop and p["entry"] - c >= cfg.ATR_TRAIL_ACTIVATION_MULT * p["atr0"]:
                    ns = p["peak"] + cfg.ATR_TRAIL_MULTIPLIER * atr_now
                    p["stop"] = min(p["stop"], max(ns, c + c * cfg.MIN_STOP_DISTANCE_PCT))

        # ---- entries (ranked) ----
        if not past_so and hhmm < entry_cutoff:
            # live leaderboards
            present = [s for s in bars if s in pct]
            gainers = sorted((s for s in present if pct[s] > 0), key=lambda s: -pct[s])[:top_n]
            losers = sorted((s for s in present if pct[s] < 0), key=lambda s: pct[s])[:top_n]
            top_gain, top_loss = set(gainers), set(losers)
            cands = []
            for sym, r in bars.items():
                if sym in open_pos:
                    continue
                if len(history[sym]) < cfg.MIN_ATR_CANDLES:
                    continue
                cd = _cd(r)
                # "Not too hot" band (2026-07-25): a name already up 10%
                # has SPENT its move -- buying that breakout is buying
                # exhaustion (proven on 2026-07-24: strongest quartile
                # avg -Rs640 @31% win, moderate +2-3% movers +Rs415 @57%).
                # min/max_strength keep only FRESH leaders, not parabolic
                # ones. Strength is the move in the trade's own favour.
                if strat.is_buy_signal(sym, cd, False) and sym in top_gain:
                    s = pct[sym]
                    if (min_strength is None or s >= min_strength) and \
                       (max_strength is None or s <= max_strength):
                        cands.append((s, sym, "LONG", r["c"]))
                elif strat.is_short_signal(sym, cd, False) and sym in top_loss:
                    s = -pct[sym]
                    if (min_strength is None or s >= min_strength) and \
                       (max_strength is None or s <= max_strength):
                        cands.append((s, sym, "SHORT", r["c"]))
            cands.sort(reverse=True)     # strongest first
            for stren, sym, d, price in cands:
                if price < cfg.MIN_TRADABLE_PRICE_RS:
                    continue
                atr0 = compute_atr(history[sym], cfg.ATR_PERIOD)
                if not atr0 or atr0 <= 0:
                    continue
                if fixed_orb_stop:
                    rng = orb.get_range(sym)
                    if rng is None:
                        continue
                    if d == "LONG":
                        stop = rng["low"] * (1 - orb_stop_pct); sd = price - stop
                    else:
                        stop = rng["high"] * (1 + orb_stop_pct); sd = stop - price
                    if sd <= 0:
                        continue
                    qty = min(int(cfg.RISK_PER_TRADE_RS / sd),
                              int(cfg.MAX_NOTIONAL_PER_TRADE_RS / price))
                else:
                    qty, sd = size(price, atr0)
                # Conviction weighting (2026-07-25): allocate MORE to
                # higher-conviction names instead of treating every
                # trade identically. weight_mode "strong" = more to the
                # most-extended; "fresh" = more to the least-extended
                # (the quartile study said extended names underperform).
                # Average weight stays ~1.0 so total exposure is
                # comparable to the equal-weight run.
                if weight_mode:
                    lo = min_strength if min_strength is not None else 0.0
                    hi = max_strength if max_strength is not None else 0.05
                    norm = 0.5 if hi <= lo else (stren - lo) / (hi - lo)
                    norm = max(0.0, min(1.0, norm))
                    if weight_mode == "fresh":
                        norm = 1.0 - norm
                    w = (1.0 - weight_span) + 2 * weight_span * norm
                    qty = int(qty * w)
                if qty <= 0:
                    continue
                if len(open_pos) < cfg.MAX_OPEN_POSITIONS:
                    pass
                elif rotate:
                    weakest = min(open_pos.values(), key=lambda p: strength(p["sym"], p["dir"]))
                    if stren <= strength(weakest["sym"], weakest["dir"]) + ROTATE_MARGIN:
                        continue
                    book_realize(weakest, last_close[weakest["sym"]], "ROTATE_OUT", m)
                    del open_pos[weakest["sym"]]
                else:
                    continue
                stop = price - sd if d == "LONG" else price + sd
                open_pos[sym] = dict(sym=sym, dir=d, entry=price, qty=qty, qty_total=qty,
                                     atr0=atr0, stop=stop, t0=m, peak=price,
                                     partial=False, realized=0.0)

        for sym, r in bars.items():
            strat.note_candle_close(sym, _cd(r))

    for sym, p in list(open_pos.items()):
        book_realize(p, last_close[sym], "EOD", minutes[-1])

    return _report(date, trades, top_n, rotate)


def _report(date, trades, top_n, rotate):
    n = len(trades)
    if n == 0:
        print(f"=== RANKED {date}: no trades (top_n={top_n}) ==="); return {"trades": 0}
    gross = sum(t["pnl"] for t in trades)
    charges = sum(_charge(t["entry"], t["exit"], t["qty"], t["dir"]) for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    los = [t for t in trades if t["pnl"] < 0]
    longs = [t for t in trades if t["dir"] == "LONG"]
    shorts = [t for t in trades if t["dir"] == "SHORT"]
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = sum(t["pnl"] for t in los) / len(los) if los else 0
    pf = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in los))) if los else float("inf")
    from collections import Counter
    rc = Counter(t["reason"] for t in trades)
    print(f"=== RANKED REPLAY {date}  (top {top_n} gainers/losers, rotate={rotate}) ===")
    print(f"Trades            : {n}  (LONG {len(longs)}, SHORT {len(shorts)})")
    print(f"Win rate          : {100*len(wins)/n:.1f}%  ({len(wins)}W/{len(los)}L)")
    print(f"GROSS P&L         : Rs {gross:,.0f}")
    print(f"Charges           : Rs {charges:,.0f}")
    print(f"NET P&L           : Rs {gross-charges:,.0f}")
    print(f"Avg win / avg loss: Rs {aw:,.0f} / Rs {al:,.0f}")
    print(f"Profit factor     : {pf:.2f}   Expectancy/trade: Rs {gross/n:,.0f}")
    print(f"LONG / SHORT P&L  : Rs {sum(t['pnl'] for t in longs):,.0f} / Rs {sum(t['pnl'] for t in shorts):,.0f}")
    print(f"Exit reasons      : " + ", ".join(f"{k} {v}" for k, v in rc.most_common()))
    print("Top winners       : " + ", ".join(f"{t['sym']}({t['dir'][0]}) +{t['pnl']:,.0f}" for t in sorted(trades, key=lambda x:-x['pnl'])[:6]))
    print("Top losers        : " + ", ".join(f"{t['sym']}({t['dir'][0]}) {t['pnl']:,.0f}" for t in sorted(trades, key=lambda x:x['pnl'])[:6]))
    return dict(trades=n, gross=gross, charges=charges, net=gross-charges,
                win_rate=100*len(wins)/n, pf=pf, trade_list=trades)


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-07-24"
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    run_ranked(date, top_n=top_n)
