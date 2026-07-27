"""
==========================================================
Shortlist -- the names worth the operator's attention
==========================================================

WHY THIS EXISTS
---------------
Operator, 2026-07-27:

    "as a human i cannot read all 750/960/1500 stocks daily, i created
     bot to trade beside me not replacing me"

That is the job. Not to decide -- to make sure nothing worth deciding
about goes unseen.

THE FAILURE THIS REPLACES
-------------------------
core/momentum_universe.py ranks every symbol by one number: % change
against its own day open, then locks the top 25. Price and nothing
else. On 2026-07-27 that produced SWIGGY and AWFIS -- neither had any
event behind it -- while these never reached the screen:

    TMB        +12.1%   Q1 business update, total advances +27% YoY
    CARTRADE   +10.8%   UBS initiated Buy, target Rs 4,000
    KFINTECH    +9.2%   Q1 results, revenue +30% YoY, profit beat
    SENCO       +7.4%   Q1 update, revenue +60% YoY

Every one of those was public before 09:15. The bot was not blind
because the information was hidden; it was blind because it only ever
looked at price.

WHAT THIS DOES DIFFERENTLY
--------------------------
Ranks on REASON, and shows the reason next to the name. Six inputs,
all of them visible in the output, none of them secret:

  1. RESULTS      results_calendar.db -- did this company just report,
                  or is it about to? (3,973 events, 922 symbols)
  2. ACTION       stock_memory.db -- dividend / buyback / bonus
  3. STRENGTH     today's move, and whether it is above its 50-day avg
  4. QUIET/LOUD   today's volume against its OWN 50-day normal.
                  Measured 2026-07-27 over 7.5 years and 631,736
                  stock-days: a big up-day on 6x+ volume UNDERPERFORMS
                  the market over the next 20 days in 6 years out of 7.
                  Heavy volume means the news is already priced.
                  KPRMILL, 24 Jun 2026: +7.7% on 64x volume -- that was
                  the promoter selling 10.5m shares. It fell 15.6%.
  5. LIQUIDITY    50-day median turnover. Below Rs 5 crore a day you
                  cannot get a real position filled.
  6. VETO         split / bonus / rights -- the price scale changed, so
                  the % move is a lie (the JLHL 2:10 case, read as -80%)

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
  - It does not buy anything. It produces a list.
  - It does not filter hard. A screener working beside a human should
    MISS NOTHING; showing eight names when three are worth it costs
    thirty seconds, missing TMB costs the trade. This is the opposite
    of momentum_universe's tight top-25 lock, which is how the good
    ones got dropped.

THE KNOWN HOLE
--------------
The calendar knows WHO reported. It does not know whether the numbers
were GOOD. On 2026-07-27 both groups had results events -- KFINTECH
reported and rose 9.2%, ACUTAAS reported the same week and fell. Until
per-quarter QoQ figures are stored (task: stock memory with QoQ), the
RESULTS score means "worth a look", not "worth buying". Do not read it
as more than that.

Usage:
    python -m tools.shortlist                  # today
    python -m tools.shortlist --date 2026-07-27
    python -m tools.shortlist --top 40

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import collections
import sqlite3
import statistics
from datetime import datetime, timedelta

DAILY_DB = "data/daily_candles.db"
INTRADAY_DB = "data/backtest_candles.db"
RESULTS_DB = "data/results_calendar.db"
MEMORY_DB = "data/stock_memory.db"

MIN_TURNOVER = 5e7          # Rs 5 crore/day median -- fillable
QUIET_MAX = 1.5             # volume ratio at or under this = "quiet"
LOUD_MIN = 6.0              # at or over this = "already crowded"
RESULTS_WINDOW_BACK = 5     # a result 3 days old still moves a stock
RESULTS_WINDOW_FWD = 3      # and one due in 2 days already does


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


# ----------------------------------------------------------
# INPUTS
# ----------------------------------------------------------

def todays_prices(date):
    """{symbol: (open, close, volume)} from the live recorder. Falls back
    to the daily store when the session was not recorded."""
    out = {}
    try:
        c = _ro(INTRADAY_DB)
        rows = c.execute(
            "select symbol, min(minute), max(minute), sum(coalesce(v,0)) "
            "from candles where date=? group by symbol", (date,)).fetchall()
        for sym, lo, hi, vol in rows:
            o = c.execute("select o from candles where symbol=? and minute=?",
                          (sym, lo)).fetchone()
            cl = c.execute("select c from candles where symbol=? and minute=?",
                           (sym, hi)).fetchone()
            if o and cl:
                out[sym] = (o[0], cl[0], vol)
    except sqlite3.Error:
        pass
    if out:
        return out
    try:
        c = _ro(DAILY_DB)
        for sym, o, cl, v in c.execute(
                "select symbol,open,close,volume from daily_bars where date=?",
                (date,)):
            out[sym] = (o, cl, v or 0)
    except sqlite3.Error:
        pass
    return out


def normals(before_date, lookback=50):
    """{symbol: (median_volume, median_turnover, ma50)} from the 50 daily
    bars BEFORE `before_date`. Strictly before -- using today's own bar to
    judge whether today is unusual would be circular."""
    c = _ro(DAILY_DB)
    rows = c.execute(
        "select symbol,date,close,volume from daily_bars where date<? "
        "order by symbol,date", (before_date,)).fetchall()
    by = collections.defaultdict(list)
    for s, d, cl, v in rows:
        by[s].append((cl, v or 0))
    out = {}
    for s, ser in by.items():
        w = ser[-lookback:]
        if len(w) < 20:
            continue
        vols = [v for _, v in w]
        out[s] = (statistics.median(vols) or 1,
                  statistics.median([cl * v for cl, v in w]) or 0,
                  sum(cl for cl, _ in w) / len(w))
    return out


def results_near(date):
    """{symbol: [(days_away, purpose)]} -- negative days = already out."""
    d0 = datetime.strptime(date, "%Y-%m-%d").date()
    lo = (d0 - timedelta(days=RESULTS_WINDOW_BACK)).isoformat()
    hi = (d0 + timedelta(days=RESULTS_WINDOW_FWD)).isoformat()
    out = collections.defaultdict(list)
    try:
        c = _ro(RESULTS_DB)
        for sym, rd, purpose in c.execute(
                "select symbol,results_date,purpose from results_events "
                "where results_date between ? and ?", (lo, hi)):
            days = (datetime.strptime(rd, "%Y-%m-%d").date() - d0).days
            out[sym].append((days, purpose or ""))
    except sqlite3.Error:
        pass
    return out


def actions_near(date):
    """{symbol: [(action_type, ex_date)]} from stock memory."""
    d0 = datetime.strptime(date, "%Y-%m-%d").date()
    lo = (d0 - timedelta(days=3)).isoformat()
    hi = (d0 + timedelta(days=30)).isoformat()
    out = collections.defaultdict(list)
    try:
        c = _ro(MEMORY_DB)
        for sym, at, ex in c.execute(
                "select symbol,action_type,ex_date from stock_actions "
                "where ex_date between ? and ?", (lo, hi)):
            out[sym].append((at, ex))
    except sqlite3.Error:
        pass
    return out


# ----------------------------------------------------------
# RANKING
# ----------------------------------------------------------

VETO_ACTIONS = {"SPLIT", "BONUS", "RIGHTS", "DEMERGER"}


def build(date, top=25):
    prices = todays_prices(date)
    norm = normals(date)
    res = results_near(date)
    acts = actions_near(date)

    rows = []
    thin = []                      # moved, but too illiquid to fill
    for sym, (o, cl, vol) in prices.items():
        if sym not in norm or not o:
            continue
        med_v, med_t, ma50 = norm[sym]
        if med_t < MIN_TURNOVER:
            # Not silently dropped -- a mover you cannot fill is still
            # something the operator should know moved. DPABHUSHAN rose
            # 6.7% on 2026-07-27 and vanished from the first version of
            # this list without a word.
            if abs((cl - o) / o * 100) >= 4.0:
                thin.append((sym, (cl - o) / o * 100, med_t))
            continue

        veto = [a for a, _ in acts.get(sym, []) if a in VETO_ACTIONS]
        move = (cl - o) / o * 100
        vratio = vol / med_v if med_v else 0
        above_ma = cl > ma50

        why = []

        # ---------------------------------------------------------
        # MOVEMENT IS THE RANK. Everything else describes it.
        #
        # 2026-07-27, first version of this file got this backwards. It
        # scored "quiet volume" as a positive and pushed TMB -- up 12.1%
        # on the day it reported advances +27% YoY -- down to rank 45,
        # because it traded 39x its normal volume. SENCO to rank 424.
        #
        # The quiet-volume finding is real, but it answers a DIFFERENT
        # question: "if I buy after a 5% up day, does it keep running for
        # 20 days?" That is a holding decision. This file answers "does
        # this deserve thirty seconds of the operator's attention?" and
        # for that, a 12% move on results day is the single most
        # important thing on the board regardless of volume.
        #
        # So: size of the move ranks. Volume character is printed as a
        # NOTE for the human to weigh, never as a score.
        # ---------------------------------------------------------
        score = abs(move) if abs(move) >= 2.0 else 0.0
        if move >= 2.0:
            why.append(f"up {move:.1f}%")
        elif move <= -2.0:
            why.append(f"DOWN {move:.1f}%")

        # --- reason: results ---
        for days, purpose in sorted(res.get(sym, [])):
            tag = ("results out" if days < 0 else
                   "REPORTING TODAY" if days == 0 else "results due")
            when = ("today" if days == 0 else
                    f"{abs(days)}d ago" if days < 0 else f"in {days}d")
            why.append(f"{tag} {when}")
            score += 4.0 if days <= 0 else 2.0

        # --- reason: corporate action (informational, not a veto) ---
        for a, ex in acts.get(sym, []):
            if a not in VETO_ACTIONS:
                why.append(f"{a.lower()} ex-{ex}")
                score += 1.0

        if above_ma:
            score += 1.0
        else:
            why.append("below 50d avg")

        # --- volume character: a NOTE, not a score ---
        if vratio <= QUIET_MAX:
            why.append(f"quiet {vratio:.1f}x -- market may not have noticed yet")
        elif vratio >= LOUD_MIN:
            why.append(f"CROWDED {vratio:.0f}x -- news likely already priced")
        else:
            why.append(f"vol {vratio:.1f}x")

        # Nothing happened and no reason to look -- not worth a line.
        if score < 2.0:
            continue

        rows.append(dict(symbol=sym, score=score, move=move, vratio=vratio,
                         turnover=med_t, veto=veto, why=why))

    rows.sort(key=lambda r: -r["score"])
    thin.sort(key=lambda x: -abs(x[1]))
    return rows[:top], len(prices), len(rows), thin


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--top", type=int, default=25)
    a = p.parse_args()

    rows, scanned, eligible, thin = build(a.date, a.top)
    print(f"\nSHORTLIST for {a.date}")
    print(f"scanned {scanned} symbols -> {eligible} worth a line "
          f"-> showing top {len(rows)}\n")
    print(f"{'#':<4}{'symbol':<13}{'score':>6}{'move':>8}  why")
    print("-" * 108)
    for i, r in enumerate(rows, 1):
        flag = "  [VETO: " + ",".join(r["veto"]) + "]" if r["veto"] else ""
        print(f"{i:<4}{r['symbol']:<13}{r['score']:>6.1f}{r['move']:>7.1f}%"
              f"  {', '.join(r['why'])}{flag}")
    if thin:
        print(f"\nMOVED BUT TOO THIN TO FILL (under Rs {MIN_TURNOVER/1e7:.0f} "
              f"crore a day) -- shown so they don't vanish silently:")
        for sym, mv, t in thin[:10]:
            print(f"    {sym:<13}{mv:>7.1f}%   normally Rs {t/1e7:.2f} cr/day")


if __name__ == "__main__":
    main()
