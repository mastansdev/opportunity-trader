"""
==========================================================
Backtest -- MONDAY CONFIG replay (mirrors the shipped engine)
==========================================================

Replays a recorded session through the EXACT rule set that is now live
in core/engine.py, reading the same config.py values the bot reads. If
Monday's market repeated Friday, this is what the bot would have done.

Mirrored gates (all from config.py, nothing hard-coded here):
  - fresh ORB cross only
  - top-N gainers (long) / losers (short)
  - RELATIVE strength band vs the market median  [RS_BAND_MIN..MAX]
  - absolute-move ceiling                        [MAX_ABS_MOVE_PCT]
  - staged position caps by time of day          [STAGED_POSITION_LIMITS]
  - no entries after                             [STAGED_NO_ENTRY_AFTER]
  - ONE attempt per symbol per direction per day
  - tight trailing stop, NO fixed target
  - no-progress exit                             [NO_PROGRESS_*]
  - slot rotation for laggards
  - risk / notional / min-price sizing

Run:  py backtest/monday_replay.py 2026-07-24
"""

import os
import sys
import statistics as stats
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

# Symbols with known bad/corporate-action data or operator-flagged
# manual interference on 2026-07-24.
DEFAULT_EXCLUDE = {
    "APARINDS",   # operator's own manual trade (flat-100 fat finger)
    "INFY",       # corrupt bar: 1037 -> 111 -> back, in one minute
    "JLHL",       # -80% in one minute: split / corporate action
}


def _charge(entry, exit_, qty, d):
    c = round_trip_charges(entry, exit_, qty, d)
    return c["total_charges"] if isinstance(c, dict) else c


def _position_cap(hhmm):
    if not cfg.ENABLE_STAGED_ENTRY:
        return cfg.MAX_OPEN_POSITIONS
    if hhmm >= cfg.STAGED_NO_ENTRY_AFTER:
        return 0
    for cutoff, cap in cfg.STAGED_POSITION_LIMITS:
        if hhmm < cutoff:
            return min(cap, cfg.MAX_OPEN_POSITIONS)
    return cfg.MAX_OPEN_POSITIONS


def run_monday(date, store=None, exclude=None, verbose=True):
    exclude = DEFAULT_EXCLUDE if exclude is None else exclude
    store = store or CandleStore()
    rows = [r for r in store.candles_for(date) if r["symbol"] not in exclude]
    if not rows:
        print(f"No candles for {date}."); return None

    by_min = defaultdict(dict)
    day_open = {}
    for r in rows:
        by_min[r["minute"]][r["symbol"]] = r
        day_open.setdefault(r["symbol"], r["o"])
    minutes = sorted(by_min)

    orb = OrbEngine(); strat = Strategy(orb)
    for m in minutes:
        if _hhmm(m) >= cfg.ORB_WINDOW_END:
            break
        t = datetime.fromisoformat(m)
        for sym, r in by_min[m].items():
            orb.update(sym, r["h"], t); orb.update(sym, r["l"], t)
    orb.force_complete_all()

    history = defaultdict(list)
    pct, last_close = {}, {}
    open_pos, trades = {}, []
    attempted = defaultdict(set)          # symbol -> {"LONG","SHORT"}
    skipped = defaultdict(int)

    def book(p, price, reason, m):
        if p["dir"] == "LONG":
            p["realized"] += (price - p["entry"]) * p["qty"]
        else:
            p["realized"] += (p["entry"] - price) * p["qty"]
        trades.append(dict(sym=p["sym"], dir=p["dir"], entry=p["entry"],
                           exit=price, reason=reason, pnl=p["realized"],
                           t0=p["t0"], tend=m, qty=p["qty_total"],
                           rs=p["rs"]))

    for m in minutes:
        hhmm = _hhmm(m)
        if hhmm < cfg.ORB_WINDOW_END:
            continue
        bars = by_min[m]
        for sym, r in bars.items():
            history[sym].append(_cd(r)); last_close[sym] = r["c"]
            o = day_open.get(sym)
            if o:
                pct[sym] = (r["c"] - o) / o
        past_so = hhmm >= cfg.SQUARE_OFF_TIME
        market_med = stats.median(pct.values()) if pct else 0.0

        def rel(sym, d):
            p = pct.get(sym)
            if p is None:
                return None
            v = p - market_med
            return v if d == "LONG" else -v

        # ---------- manage open positions ----------
        for sym in list(open_pos):
            p = open_pos[sym]; r = bars.get(sym)
            if past_so:
                book(p, last_close.get(sym, p["entry"]), "SQUARE_OFF", m)
                del open_pos[sym]; continue
            if r is None:
                continue
            hi, lo, c = r["h"], r["l"], r["c"]
            atr_now = compute_atr(history[sym], cfg.ATR_PERIOD) or p["atr0"]
            hit = False
            if p["dir"] == "LONG":
                if lo <= p["stop"]:
                    book(p, p["stop"], "STOP", m); hit = True
                else:
                    p["peak"] = max(p["peak"], c)
                    if c - p["entry"] >= cfg.ATR_TRAIL_ACTIVATION_MULT * p["atr0"]:
                        ns = p["peak"] - cfg.ATR_TRAIL_MULTIPLIER * atr_now
                        p["stop"] = max(p["stop"],
                                        min(ns, c - c * cfg.MIN_STOP_DISTANCE_PCT))
            else:
                if hi >= p["stop"]:
                    book(p, p["stop"], "STOP", m); hit = True
                else:
                    p["peak"] = min(p["peak"], c)
                    if p["entry"] - c >= cfg.ATR_TRAIL_ACTIVATION_MULT * p["atr0"]:
                        ns = p["peak"] + cfg.ATR_TRAIL_MULTIPLIER * atr_now
                        p["stop"] = min(p["stop"],
                                        max(ns, c + c * cfg.MIN_STOP_DISTANCE_PCT))
            if hit:
                del open_pos[sym]; continue

            # no-progress exit
            if cfg.ENABLE_NO_PROGRESS_EXIT:
                held = (datetime.fromisoformat(m)
                        - datetime.fromisoformat(p["t0"])).total_seconds() / 60
                if held >= cfg.NO_PROGRESS_MINUTES:
                    gain = (c - p["entry"]) if p["dir"] == "LONG" else (p["entry"] - c)
                    if gain < cfg.NO_PROGRESS_R * p["risk"]:
                        book(p, c, "NO_PROGRESS", m); del open_pos[sym]; continue

        # ---------- entries ----------
        cap = _position_cap(hhmm)
        if not past_so and cap > 0:
            present = [s for s in bars if s in pct]
            gain = sorted((s for s in present if pct[s] > 0),
                          key=lambda s: -pct[s])[:cfg.TREND_RANK_TOP_N]
            loss = sorted((s for s in present if pct[s] < 0),
                          key=lambda s: pct[s])[:cfg.TREND_RANK_TOP_N]
            tg, tl = set(gain), set(loss)
            cands = []
            for sym, r in bars.items():
                if sym in open_pos:
                    continue
                if len(history[sym]) < cfg.MIN_ATR_CANDLES:
                    continue
                cd = _cd(r)
                for d, fn, pool in (("LONG", strat.is_buy_signal, tg),
                                    ("SHORT", strat.is_short_signal, tl)):
                    if not fn(sym, cd, False):
                        continue
                    if d in attempted[sym]:
                        skipped["already_attempted"] += 1; continue
                    if sym not in pool:
                        skipped["not_top_ranked"] += 1; continue
                    rv = rel(sym, d)
                    if rv is None:
                        continue
                    if cfg.ENABLE_RS_BAND and not (cfg.RS_BAND_MIN <= rv <= cfg.RS_BAND_MAX):
                        skipped["rs_band"] += 1; continue
                    if abs(pct.get(sym, 0)) > cfg.MAX_ABS_MOVE_PCT:
                        skipped["exhausted"] += 1; continue
                    cands.append((rv, sym, d, r["c"]))
            cands.sort(reverse=True)
            for rv, sym, d, price in cands:
                if price < cfg.MIN_TRADABLE_PRICE_RS:
                    skipped["price_floor"] += 1; continue
                atr0 = compute_atr(history[sym], cfg.ATR_PERIOD)
                if not atr0 or atr0 <= 0:
                    continue
                sd = max(atr0 * cfg.ATR_STOP_MULTIPLIER,
                         price * cfg.MIN_STOP_DISTANCE_PCT)
                qty = min(int(cfg.RISK_PER_TRADE_RS / sd),
                          int(cfg.MAX_NOTIONAL_PER_TRADE_RS / price))
                if qty <= 0:
                    continue
                if len(open_pos) >= cap:
                    if not cfg.ENABLE_SLOT_ROTATION:
                        skipped["book_full"] += 1; continue
                    weakest = min(
                        open_pos.values(),
                        key=lambda q: (rel(q["sym"], q["dir"]) if rel(q["sym"], q["dir"]) is not None else 99))
                    wrs = rel(weakest["sym"], weakest["dir"])
                    if wrs is None or rv <= wrs + cfg.ROTATION_MIN_STRENGTH_EDGE:
                        skipped["book_full"] += 1; continue
                    book(weakest, last_close[weakest["sym"]], "ROTATE_OUT", m)
                    del open_pos[weakest["sym"]]
                stop = price - sd if d == "LONG" else price + sd
                open_pos[sym] = dict(sym=sym, dir=d, entry=price, qty=qty,
                                     qty_total=qty, atr0=atr0, stop=stop,
                                     risk=sd, t0=m, peak=price, realized=0.0,
                                     rs=rv)
                attempted[sym].add(d)

        for sym, r in bars.items():
            strat.note_candle_close(sym, _cd(r))

    for sym, p in list(open_pos.items()):
        book(p, last_close[sym], "EOD", minutes[-1])

    return _report(date, trades, skipped, exclude, verbose)


def _report(date, trades, skipped, exclude, verbose):
    n = len(trades)
    print(f"=== MONDAY-CONFIG REPLAY on {date} ===")
    print(f"Excluded: {', '.join(sorted(exclude))}")
    print(f"Settings: RS band {cfg.RS_BAND_MIN:.3f}-{cfg.RS_BAND_MAX:.3f}, "
          f"maxmove {cfg.MAX_ABS_MOVE_PCT:.2f}, risk Rs{cfg.RISK_PER_TRADE_RS:.0f}, "
          f"stop {cfg.MIN_STOP_DISTANCE_PCT:.3f}, staged {cfg.STAGED_POSITION_LIMITS}")
    if n == 0:
        print("NO TRADES."); print("skip reasons:", dict(skipped)); return {"trades": 0}
    gross = sum(t["pnl"] for t in trades)
    charges = sum(_charge(t["entry"], t["exit"], t["qty"], t["dir"]) for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    los = [t for t in trades if t["pnl"] < 0]
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = sum(t["pnl"] for t in los) / len(los) if los else 0
    pf = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in los))) if los else float("inf")
    print(f"\nTrades            : {n}  (LONG {sum(1 for t in trades if t['dir']=='LONG')}, "
          f"SHORT {sum(1 for t in trades if t['dir']=='SHORT')})")
    print(f"Unique symbols    : {len({t['sym'] for t in trades})}  (one attempt each)")
    print(f"Win rate          : {100*len(wins)/n:.1f}%  ({len(wins)}W/{len(los)}L)")
    print(f"GROSS P&L         : Rs {gross:,.0f}")
    print(f"Charges           : Rs {charges:,.0f}")
    print(f"NET P&L           : Rs {gross-charges:,.0f}   "
          f"({100*(gross-charges)/cfg.MIS_CAPITAL_RS:+.2f}% on capital)")
    print(f"Avg win / avg loss: Rs {aw:,.0f} / Rs {al:,.0f}   (ratio {abs(aw/al) if al else 0:.2f}:1)")
    print(f"Profit factor     : {pf:.2f}   Expectancy: Rs {gross/n:,.0f}/trade")
    from collections import Counter
    print(f"Exit reasons      : " + ", ".join(f"{k} {v}" for k, v in Counter(t['reason'] for t in trades).most_common()))
    print(f"Signals rejected  : " + ", ".join(f"{k} {v}" for k, v in sorted(skipped.items(), key=lambda kv:-kv[1])))
    if verbose:
        print(f"\n{'time':6} {'dir':6}{'symbol':12}{'entry':>9}{'exit':>9}{'qty':>6}{'RS':>7}{'pnl':>9}  reason")
        for t in sorted(trades, key=lambda x: x["t0"]):
            print(f"{t['t0'][11:16]:6} {t['dir']:6}{t['sym']:12}{t['entry']:>9.1f}"
                  f"{t['exit']:>9.1f}{t['qty']:>6}{100*t['rs']:>6.1f}%{t['pnl']:>9,.0f}  {t['reason']}")
    return dict(trades=n, gross=gross, charges=charges, net=gross-charges,
                win_rate=100*len(wins)/n, pf=pf, trade_list=trades)


if __name__ == "__main__":
    run_monday(sys.argv[1] if len(sys.argv) > 1 else "2026-07-24")
