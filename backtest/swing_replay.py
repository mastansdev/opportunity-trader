"""
==========================================================
Swing replay -- ride the move for days, not minutes
==========================================================

    py backtest/swing_replay.py --help
    py backtest/swing_replay.py --train              # 2016-2021 only
    py backtest/swing_replay.py --test               # 2022-2026 only
    py backtest/swing_replay.py --sweep trail        # trail multiples

WHY THIS EXISTS
---------------
The intraday system was measured over 61 sessions (MULTIDAY_FINDINGS.md)
and the arithmetic did not work: Rs 35 of gross per trade against Rs 117
of charges. The statutory part of that Rs 117 -- STT, exchange, stamp,
SEBI, GST -- is about Rs 70 and cannot be negotiated away by any broker.
So a strategy whose average trade earns Rs 35 is not a broker problem or
a sizing problem. It is a HOLDING PERIOD problem: the same Rs 117 buys
you a 0.3% intraday wiggle or a 4% multi-day move, and only one of those
covers it.

The evidence that the move exists:

    trades closed intraday    1,949    avg Rs    35
    trades held to the bell       8    avg Rs 1,260

and 87 trades that ran past +3R made Rs 324,603 across 70 DIFFERENT
symbols -- 4.8x the entire system's gross, from a spread of names, not
one lucky stock. Verified clean of the corrupt-data symbols.

So: same core idea the operator has stated from the start -- ride a
stock while it moves our way, exit ruthlessly when it stops -- measured
on DAILY bars over ten years instead of on 61 intraday sessions.

WHAT IS DELIBERATELY DIFFERENT FROM THE LIVE BOT
------------------------------------------------
1. LONG ONLY. Shorts were 53% of intraday trades for 3.6% of the gross.
2. RANKED ENTRY, not first-come. When more stocks qualify than there
   are free slots, the STRONGEST are taken. The live bot enters
   whichever symbol's candle the feed happened to deliver first, which
   is the "clock-order was the original sin" problem it was supposed to
   have fixed.
3. NO forced square-off. The position closes when the trail breaks, not
   when a clock says so.
4. MTF COSTS ARE CHARGED. Holding overnight is not free: interest
   accrues daily on the funded portion at MTF_ANNUAL_RATE. A strategy
   that only works when you ignore the borrowing cost does not work.

HONESTY CONSTRAINTS BUILT IN
----------------------------
- TRAIN/TEST SPLIT. Parameters get chosen on 2016-2021 (--train) and
  are then run ONCE on 2022-2026 (--test). Sweeping on the test years
  spends the test.
- SURVIVORSHIP IS REAL AND IS NOT FIXED. The universe is today's
  master list, so every symbol here survived to 2026. This inflates
  results. It is stated in the output rather than quietly ignored.
- CORRUPT SYMBOLS EXCLUDED. The 25%+ day-on-day movers found on
  2026-07-27 (ZFCVINDIA, PATANJALI, HEXT and the rest) are dropped --
  a momentum system treats a data error as the strongest buy signal
  it has ever seen.
- NO LOOK-AHEAD. Every decision on day D uses bars up to and including
  D; the fill happens at D+1's open.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import random
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = "data/daily_candles.db"

# Symbols with an unexplained >25% day-on-day close move in the corpus.
# See the 2026-07-27 split check. Either unadjusted corporate actions,
# relistings after insolvency (PATANJALI/Ruchi Soya, HEXT), or two
# instruments colliding under one ticker (ZFCVINDIA reads 2,433 then
# 14,714 then 2,660 -- the real price is around 14,000).
EXCLUDE = {
    "ZFCVINDIA", "PATANJALI", "HEXT", "PICCADIL", "MWL", "MIDQ50ADD",
    "SHRIPISTON", "HEALTHADD", "PSUBANK", "JLHL", "MBAPL", "KRISHANA",
    "POCL", "BRIGADE",
}

TRAIN_END = "2021-12-31"
TEST_START = "2022-01-01"


# ----------------------------------------------------------
# Costs
# ----------------------------------------------------------
def round_trip_charges(entry, exit_price, qty):
    """Statutory + brokerage on one completed delivery/MTF round trip.
    Same rates as trading/charges.py -- intraday STT (0.025%) is
    replaced by the DELIVERY sell rate (0.1%), which is what an
    overnight position actually pays."""
    buy_turnover = entry * qty
    sell_turnover = exit_price * qty
    brokerage = min(20.0, 0.0003 * buy_turnover) + \
        min(20.0, 0.0003 * sell_turnover)
    stt = 0.001 * sell_turnover              # delivery sell leg
    exchange = 0.0000297 * (buy_turnover + sell_turnover)
    sebi = 0.000001 * (buy_turnover + sell_turnover)
    stamp = 0.00003 * buy_turnover
    gst = 0.18 * (brokerage + exchange + sebi)
    return brokerage + stt + exchange + sebi + stamp + gst


def mtf_interest(funded_amount, calendar_days, annual_rate):
    if funded_amount <= 0 or calendar_days <= 0:
        return 0.0
    return funded_amount * annual_rate * calendar_days / 365.0


# ----------------------------------------------------------
# Indicators -- plain python, no pandas dependency
# ----------------------------------------------------------
def wilder_atr(highs, lows, closes, period=14):
    """True-range ATR, Wilder smoothing. Returns a list aligned to the
    input, None until there is enough history."""
    n = len(closes)
    out = [None] * n
    trs = [None] * n
    for i in range(1, n):
        trs[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    if n <= period:
        return out
    seed = sum(trs[1:period + 1]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def rolling_max(values, window):
    out = [None] * len(values)
    for i in range(len(values)):
        if i + 1 >= window:
            out[i] = max(values[i - window + 1:i + 1])
    return out


def sma(values, window):
    out = [None] * len(values)
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= window:
            run -= values[i - window]
        if i + 1 >= window:
            out[i] = run / window
    return out


# ----------------------------------------------------------
def load(db=DB):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "select symbol, date, open, high, low, close, volume "
        "from daily_bars where close > 0 order by symbol, date"
    ).fetchall()
    bars = defaultdict(list)
    for sym, d, o, h, l, c, v in rows:
        if sym in EXCLUDE:
            continue
        bars[sym].append((d, o, h, l, c, v or 0.0))
    return bars


def build_indicators(bars, breakout_lookback, trend_ma, atr_period):
    """Per symbol: date -> the numbers a decision on that date needs."""
    ind = {}
    for sym, series in bars.items():
        if len(series) < max(breakout_lookback, trend_ma, atr_period) + 30:
            continue
        dates = [r[0] for r in series]
        highs = [r[2] for r in series]
        lows = [r[3] for r in series]
        closes = [r[4] for r in series]
        opens = [r[1] for r in series]
        vols = [r[5] for r in series]
        atr = wilder_atr(highs, lows, closes, atr_period)
        # breakout reference EXCLUDES today -- shifted by one
        hi_n = rolling_max(highs, breakout_lookback)
        hi_prev = [None] + hi_n[:-1]
        ma = sma(closes, trend_ma)
        value = [closes[i] * vols[i] for i in range(len(closes))]
        adv = sma(value, 20)
        ind[sym] = dict(dates=dates, opens=opens, highs=highs, lows=lows,
                        closes=closes, atr=atr, hi_prev=hi_prev, ma=ma,
                        adv=adv,
                        idx={d: i for i, d in enumerate(dates)})
    return ind


def run(ind, all_dates, p, verbose=False):
    equity = p["capital"]
    cash_peak = equity
    open_pos = {}
    trades = []
    max_dd = 0.0

    for di, today in enumerate(all_dates):
        if di + 1 >= len(all_dates):
            break
        nxt = all_dates[di + 1]

        # ---------- manage open positions on TODAY's bar ----------
        for sym in list(open_pos):
            s = ind[sym]
            i = s["idx"].get(today)
            if i is None:
                continue
            pos = open_pos[sym]
            high, low, close = s["highs"][i], s["lows"][i], s["closes"][i]
            a = s["atr"][i] or pos["atr0"]
            pos["peak"] = max(pos["peak"], high)
            # chandelier: ratchets up, never down
            new_stop = pos["peak"] - p["trail_atr"] * a
            pos["stop"] = max(pos["stop"], new_stop)
            pos["days"] += 1
            # Optional fixed rupee profit-taking -- the "book Rs 10,000
            # and move on" rule. Modelled as a limit: if the day's high
            # reaches the target, we are filled there.
            if p.get("max_profit_rs"):
                target = pos["entry"] + p["max_profit_rs"] / pos["qty"]
                if high >= target:
                    _close(open_pos, trades, sym, target, today, p)
                    continue
            # Fixed rupee loss cap. Pessimistic on purpose: when BOTH
            # the target and the loss cap sit inside one day's range we
            # cannot know from a daily bar which was touched first, so
            # the LOSS is taken. Assuming the good one filled first is
            # how backtests flatter themselves.
            if p.get("max_loss_rs"):
                floor = pos["entry"] - p["max_loss_rs"] / pos["qty"]
                if low <= floor:
                    _close(open_pos, trades, sym, floor, today, p)
                    continue
            # Hard holding limit -- "don't hold indefinitely".
            if p.get("max_days") and pos["days"] >= p["max_days"]:
                _close(open_pos, trades, sym, close, today, p)
                continue
            if low <= pos["stop"]:
                fill = min(pos["stop"], s["opens"][i]) \
                    if s["opens"][i] < pos["stop"] else pos["stop"]
                _close(open_pos, trades, sym, fill, today, p)

        # ---------- rank candidates on TODAY, fill at NEXT open ----------
        free = p["max_positions"] - len(open_pos)
        if free > 0:
            cands = []
            for sym, s in ind.items():
                if sym in open_pos:
                    continue
                i = s["idx"].get(today)
                if i is None or i < 1:
                    continue
                c = s["closes"][i]
                a, hp, m, adv = s["atr"][i], s["hi_prev"][i], s["ma"][i], s["adv"][i]
                if None in (a, hp, m, adv) or a <= 0:
                    continue
                if c < p["min_price"] or adv < p["min_adv"]:
                    continue
                if p.get("random_entry"):
                    # CONTROL GROUP. Same universe, same price and
                    # liquidity filters, same sizing, same exits --
                    # the ONLY difference is that the stock is chosen
                    # at random instead of by the breakout signal.
                    # If the real signal cannot beat this, the signal
                    # is decoration and every hour spent tuning it was
                    # wasted.
                    cands.append((p["_rng"].random(), sym, i))
                    continue
                if c <= hp or c <= m:            # new N-day high, above trend
                    continue
                # strength = distance above the trend line, in ATRs
                cands.append(((c - m) / a, sym, i))
            cands.sort(reverse=True)
            for _, sym, i in cands[:free]:
                s = ind[sym]
                j = s["idx"].get(nxt)
                if j is None:
                    continue
                entry = s["opens"][j]
                a = s["atr"][i]
                stop = entry - p["stop_atr"] * a
                if stop <= 0 or entry <= 0:
                    continue
                risk_rs = equity * p["risk_pct"]
                qty = int(risk_rs / (entry - stop))
                if qty < 1:
                    continue
                notional = qty * entry
                if notional > equity * p["max_leverage"]:
                    qty = int(equity * p["max_leverage"] / entry)
                if qty < 1:
                    continue
                open_pos[sym] = dict(entry=entry, qty=qty, stop=stop,
                                     peak=entry, atr0=a, date=nxt, days=0)

        # ---------- equity mark ----------
        realised = sum(t["net"] for t in trades)
        equity = p["capital"] + realised
        cash_peak = max(cash_peak, equity)
        max_dd = min(max_dd, equity - cash_peak)

    # Force-close whatever is still open, at the last close INSIDE THE
    # WINDOW.
    #
    # 2026-07-27 BUG, caught by the operator asking to see actual
    # trades instead of a summary: this used s["closes"][-1] -- the
    # last close of the symbol's ENTIRE history, which is 2026-07-24.
    # Running --train (ending 2021-12-31) therefore sold every position
    # still open at the boundary at its 2026 price. BSE showed as
    # 212.88 -> 3,549.70 in 20 days. The backtest was reading five
    # years into the future, and every number it produced before this
    # fix is void.
    last = all_dates[-1]
    for sym in list(open_pos):
        s = ind[sym]
        i = s["idx"].get(last)
        if i is None:
            # No bar on the final day (halted/illiquid). Walk back to
            # the most recent bar that IS inside the window -- never
            # forward.
            i = max((s["idx"][d] for d in all_dates if d in s["idx"]),
                    default=None)
            if i is None:
                open_pos.pop(sym)
                continue
        _close(open_pos, trades, sym, s["closes"][i], last, p)

    return trades, max_dd


def _close(open_pos, trades, sym, price, date, p):
    pos = open_pos.pop(sym)
    gross = (price - pos["entry"]) * pos["qty"]
    charges = round_trip_charges(pos["entry"], price, pos["qty"])
    notional = pos["entry"] * pos["qty"]
    funded = max(0.0, notional - notional / max(p["max_leverage"], 1.0))
    interest = mtf_interest(funded, pos["days"] * 7 / 5.0, p["mtf_rate"])
    trades.append(dict(sym=sym, entry=pos["entry"], exit=price,
                       qty=pos["qty"], days=pos["days"], gross=gross,
                       charges=charges, interest=interest,
                       net=gross - charges - interest,
                       entry_date=pos["date"], exit_date=date))


def report(trades, max_dd, p, label):
    if not trades:
        print(f"{label}: no trades")
        return None
    n = len(trades)
    gross = sum(t["gross"] for t in trades)
    ch = sum(t["charges"] for t in trades)
    it = sum(t["interest"] for t in trades)
    net = sum(t["net"] for t in trades)
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] <= 0]
    hold = sum(t["days"] for t in trades) / n
    yrs = len(set(t["entry_date"][:4] for t in trades))
    print(f"\n=== {label} ===")
    print(f"  trades {n:,}   avg hold {hold:.1f} trading days   "
          f"win {100*len(wins)/n:.1f}%")
    print(f"  GROSS     Rs {gross:>12,.0f}")
    print(f"  charges   Rs {-ch:>12,.0f}")
    print(f"  MTF int   Rs {-it:>12,.0f}")
    print(f"  NET       Rs {net:>12,.0f}   on Rs {p['capital']:,.0f} capital")
    print(f"  return    {100*net/p['capital']:>10.1f}%  over ~{yrs} years")
    if wins:
        print(f"  avg win   Rs {sum(t['net'] for t in wins)/len(wins):>12,.0f}")
    if losses:
        print(f"  avg loss  Rs {sum(t['net'] for t in losses)/len(losses):>12,.0f}")
    print(f"  max drawdown Rs {max_dd:>10,.0f} "
          f"({100*max_dd/p['capital']:.1f}% of capital)")
    return net


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=30_00_000)
    ap.add_argument("--risk-pct", type=float, default=0.01)
    ap.add_argument("--stop-atr", type=float, default=2.5)
    ap.add_argument("--trail-atr", type=float, default=4.0)
    ap.add_argument("--breakout", type=int, default=50)
    ap.add_argument("--trend-ma", type=int, default=100)
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--max-positions", type=int, default=10)
    ap.add_argument("--max-leverage", type=float, default=4.0)
    ap.add_argument("--mtf-rate", type=float, default=0.1349)
    ap.add_argument("--min-price", type=float, default=200.0)
    ap.add_argument("--min-adv", type=float, default=2e7)
    ap.add_argument("--max-profit-rs", type=float, default=None,
                    help="book out at this rupee profit (target test)")
    ap.add_argument("--max-loss-rs", type=float, default=None,
                    help="cut at this rupee loss (fixed bracket test)")
    ap.add_argument("--max-days", type=int, default=None,
                    help="force exit after N trading days held")
    ap.add_argument("--dump-trades", type=int, default=None, metavar="N",
                    help="print the N biggest and N worst trades with "
                         "dates and prices, so every one can be checked "
                         "against a real chart")
    ap.add_argument("--buy-and-hold", default=None, metavar="SYMBOL",
                    help="sanity check: what did this stock actually do "
                         "over the window? compare against any chart")
    ap.add_argument("--random-entry", type=int, default=None, metavar="SEED",
                    help="control: pick stocks at random, same everything "
                         "else. The signal must beat this to exist.")
    ap.add_argument("--benchmark", action="store_true",
                    help="equal-weight buy & hold over the same window")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()

    p = dict(capital=a.capital, risk_pct=a.risk_pct, stop_atr=a.stop_atr,
             trail_atr=a.trail_atr, max_positions=a.max_positions,
             max_leverage=a.max_leverage, mtf_rate=a.mtf_rate,
             min_price=a.min_price, min_adv=a.min_adv,
             max_profit_rs=a.max_profit_rs, max_loss_rs=a.max_loss_rs,
             max_days=a.max_days,
             random_entry=a.random_entry is not None,
             _rng=random.Random(a.random_entry or 0))

    bars = load()
    ind = build_indicators(bars, a.breakout, a.trend_ma, a.atr_period)
    dates = sorted({d for s in ind.values() for d in s["dates"]})
    if a.train:
        dates = [d for d in dates if d <= TRAIN_END]
        label = f"TRAIN 2016-2021  stop {a.stop_atr}ATR trail {a.trail_atr}ATR"
    elif a.test:
        dates = [d for d in dates if d >= TEST_START]
        label = f"TEST 2022-2026  stop {a.stop_atr}ATR trail {a.trail_atr}ATR"
    else:
        label = f"ALL 2016-2026  stop {a.stop_atr}ATR trail {a.trail_atr}ATR"

    print(f"universe {len(ind)} symbols, {len(dates)} sessions, "
          f"{EXCLUDE and len(EXCLUDE)} excluded as corrupt")
    if a.benchmark:
        # The only comparison that matters: what would simply OWNING
        # this universe have done over the same window, with no rules,
        # no trading, no charges and no interest? A strategy that does
        # not beat this is an expensive way to underperform doing
        # nothing.
        rets = []
        for sym, s in ind.items():
            inside = [d for d in dates if d in s["idx"]]
            if len(inside) < 200:
                continue
            p0 = s["closes"][s["idx"][inside[0]]]
            p1 = s["closes"][s["idx"][inside[-1]]]
            if p0 > 0:
                rets.append((p1 - p0) / p0 * 100.0)
        rets.sort()
        mean = sum(rets) / len(rets)
        print(f"\nBENCHMARK -- equal-weight buy & hold, {len(rets)} symbols")
        print(f"  window {dates[0]} -> {dates[-1]}")
        print(f"  mean   {mean:+.1f}%")
        print(f"  median {rets[len(rets)//2]:+.1f}%")
        print("  no trading, no charges, no interest, no decisions.")
        return

    if a.buy_and_hold:
        s = ind.get(a.buy_and_hold)
        if not s:
            sys.exit(f"{a.buy_and_hold} not in the universe")
        first = next(d for d in dates if d in s["idx"])
        last = next(d for d in reversed(dates) if d in s["idx"])
        p0 = s["closes"][s["idx"][first]]
        p1 = s["closes"][s["idx"][last]]
        print(f"\nBUY AND HOLD SANITY CHECK -- {a.buy_and_hold}")
        print(f"  {first}  close Rs {p0:,.2f}")
        print(f"  {last}  close Rs {p1:,.2f}")
        print(f"  move {100*(p1-p0)/p0:+.1f}%")
        print("  ^ open this symbol on any chart for these two dates.")
        print("    If these prices are wrong, nothing else here is right.")
        return

    trades, dd = run(ind, dates, p)
    report(trades, dd, p, label)

    if a.dump_trades:
        ordered = sorted(trades, key=lambda t: -t["net"])
        print("\n  Every row below is checkable on a chart: open the")
        print("  symbol, look at the two dates, confirm the prices.\n")
        for title, rows in (("BIGGEST WINNERS", ordered[:a.dump_trades]),
                            ("WORST LOSERS", ordered[-a.dump_trades:])):
            print(f"  --- {title} ---")
            print(f"  {'symbol':<13}{'in':<12}{'entry':>10}"
                  f"{'out':<13}{'exit':>10}{'days':>6}{'net':>12}")
            for t in rows:
                print(f"  {t['sym']:<13}{t['entry_date']:<12}"
                      f"{t['entry']:>10,.2f} {t['exit_date']:<12}"
                      f"{t['exit']:>10,.2f}{t['days']:>6}{t['net']:>12,.0f}")
            print()
    print("\n  NOTE: universe is TODAY's master list -- every symbol here")
    print("  survived to 2026. That biases these numbers UPWARD and is")
    print("  not corrected for.")


if __name__ == "__main__":
    main()
