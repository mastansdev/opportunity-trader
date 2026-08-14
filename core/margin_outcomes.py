"""
==========================================================
Did SECTOR-WIDE MARGIN ever pay? Measured, not argued.
==========================================================

    "pls start that . wire"
                                -- operator, 12 August 2026

core/margin_driver.py draws a chip. That is all it does. Whether the
chip is worth anything is this module's question, and until it answers
the chip stays exactly what ONE-OFF was before it earned a number: a
line on the screen with no claim attached.

    "It only becomes a rule if it earns one against real outcomes."
                                -- core/result_tag.py, 5 August 2026

WHY THIS DOES NOT READ THE EVENT TABLE
--------------------------------------
core/outcomes.py grades a chip off the STORED event, on purpose:

    "the panel's output depends on price, volume and the other events
     beside it, and mixing those in would measure the whole row"

SECTOR-WIDE MARGIN breaks that rule by design. It is a claim ABOUT the
other events beside it -- it says three companies printed the same
quarter. It cannot be read off one stored row, and the events table
never stored the figures anyway (detail is empty on all 2,775 RESULTs).

So it is rebuilt from data/telegram.db, which is where the figures have
been all along, using the same reader the panel uses. That is slower
and it is the only honest way to get an n before November.

WHAT IS MEASURED
----------------
Exactly what core/outcomes.py measures, with the same two objects, so
the numbers sit beside the existing table without translation:

    edge = the stock's move on the answering session
           MINUS the median move of everything that traded that day

and the buckets are the comparison that actually matters:

    POSITIVE + sector-wide     the PANAMAPET case
    POSITIVE, sector clean     the same chip without the warning
    POSITIVE, no reading       grid unreadable, kept separate

If the first bucket does not underperform the second, this chip is
noise and core/margin_driver.py should be deleted. That is a real
outcome and it is the expected one until the data says otherwise.

    python -m core.margin_outcomes

Author : H&M Opportunity Trader
==========================================================
"""

from __future__ import annotations

import os
import sqlite3
import statistics
from collections import defaultdict

from core import margin_driver
from core.outcomes import DAILY_DB, EVENTS_DB, MIN_SAMPLE, Baseline
from core.reaction import Reaction

TELEGRAM_DB = os.path.join("data", "telegram.db")

# A positive publisher read -- the only rows where this chip can matter.
_POSITIVE_GRADES = {"EXCELLENT", "GREAT", "GOOD"}


def _diag(msg):
    try:
        from core.logger import diagnostic
        diagnostic(msg)
    except Exception:                                      # noqa: BLE001
        pass


# ---------------------------------------------------------------
# REBUILD THE GRID, ONE REPORTING DAY AT A TIME
# ---------------------------------------------------------------
def _cards_for(con, symbol, upto, hours=36):
    """The raw channel text for one symbol in the window before `upto`."""
    from datetime import datetime, timedelta
    try:
        end = datetime.fromisoformat(str(upto).replace("Z", "+00:00"))
    except ValueError:
        return []
    start = (end - timedelta(hours=hours)).isoformat()
    rows = con.execute(
        "SELECT channel, text, ocr_text FROM messages "
        "WHERE symbols LIKE ? AND at >= ? AND at <= ? LIMIT 60",
        (f"%{symbol}%", start, str(upto))).fetchall()
    return [(str(r[0] or ""), " ".join(str(x or "") for x in (r[1], r[2])))
            for r in rows]


def verdicts(events_db=EVENTS_DB, telegram_db=TELEGRAM_DB, limit_days=None):
    """[{symbol, at, day, grade, driver, delta_pp, peers}] across history.

    One pass per reporting DAY, because the peer test needs every name
    that reported that day before it can say anything about any of them.
    """
    if not (os.path.exists(events_db) and os.path.exists(telegram_db)):
        return []

    try:
        from core import result_read, subject
    except Exception as exc:                               # noqa: BLE001
        _diag(f"[MARGIN] reader unavailable: {exc}")
        return []

    try:
        ev = sqlite3.connect(events_db)
        ev.row_factory = sqlite3.Row
        rows = ev.execute(
            "SELECT symbol, at, grade FROM events "
            "WHERE kind = 'RESULT' AND symbol IS NOT NULL "
            "AND at IS NOT NULL ORDER BY at").fetchall()
        ev.close()
    except sqlite3.Error as exc:
        _diag(f"[MARGIN] events: {exc}")
        return []

    by_day = defaultdict(list)
    for r in rows:
        by_day[str(r["at"])[:10]].append(dict(r))

    days = sorted(by_day)
    if limit_days:
        days = days[-limit_days:]

    out = []
    tg = sqlite3.connect(telegram_db)
    for day in days:
        # ---- pass 1: read every grid that reported this day ----
        read = {}
        for r in by_day[day]:
            sym = str(r["symbol"] or "").upper()
            if not sym or sym in read:
                continue
            try:
                cards = subject.only(sym, _cards_for(tg, sym, r["at"]))
                if not cards:
                    continue
                fields = result_read.read(cards)
            except Exception:                              # noqa: BLE001
                continue
            delta = margin_driver.margin_delta_pp(fields)
            if delta is None:
                continue
            read[sym] = {"fields": fields, "delta_pp": delta,
                         "at": r["at"], "grade": r["grade"]}

        if not read:
            continue

        grid = [{"symbol": s, "delta_pp": v["delta_pp"],
                 "sector": None, "at": day} for s, v in read.items()]

        # ---- pass 2: ask each one where its margin came from ----
        for sym, v in read.items():
            got = margin_driver.assess(sym, v["fields"], peers=grid)
            out.append({
                "symbol": sym, "at": v["at"], "day": day,
                "grade": str(v["grade"] or "").upper(),
                "delta_pp": round(v["delta_pp"], 1),
                "driver": (got or {}).get("driver") or "CLEAN",
                "peers": (got or {}).get("peers") or [],
            })
    tg.close()
    return out


# ---------------------------------------------------------------
# PRICE THEM
# ---------------------------------------------------------------
def measure(events_db=EVENTS_DB, daily_db=DAILY_DB,
            telegram_db=TELEGRAM_DB, limit_days=None):
    """{bucket: {n, edge_median, edge_mean, up_pct, enough, sample}}.

    Same `edge` as core/outcomes.measure() -- the move minus the
    market's median that session -- so the rows are comparable.
    """
    rows = verdicts(events_db, telegram_db, limit_days)
    if not rows:
        return {"_unanswered": 0, "_read": 0}

    reaction = Reaction(db_path=daily_db)
    baseline = Baseline(db_path=daily_db)

    buckets = defaultdict(list)
    unanswered = 0
    for r in rows:
        positive = r["grade"] in _POSITIVE_GRADES
        if r["driver"] == "SECTOR_WIDE":
            label = "POSITIVE + sector-wide" if positive else "sector-wide, not positive"
        elif r["driver"] == "PRICE":
            label = "POSITIVE + margin=price" if positive else "margin=price, not positive"
        else:
            label = "POSITIVE, sector clean" if positive else "clean, not positive"

        move, on_date = reaction.move_after(r["symbol"], r["at"])
        if move is None:
            unanswered += 1
            continue
        market = baseline.median_move(on_date)
        if market is None:
            continue
        edge = round(move - market, 3)
        buckets[label].append((r["symbol"], on_date, move, edge, r["peers"]))

    out = {}
    for label, hits in buckets.items():
        edges = [h[3] for h in hits]
        out[label] = {
            "n": len(edges),
            "edge_median": round(statistics.median(edges), 2),
            "edge_mean": round(statistics.fmean(edges), 2),
            "up_pct": round(100.0 * sum(1 for e in edges if e > 0) / len(edges), 1),
            "enough": len(edges) >= MIN_SAMPLE,
            "sample": sorted(hits, key=lambda h: -abs(h[3]))[:3],
        }
    out["_unanswered"] = unanswered
    out["_read"] = len(rows)
    return out


def report(**kw):
    """The table, and the one sentence the table supports."""
    got = measure(**kw)
    read = got.pop("_read", 0)
    unanswered = got.pop("_unanswered", 0)

    lines = [
        "=" * 72,
        " SECTOR-WIDE MARGIN -- does the warning pay?",
        "=" * 72,
        f" grids rebuilt from telegram.db : {read}",
        f" no answering session yet       : {unanswered}",
        "",
        f" {'bucket':<28}{'n':>5}{'edge':>9}{'up%':>8}   verdict",
        " " + "-" * 68,
    ]
    order = ["POSITIVE + sector-wide", "POSITIVE + margin=price",
             "POSITIVE, sector clean"]
    for label in order + [k for k in got if k not in order]:
        row = got.get(label)
        if not row:
            continue
        verdict = "measured" if row["enough"] else f"n<{MIN_SAMPLE}, no claim"
        lines.append(f" {label:<28}{row['n']:>5}{row['edge_median']:>+9.2f}"
                     f"{row['up_pct']:>8.1f}   {verdict}")

    warned = got.get("POSITIVE + sector-wide")
    clean = got.get("POSITIVE, sector clean")
    lines.append("")
    if warned and clean and warned["enough"] and clean["enough"]:
        gap = warned["edge_median"] - clean["edge_median"]
        if gap < -0.3:
            lines.append(f" The warning is worth {abs(gap):.2f}pp. It has earned a rule.")
        elif gap > 0.3:
            lines.append(f" Warned names did BETTER by {gap:.2f}pp. Delete the chip.")
        else:
            lines.append(f" Gap is {gap:+.2f}pp. Nothing here. Keep drawing, keep counting.")
    else:
        w_n = warned["n"] if warned else 0
        c_n = clean["n"] if clean else 0
        lines.append(f" warned n={w_n}, control n={c_n}, floor {MIN_SAMPLE}.")
        if warned and warned["enough"] and not (clean and clean["enough"]):
            # The trap this module exists to avoid. The warned bucket is
            # big enough to describe ON ITS OWN, and describing it alone
            # is how a chip acquires a reputation it never earned.
            lines.append(f" The warned bucket is measurable ({warned['edge_median']:+.2f}, "
                         f"up {warned['up_pct']:.0f}%) but the CONTROL is not.")
            lines.append(" A number without its comparison is not a finding.")
            if warned["edge_median"] > 0:
                lines.append("")
                lines.append(" NOTE: warned names still made money. Whatever this chip"
                             " is,")
                lines.append("       it is NOT a skip signal. Do not let it become one.")
        else:
            lines.append(" NO CLAIM EITHER WAY.")
        lines.append(" The chip stays unmeasured and must not change any tag.")
    lines.append("=" * 72)
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
