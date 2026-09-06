"""
==========================================================
The bot marks its own homework
==========================================================

    "yes - self performance upgrade, self improving"
    "again why manual runs? why can't bot do itself."
                        -- the operator, 6 Sep and 4 August 2026

A FIXED SET OF QUESTIONS, ASKED OF ITS OWN BOOK EVERY NIGHT, and the
answers kept so tonight's can be read against last week's. That last
part is the self-improving half: one night's answer is a fact, ten
nights of the same answer is a finding, and an answer that flips every
night was never real.

THE FIRST QUESTION IS THE ONE THAT MATTERS. Measured 6 September on
his own book:

    day        trades   day total   best two   ALL THE REST
    1 Sep           5      -6,090        145        -6,235
    2 Sep           6      -6,376        124        -6,500
    3 Sep          21       1,870      4,993        -3,123
    4 Sep          27      11,794     24,676       -12,882

Every single day, everything except the best two trades lost money.
Friday's profit IS NIACL and PURVA. So the day's P&L cannot measure
whether the bot is improving -- it measures whether a big mover turned
up. THE REST is the number that can only be moved by getting better,
and it is asked first here for that reason.

EVERY NUMBER NEEDS AN n, and a question with too few cases says so
rather than answering. His rule, and the reason MIN_CASES exists:
every parameter fitted on 18-27 August died on the eleven sessions it
had not seen.

NOTHING IS AVERAGED ACROSS STOCKS. Counts and rupee totals only --
"11 up, 6 down, together +21,052" -- because a mean across names is
the thing he has said repeatedly is not how a market works. Where a
group is small the stocks are named outright.

IT DECIDES NOTHING. No gate imports this; a test enforces it. It
produces the table, and he changes the setting.

WHAT IS NOT ANSWERABLE YET, and says so plainly: move_age_min,
run_up_pct, reason_kind, reason_pct_of_company and mcap_band began
recording on 6 September 2026, so every trade before that carries a
blank. Those questions light up on their own once the book has enough.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta

from core.logger import decision, diagnostic

TRADES_DB = os.path.join("data", "trade_memory.db")
DB_PATH = os.path.join("data", "self_review.db")

# His rule: a number without an n is not a number. Twenty is the same
# bar core/opportunity.PAYOFF_MIN_CASES uses, on purpose -- one idea,
# one threshold.
MIN_CASES = 20

# How far back each night's questions look.
WINDOW_DAYS = 30


def _trades(since, db_path=None):
    """Every closed trade in the window, newest last."""
    try:
        conn = sqlite3.connect("file:" + (db_path or TRADES_DB)
                               + "?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trade_memory WHERE trade_date >= ? "
            "ORDER BY trade_date, entry_time", (since,)).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[REVIEW] could not read the book ({exc})")
        return []
    return [dict(r) for r in rows]


def _split(rows, key):
    """{value: [rows]} for one column, skipping rows that lack it."""
    out = {}
    for row in rows:
        got = row.get(key)
        if got is None or got == "":
            continue
        out.setdefault(str(got), []).append(row)
    return out


def _tally(rows):
    """Counts and a rupee total. Never an average across stocks."""
    up = [r for r in rows if (r.get("pnl") or 0) > 0]
    down = [r for r in rows if (r.get("pnl") or 0) < 0]
    return {"n": len(rows), "up": len(up), "down": len(down),
            "total": round(sum(r.get("pnl") or 0 for r in rows), 2)}


# ------------------------------------------------------------------
# the questions
# ------------------------------------------------------------------

def q_the_rest(rows):
    """What did each day make WITHOUT its best two trades?

    The only number here that cannot be won by luck.
    """
    by_day = {}
    for row in rows:
        by_day.setdefault(row.get("trade_date"), []).append(row)
    days = []
    for day in sorted(by_day):
        pnls = sorted((r.get("pnl") or 0) for r in by_day[day])
        total = sum(pnls)
        rest = total - sum(pnls[-2:])
        days.append({"day": day, "trades": len(pnls),
                     "total": round(total, 2), "rest": round(rest, 2)})
    bled = [d for d in days if d["rest"] < 0]
    return {
        "question": "what did each day make without its best two trades",
        "enough": bool(days),
        "n": len(days),
        "days": days,
        "answer": (f"{len(bled)} of {len(days)} day(s) lost money on "
                   f"everything except their best two trades"
                   if days else "no days on file"),
    }


def _by_column(rows, key, label):
    """One line per value of a column -- door, band, reason kind."""
    groups = _split(rows, key)
    if not groups:
        return {"question": f"which {label} paid",
                "enough": False, "n": 0,
                "answer": (f"nothing recorded yet -- {key} began being "
                           f"written on 6 September 2026")}
    lines = []
    for value, got in sorted(groups.items(),
                             key=lambda kv: -_tally(kv[1])["total"]):
        tally = _tally(got)
        tally["value"] = value
        if tally["n"] < MIN_CASES:
            tally["names"] = sorted({r.get("symbol") for r in got})[:8]
        lines.append(tally)
    seen = sum(l["n"] for l in lines)
    return {
        "question": f"which {label} paid",
        "enough": seen >= MIN_CASES,
        "n": seen,
        "groups": lines,
        "answer": (f"{len(lines)} kind(s) on file across {seen} trade(s)"
                   + ("" if seen >= MIN_CASES
                      else f" -- under {MIN_CASES}, so this is a list, "
                           f"not a finding")),
    }


def q_which_door(rows):
    return _by_column(rows, "door", "door")


def q_which_size(rows):
    return _by_column(rows, "mcap_band", "size of company")


def q_which_reason(rows):
    return _by_column(rows, "reason_kind", "kind of reason")


def q_how_late(rows):
    """Did arriving late cost anything?

    Friday 4 September, reconstructed by hand: seven entries more than
    thirty minutes after the move began, none of them a winner,
    together -15,083. That could not be asked from the book because
    nothing recorded it. Now it can.
    """
    got = [r for r in rows if r.get("move_age_min") is not None]
    if not got:
        return {"question": "did arriving late cost anything",
                "enough": False, "n": 0,
                "answer": ("nothing recorded yet -- move_age_min began "
                           "being written on 6 September 2026")}
    early = [r for r in got if (r.get("move_age_min") or 0) <= 30]
    late = [r for r in got if (r.get("move_age_min") or 0) > 30]
    return {
        "question": "did arriving late cost anything",
        "enough": len(got) >= MIN_CASES,
        "n": len(got),
        "early": _tally(early),
        "late": _tally(late),
        "answer": (f"within 30 min: {_tally(early)['total']:,.0f} · "
                   f"later: {_tally(late)['total']:,.0f}"
                   + ("" if len(got) >= MIN_CASES
                      else f" -- under {MIN_CASES} trades, not a finding")),
    }


def q_how_far_it_had_run(rows):
    """Did it matter how far the stock had already gone?

    Measured on Friday and it separated NOTHING -- RESPONIND had used
    3.7 of its own normal days and lost, RADHIKAJWE 3.5 and won. Asked
    anyway, forward, because one day is not an answer either way.
    """
    got = [r for r in rows if r.get("run_up_pct") is not None]
    if not got:
        return {"question": "did it matter how far it had already run",
                "enough": False, "n": 0,
                "answer": ("nothing recorded yet -- run_up_pct began "
                           "being written on 6 September 2026")}
    small = [r for r in got if (r.get("run_up_pct") or 0) <= 5.0]
    big = [r for r in got if (r.get("run_up_pct") or 0) > 5.0]
    return {
        "question": "did it matter how far it had already run",
        "enough": len(got) >= MIN_CASES,
        "n": len(got),
        "up_to_5pct": _tally(small),
        "over_5pct": _tally(big),
        "answer": (f"up to 5%: {_tally(small)['total']:,.0f} · "
                   f"over 5%: {_tally(big)['total']:,.0f}"
                   + ("" if len(got) >= MIN_CASES
                      else f" -- under {MIN_CASES} trades, not a finding")),
    }


def q_how_it_ended(rows):
    """Which exit reason gave the money back?"""
    return _by_column(rows, "exit_reason", "exit")


QUESTIONS = (q_the_rest, q_which_door, q_how_late, q_how_far_it_had_run,
             q_which_size, q_which_reason, q_how_it_ended)


# ------------------------------------------------------------------
# asking, keeping, and reading back
# ------------------------------------------------------------------

def ask(now=None, since_days=WINDOW_DAYS, db_path=None):
    """Put every question to the book. Never raises."""
    today = now or datetime.now()
    if isinstance(today, datetime):
        today = today.date()
    since = (today - timedelta(days=since_days)).isoformat()
    rows = _trades(since, db_path)
    out = []
    for question in QUESTIONS:
        try:
            out.append(question(rows))
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[REVIEW] {question.__name__} failed: {exc}")
    return {"day": today.isoformat(), "trades": len(rows),
            "since": since, "answers": out}


def _connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY, day TEXT, question TEXT,
            enough INTEGER, n INTEGER, answer TEXT, detail TEXT,
            recorded_at TEXT)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_review "
                 "ON reviews (day, question)")
    conn.commit()
    return conn


def keep(got=None, store=None, **kw):
    """Write tonight's answers down, so trends can be read later."""
    got = got or ask(**kw)
    written = 0
    try:
        conn = _connect(store)
        for answer in got["answers"]:
            conn.execute(
                "INSERT OR REPLACE INTO reviews (day, question, enough, "
                "n, answer, detail, recorded_at) VALUES (?,?,?,?,?,?,?)",
                (got["day"], answer["question"],
                 1 if answer.get("enough") else 0, answer.get("n", 0),
                 str(answer.get("answer"))[:400],
                 json.dumps(answer, default=str)[:4000],
                 datetime.now().isoformat(timespec="seconds")))
            written += 1
        conn.commit()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[REVIEW] could not keep tonight's answers ({exc})")
        return 0
    return written


def trend(question, limit=10, store=None):
    """The same question's answer over the last nights.

    The self-improving half: an answer that says the same thing ten
    nights running is worth acting on; one that flips every night was
    never real.
    """
    try:
        conn = _connect(store)
        rows = conn.execute(
            "SELECT day, n, enough, answer FROM reviews WHERE question = ? "
            "ORDER BY day DESC LIMIT ?", (question, limit)).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[REVIEW] could not read the trend ({exc})")
        return []
    return [{"day": d, "n": n, "enough": bool(e), "answer": a}
            for d, n, e, a in rows]


def report(got=None, **kw):
    """The night's answers as lines to print."""
    got = got or ask(**kw)
    lines = [f"THE BOT'S OWN REVIEW -- {got['trades']} trade(s) since "
             f"{got['since']}"]
    for answer in got["answers"]:
        mark = "  " if answer.get("enough") else "? "
        lines.append(f"{mark}{answer['question']}:")
        lines.append(f"      {answer.get('answer')}")
        for day in answer.get("days", [])[-6:]:
            lines.append(f"        {day['day']}  {day['trades']:>3} trades  "
                         f"day {day['total']:>10,.0f}   "
                         f"without its best two {day['rest']:>10,.0f}")
        for group in answer.get("groups", [])[:8]:
            names = group.get("names")
            lines.append(f"        {str(group['value'])[:22]:<24}"
                         f"{group['n']:>4} trades  {group['up']:>3} up  "
                         f"{group['down']:>3} down  {group['total']:>10,.0f}"
                         + (f"   {', '.join(names)}" if names else ""))
    return lines


def run(store=None, **kw):
    """Ask, print, and keep. Called at the close by main.py."""
    got = ask(**kw)
    for line in report(got):
        decision(line)
    keep(got, store=store)
    return got
