"""---- 20,962 REFUSALS AND NOT ONE NAME. 31 August 2026. ----

    "fix that refusals table so i can see why. i didn't understand why
     bot can't see the stocks or any other thing . literally i'm
     loosing my control & frustated"

He asked why the bot took none of 31 August's twelve best stocks --
DIFFNKG +16.9%, PRUDENT +10.1%, MANALIPETC +9.9% and nine more. The
answer was in the store and unreadable: 20,962 refusal rows for the
day, every one anonymous, the largest reading

    "no event -- not evaluated"   99

and never saying which 99.

WHAT WAS ACTUALLY WRONG
-----------------------
Nothing was failing to record the symbols. core/ranker.py line 696
writes refused_by_symbol[name] for every stock it skips for want of a
reason, and returns it at line 1135. dashboard/state.py reads it to
paint the Live tab.

And the ONE line that writes into the store passed the anonymous census
instead. So "which stocks, and why" was computed every cycle, shown on
screen for as long as the page stayed open, and thrown away.

The same family of mistake as the order-flow that fed nothing,
lag_summary() with no callers, and LIVE_ALLOW_BOT_ENTRIES documented in
three files and implemented in none: the work was done, and the last
short step to where it would be useful was missing.
"""

import sqlite3

import pytest

from core.decision_log import DecisionLog


@pytest.fixture
def log(tmp_path, monkeypatch):
    import core.decision_log as dl
    monkeypatch.setattr(dl, "DB_PATH", str(tmp_path / "decisions.db"),
                        raising=False)
    made = DecisionLog(db_path=str(tmp_path / "decisions.db"))
    assert made._ready, "the test store did not open"
    return made


# ------------------------------------------------- both shapes, one call

def test_a_named_refusal_keeps_its_stock(log):
    """{symbol: reason} -- the shape the ranker produces."""
    log.record_refusals({"DIFFNKG": "no event behind it -- the tape is "
                                    "not a reason"})
    rows = log.refused_symbols()
    assert [r["symbol"] for r in rows] == ["DIFFNKG"]
    assert "no event behind it" in rows[0]["detail"]


def test_a_counted_refusal_still_works(log):
    """{reason: count} -- the census shape. It must not be broken by
    supporting the other one; both producers are live."""
    log.record_refusals({"no event -- not evaluated": 99})
    assert log.refused_symbols() == [], "a census has no stock to name"


def test_both_shapes_in_one_call(log):
    """Which is exactly what dashboard/state.py now hands over: the
    census merged with the per-stock dict."""
    log.record_refusals({
        "no event -- not evaluated": 99,
        "DIFFNKG": "no event behind it -- the tape is not a reason",
        "PRUDENT": "no event behind it -- the tape is not a reason",
    })
    got = {r["symbol"] for r in log.refused_symbols()}
    assert got == {"DIFFNKG", "PRUDENT"}


def test_the_same_stock_all_day_is_one_row(log):
    """He said duplicates are not acceptable. A stock refused every
    cycle is ONE row with a count, not one row per cycle."""
    for _ in range(40):
        log.record_refusals({"DIFFNKG": "no event behind it"})
    rows = log.refused_symbols()
    assert len(rows) == 1
    assert rows[0]["cycles"] == 40


def test_a_changing_number_does_not_make_a_new_row(log):
    """The live percentage used to be baked into the reason text, and
    the table is keyed on that text -- so every tick made a new row.
    92 rows for a handful of stocks on 31 August."""
    for pct in (7.2, 7.3, 7.4, 7.1, 6.9):
        log.record_refusals({"ZEEL": f"down {pct}% -- not moving up enough"})
    rows = log.refused_symbols()
    assert len(rows) == 1, [r["detail"] for r in rows]
    assert rows[0]["cycles"] == 5
    assert "6.9" in rows[0]["detail"], "it should show the LATEST reading"


# ------------------------------------------------------ the wiring itself

def test_the_dashboard_hands_over_the_symbols():
    """The whole bug was here, and it was one line. Without this the
    store fills with anonymous counts again and 'why was DIFFNKG not
    traded' has no answer -- while the Live tab keeps showing it, which
    is what made it so hard to notice."""
    from pathlib import Path

    src = Path("dashboard/state.py").read_text(encoding="utf-8")
    assert 'refusals.update(got.get("refused_by_symbol") or {})' in src, (
        "state.py no longer passes the per-stock refusals -- every "
        "refusal goes back to being anonymous")


def test_the_ranker_still_produces_them():
    """The other half of the junction. If the ranker stops returning
    the dict, the line above silently passes nothing and the store goes
    quiet without a single error."""
    from pathlib import Path

    src = Path("core/ranker.py").read_text(encoding="utf-8")
    assert '"refused_by_symbol": dict(refused_by_symbol)' in src


# ------------------------------------------------------------- the tool

def test_why_not_separates_refused_from_never_seen():
    """"refused" and "no record" are different answers. Printing them
    the same way is how 20,962 rows managed to say nothing."""
    from pathlib import Path

    src = Path("tools/why_not.py").read_text(encoding="utf-8")
    assert "never reached the decision path" in src
    assert "Refused, and why" in src
