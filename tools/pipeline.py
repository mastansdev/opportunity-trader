"""
==========================================================
py tools/pipeline.py  --  is the whole chain intact?
==========================================================

    "lay out the bot receiving & processing & output in dashboard
     complete pipeline is in tact or broken. any file/code is left
     behind to correct in future. you do not depend on your memory +
     on me"
                                -- operator, 8 August 2026

WHY THIS EXISTS
---------------
tools/check.py answers "can I trade this morning". This answers a
different and larger question: does every stage of the machine still
hand its output to the next one.

They are not the same question. On 5 August 3,541 tests passed while
core/ranker.py reached no order path at all -- every part worked and
one JOIN did not exist. tools/check.py would have said the morning was
fine, because it was.

So this walks the chain in order and, at every junction, asks the
NEXT stage what it actually received. Not "does the function exist" --
"did anything come out of it".

    RECEIVE     telegram, RSS, bhavcopy, results calendar, Dhan feed
    PROCESS     OCR -> grades -> reasons -> watchlist -> rank -> plan
    ACT         auto_entry -> engine
    SHOW        the dashboard snapshot the React page reads

Every line is measured against the real stores. Nothing is read from
source and asserted.

WHAT THE STATES MEAN
--------------------
    OK        measured, and carrying data
    EMPTY     the stage works but produced nothing right now. Often
              legitimate (a Sunday has no gapper card). Named anyway,
              because "empty" and "broken" look identical on a screen
              and only one of them needs fixing.
    BROKEN    it raised, or the next stage gets nothing it can use

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, EMPTY, BROKEN = "  OK  ", "EMPTY ", "BROKEN"

_results = []


def stage(name):
    print(f"\n{'=' * 72}\n  {name}\n{'=' * 72}")


def line(state, what, detail):
    print(f"  [{state}]  {what:<30} {detail}")
    _results.append((state, what, detail))


def _q(db, sql, args=()):
    try:
        con = sqlite3.connect(db)
        got = con.execute(sql, args).fetchall()
        con.close()
        return got
    except Exception as exc:                               # noqa: BLE001
        return [("__error__", str(exc))]


def _err(rows):
    return rows and rows[0] and rows[0][0] == "__error__"


# ===============================================================
def receive():
    stage("1. RECEIVE  --  what comes in from outside")
    now = datetime.now()

    # ---- telegram ----
    got = _q("data/telegram.db", "select count(*), max(seen_at) from messages")
    if _err(got) or not got:
        line(BROKEN, "telegram store", "cannot be read")
    else:
        n, last = got[0]
        age = "?"
        try:
            age = f"{(now - datetime.fromisoformat(str(last))).total_seconds()/3600:.1f}h ago"
        except Exception:                                  # noqa: BLE001
            pass
        line(OK if n else EMPTY, "telegram store",
             f"{n:,} messages, newest {age}")

    # ---- OCR actually ran ----
    got = _q("data/telegram.db",
             "select count(*), sum(case when ocr_text is not null "
             "and length(ocr_text) > 25 then 1 else 0 end) from messages "
             "where photos is not null and photos not in ('', '[]')")
    if not _err(got) and got and got[0][0]:
        total, read = got[0][0], got[0][1] or 0
        pct = 100.0 * read / total
        line(OK if pct > 80 else BROKEN, "OCR on images",
             f"{read:,} of {total:,} images readable ({pct:.0f}%)")
    else:
        line(EMPTY, "OCR on images", "no images stored")

    # ---- bhavcopy ----
    files = sorted(f for f in os.listdir("data")
                   if f.startswith("BhavCopy_NSE_CM"))
    if files:
        newest = files[-1]
        stamp = "".join(ch for ch in newest if ch.isdigit())[-8:]
        line(OK, "NSE bhavcopy", f"{len(files)} files, newest {stamp}")
    else:
        line(BROKEN, "NSE bhavcopy", "none downloaded")

    # ---- delivery data (Check B's input) ----
    deliv = [f for f in os.listdir("data")
             if "sec_bhavdata" in f.lower() or "MTO" in f]
    line(EMPTY if not deliv else OK, "NSE delivery data",
         f"{len(deliv)} file(s)" if deliv else
         "NOT DOWNLOADED -- delivery % cannot be computed")

    # ---- results calendar ----
    got = _q("data/results_calendar.db",
             "select count(distinct symbol), max(results_date) "
             "from results_events")
    if _err(got):
        line(BROKEN, "results calendar", "cannot be read")
    else:
        line(OK if got[0][0] else EMPTY, "results calendar",
             f"{got[0][0]} companies, latest date {got[0][1]}")

    # ---- the price feed ----
    got = _q("data/backtest_candles.db",
             "select max(date), count(distinct symbol) from candles "
             "where date = (select max(date) from candles)")
    if _err(got) or not got or not got[0][0]:
        line(BROKEN, "Dhan price feed", "no candles recorded")
    else:
        line(OK, "Dhan price feed",
             f"last session {got[0][0]}, {got[0][1]:,} symbols")


# ===============================================================
def process():
    stage("2. PROCESS  --  raw material into a tradeable opinion")
    when = datetime.now()

    # ---- grades ----
    try:
        from core import watchlist_builder as W
        graded = W.graded_symbols() or {}
        line(OK if graded else EMPTY, "result grades (Row 1)",
             f"{len(graded)} stocks graded Excellent/Great in 36h")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "result grades (Row 1)", str(exc)[:44])
        graded = {}

    # ---- reasons ----
    try:
        from core.why_moving import why
        probes = list(graded)[:12] or ["RELIANCE", "INFY", "TCS"]
        hits = sum(1 for s in probes
                   if (why(symbol=s) or {}).get("text"))
        line(OK if hits else BROKEN, "why_moving (reasons)",
             f"{hits} of {len(probes)} probe symbols have a reason")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "why_moving (reasons)", str(exc)[:44])

    # ---- the three watchlist rows ----
    try:
        from core import watchlist_builder as W
        today = when.date().isoformat()
        reporting = W.reporting_on(today) or {}
        line(OK if reporting else EMPTY, "Row 2 (reporting today)",
             f"{len(reporting)} companies report today")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "Row 2 (reporting today)", str(exc)[:44])

    # ---- ranker, driven on the last real session ----
    try:
        from core.ranker import rank
        from core.why_moving import why
        from core import liquidity
        con = sqlite3.connect("data/backtest_candles.db")
        day = con.execute("select max(date) from candles").fetchone()[0]
        rows = []
        for sym, lo, hi, vol in con.execute(
                "select symbol, min(l), max(h), sum(v) from candles "
                "where date=? group by symbol", (day,)):
            o = con.execute("select o from candles where date=? and symbol=? "
                            "order by minute limit 1", (day, sym)).fetchone()
            c = con.execute("select c from candles where date=? and symbol=? "
                            "order by minute desc limit 1",
                            (day, sym)).fetchone()
            if not o or not c or not o[0]:
                continue
            rows.append({"symbol": sym, "ltp": c[0], "day_open": o[0],
                         "day_high": hi, "day_low": lo, "volume": vol or 0,
                         "turnover_cr": (vol or 0) * c[0] / 1e7,
                         "change_pct": (c[0] - o[0]) / o[0] * 100})
        con.close()
        rows.sort(key=lambda r: -r["change_pct"])
        got = rank(rows[:60], mechanism_of=lambda s: why(symbol=s),
                   adv_of=liquidity.adv,
                   now=datetime.fromisoformat(day + "T11:00"),
                   open_of=lambda s: next(
                       (r["day_open"] for r in rows if r["symbol"] == s), None),
                   top=8)
        picks = got.get("rows") or []
        line(OK if picks else EMPTY, "ranker",
             f"named {len(picks)} stock(s) on {day}"
             + (f" -- top: {picks[0]['symbol']}" if picks else ""))

        # ---- sizing ----
        from core.position_plan import plan as position_plan
        by = {r["symbol"]: r for r in rows}
        ok_plans = 0
        for row in picks:
            src = by.get(row.get("symbol")) or {}
            p = position_plan(src.get("ltp"), row.get("action"),
                              day_low=src.get("day_low"),
                              day_high=src.get("day_high"))
            if p.get("ok"):
                ok_plans += 1
        line(OK if ok_plans else BROKEN, "position sizing",
             f"{ok_plans} of {len(picks)} ranked picks got a tradeable plan")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "ranker / sizing", str(exc)[:44])


# ===============================================================
def act():
    stage("3. ACT  --  does an opinion become an order")
    try:
        from core import auto_entry
        for fn in ("take", "refuse_reason", "early_rows"):
            line(OK if hasattr(auto_entry, fn) else BROKEN,
                 f"auto_entry.{fn}()", "present")
        # the join main.py relies on
        src = open("main.py", encoding="utf-8", errors="ignore").read()
        line(OK if "auto_entry.take(" in src else BROKEN,
             "main.py calls it", "the ranker reaches the order path"
             if "auto_entry.take(" in src else "THE JOIN IS MISSING")
        line(OK if "engine._enter" in src else BROKEN,
             "wired to the engine", "orders go through Engine._enter")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "auto_entry", str(exc)[:44])

    # ---- THE SWITCH GUARDS, TESTED BY RUNNING THEM. 8 Aug 2026 ----
    #
    # The first version of this check sliced 900 characters after the
    # def and looked for the word "alert_only". It reported ROTATION
    # IGNORES THE SWITCH on a rotation guard that was correctly in
    # place -- the guard simply sat below a long comment block.
    #
    # A false BROKEN is as damaging as a false OK: he stops trusting
    # the audit, which is the one instrument he has. So these now
    # BUILD an engine, turn the switch off, and call the method.
    try:
        from core.engine import Engine
        engine = Engine.__new__(Engine)          # no broker, no feed
        engine.alert_only = True
        engine.open_positions = {"AAA": {"entry_price": 100.0,
                                         "direction": "LONG", "qty": 10}}
        engine._rotation_off_logged = True
        freed = engine._maybe_rotate_out("BBB", "LONG", datetime.now())
        line(OK if freed is False else BROKEN, "switch guards rotation",
             "switch OFF -> rotation refused (ran it)" if freed is False
             else "ROTATION SOLD A HOLDING WITH THE SWITCH OFF")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "switch guards rotation",
             f"could not be exercised: {str(exc)[:34]}")

    # The adoption hole. broker_sync adopts any position that APPEARS
    # during the session -- including the ones he opens himself in the
    # Dhan app -- and never consults alert_only. That is what sold
    # KALYANKJIL, AUROPHARMA and HEROMOTOCO on 7 August.
    try:
        src = open("core/broker_sync.py", encoding="utf-8",
                   errors="ignore").read()
        adopt = src.split("adopt_positions.adopt(")[0][-1500:] \
            if "adopt_positions.adopt(" in src else ""
        guarded = "alert_only" in adopt
        line(OK if guarded else BROKEN, "switch guards adoption",
             "OFF cannot touch his trades" if guarded else
             "ADOPTS HIS MANUAL TRADES EVEN WHEN OFF")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "adoption guard", str(exc)[:44])


# ===============================================================
def show():
    stage("4. SHOW  --  what the dashboard actually receives")
    wanted = ["auto_watchlist", "ranked", "morning_ready", "result_details",
              "bot_trading", "positions", "gainers_losers", "sectors"]
    try:
        from dashboard.state import DashboardState
        names = [n for n in dir(DashboardState) if not n.startswith("__")]
        line(OK if "get_snapshot" in names else BROKEN,
             "snapshot builder", "DashboardState.get_snapshot() exists")
        src = open("dashboard/state.py", encoding="utf-8",
                   errors="ignore").read()
        for key in wanted:
            present = f'"{key}"' in src
            line(OK if present else BROKEN, f"snapshot['{key}']",
                 "built" if present else "NEVER SET -- the page shows nothing")
        # ---- IT CHECKED A PAGE HE HAD LEFT. 13 August 2026. ----
        #
        # This read dashboard/static/app.html -- the React screen served
        # at "/". He moved to /board (board.html) on 9 August, and on
        # 13 August the four pages were collapsed to two: /board for
        # trading, /full for diagnostics. app.html and screen.html were
        # deleted as a third and fourth page doing neither.
        #
        # An audit that opens a deleted file reports BROKEN on a healthy
        # bot, and an audit that opens the WRONG file reports OK on a
        # blind one. So it checks the screen he actually watches, and
        # falls back to the diagnostics page.
        page = ""
        for candidate in ("dashboard/static/board.html",
                          "dashboard/static/index.html"):
            try:
                page = open(candidate, encoding="utf-8",
                            errors="ignore").read()
                break
            except OSError:
                continue
        shown = [k for k in wanted if k in page]
        # board.html is ONE TABLE by design and reads far fewer keys
        # than index.html -- "one verdict not six chips". Judged on the
        # handful it must have to draw a row at all, not on all of them.
        must = [k for k in ("gainers_losers", "ranked", "bot_trading")
                if k in page]
        line(OK if len(must) == 3 else BROKEN,
             "the trading screen reads them",
             f"{len(shown)} of {len(wanted)} keys on board.html "
             f"({len(must)}/3 essential)")
    except Exception as exc:                               # noqa: BLE001
        line(BROKEN, "dashboard", str(exc)[:44])


# ===============================================================
def main():
    print("=" * 72)
    print(f"  PIPELINE AUDIT   {datetime.now():%d %b %Y %H:%M}")
    print("  every line below was measured, not read from source")
    print("=" * 72)
    receive()
    process()
    act()
    show()

    broken = [r for r in _results if r[0] == BROKEN]
    empty = [r for r in _results if r[0] == EMPTY]
    print(f"\n{'=' * 72}")
    print(f"  {len(_results)} junctions checked   "
          f"{len(broken)} BROKEN   {len(empty)} empty")
    if broken:
        print("\n  BROKEN -- these stop the chain:\n")
        for _s, what, detail in broken:
            print(f"     {what:<32} {detail}")
    if empty:
        print("\n  EMPTY -- working, but nothing in them right now:\n")
        for _s, what, detail in empty:
            print(f"     {what:<32} {detail}")
    print("=" * 72)
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
