"""
==========================================================
The brain may name an opportunity. It may not trade one.
==========================================================

    "i want you to develop a brain memory module in to bot with self
     evaluating & learning to find the opportunity on based of the
     memory."                       -- operator, 16 August 2026

core/opportunity.py answers that. These tests exist because a module
which LEARNS is the easiest place in this repo for a quiet, expensive
mistake, and there are exactly three ways it could go wrong:

  1. It starts voting. Every other measurement layer here --
     core/trade_memory.py, core/outcomes.py, dashboard/chip_stats.py --
     is deliberately kept off the decision path, and his standing rule
     is blunt: "Entry, exit, target and trail are DEFINED RULES ... not
     to discover new ones from history." test_it_never_reaches_the_
     entry_path re-derives that from the source rather than trusting it.

  2. It states an average built on four cases. His floor, in his own
     words: "nothing concluded from fewer than 10 comparable cases."

  3. It infers direction from the TYPE. An FDA approval and a Form 483
     with eight observations match the same words and mean opposite
     things. A module that calls both bullish would be worse than one
     that recognised nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from core import opportunity as op

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------
# 1. RECOGNITION
# ---------------------------------------------------------------

def test_it_names_the_families_he_listed():
    """He named these by hand. Each must be recognisable."""
    cases = {
        "Cipla receives USFDA approval for its generic": "FDA_APPROVAL",
        "RVNL bags order worth Rs 1,200 cr": "ORDER_WIN",
        "Cabinet approves PLI scheme for electronics": "GOVT_SCHEME",
        "Board approves acquisition of 51% stake": "ACQUISITION",
        "US imposes anti-dumping duty on imports": "TARIFF_DUTY",
        "Escalation in the Middle East lifts freight": "GEOPOLITICS",
        "Company gets environmental clearance for the mine": (
            "REGULATORY_CLEARANCE"),
        "Brent crude slips, margin tailwind for OMCs": "COMMODITY_CYCLE",
        "New greenfield plant commissioned": "CAPACITY_EXPANSION",
    }
    for text, expected in cases.items():
        assert expected in op.keys(text), f"{expected} not found in {text!r}"


def test_one_story_may_be_two_opportunities():
    """"US tariff on steel imports lifts domestic mills" is a tariff
    story AND a commodity story. Collapsing it to one label throws
    away half the reason it moved."""
    got = op.keys("US tariff on steel imports lifts domestic mills, "
                  "steel price firm")
    assert "TARIFF_DUTY" in got
    assert "COMMODITY_CYCLE" in got


def test_every_hit_carries_the_phrase_it_matched():
    """A type is a label for RECALL, never the reason for a trade --
    core/ranker.py refuses keyword reasons by name. Carrying the
    matched phrase keeps that check possible downstream."""
    for hit in op.classify("Company bags order worth Rs 500 cr"):
        assert hit["matched"], f"{hit['key']} matched nothing quotable"
        assert hit["horizon"] in (op.SESSION, op.DAYS, op.QUARTERS)


def test_empty_and_junk_never_raise():
    for text in (None, "", "   ", "\n", "!!!", "a" * 5000):
        assert isinstance(op.classify(text), list)


# ---------------------------------------------------------------
# 2. DIRECTION COMES FROM THE SENTENCE, NEVER FROM THE TYPE
# ---------------------------------------------------------------

def test_an_approval_and_an_observation_are_not_the_same_news():
    """THE ONE THAT MATTERS MOST.

    Both match FDA_APPROVAL's words. One is a licence to sell a drug,
    the other is a regulator listing eight faults. A brain that calls
    both bullish is worse than no brain.
    """
    good = op.classify("Cipla receives USFDA approval for generic")
    bad = op.classify("Sun Pharma gets Form 483 with 8 observations "
                      "from USFDA")
    assert good[0]["key"] == bad[0]["key"] == "FDA_APPROVAL"
    assert good[0]["direction"] == op.UP
    assert bad[0]["direction"] == op.DOWN


def test_a_sentence_that_does_not_say_reads_UNKNOWN():
    """Unknown must stay unknown. core/ranker.py refuses UNKNOWN by
    name, which is the correct outcome for a sentence with no sign."""
    assert op.direction_hint("US imposes 25% tariff on steel imports") \
        == op.UNKNOWN
    assert op.direction_hint("") == op.UNKNOWN
    assert op.direction_hint("approval rejected") == op.UNKNOWN  # both


# ---------------------------------------------------------------
# 3. IT MAY NOT CONCLUDE FROM FOUR CASES
# ---------------------------------------------------------------

def test_a_thin_family_refuses_to_state_an_average(monkeypatch):
    """     "nothing concluded from fewer than 10 comparable cases.
              Say 'insufficient data' and state exactly what more is
              needed." """
    monkeypatch.setattr(op, "scan", lambda **k: {
        "available": True, "scanned": 3,
        "hits": [dict(key="ORDER_WIN", symbol="X", at="2026-08-01",
                      direction=op.UP)] * 3})
    monkeypatch.setattr(op, "_next_session_move", lambda *a, **k: 5.0)

    got = op.evaluate(min_cases=10)
    row = next(f for f in got["families"] if f["key"] == "ORDER_WIN")
    assert row["avg_pct"] is None, (
        "it printed an average built on three cases -- that is how a "
        "coincidence becomes a rule")
    assert "insufficient data" in row["verdict"]
    assert "10" in row["verdict"], "it must say what more is needed"


def test_the_floor_is_applied_to_the_long_only_split_too(monkeypatch):
    """A family can be measurable overall and still have too few
    positive-direction cases to say anything about the half this bot
    could actually trade."""
    hits = ([dict(key="ORDER_WIN", symbol="X", at="2026-08-01",
                  direction=op.UP)] * 3
            + [dict(key="ORDER_WIN", symbol="X", at="2026-08-01",
                    direction=op.DOWN)] * 12)
    monkeypatch.setattr(op, "scan", lambda **k: {
        "available": True, "scanned": len(hits), "hits": hits})
    monkeypatch.setattr(op, "_next_session_move", lambda *a, **k: 1.0)

    row = next(f for f in op.evaluate(min_cases=10)["families"]
               if f["key"] == "ORDER_WIN")
    assert row["avg_pct"] is not None, "15 cases overall should measure"
    assert row["avg_pct_positive"] is None, (
        "only 3 positive-direction cases, but it stated an average for "
        "them anyway")


def test_an_unreadable_store_says_so_rather_than_reporting_zero():
    """"nothing there" and "the read failed" are opposite answers and
    only one of them is safe."""
    assert op._rows("data/there-is-definitely-no-such.db",
                    "select 1") is None


def test_a_missing_price_history_is_not_a_zero_move():
    assert op._next_session_move("NOSUCHSYMBOL-XYZ", "2026-08-01") is None


# ---------------------------------------------------------------
# 4. IT MUST NEVER REACH THE ENTRY PATH
# ---------------------------------------------------------------

def test_it_never_reaches_the_entry_path():
    """THE LINE THAT MUST NOT MOVE.

    If somebody wires this into the ranker or the engine, the bot
    starts trading a rule derived from history -- explicitly forbidden
    -- and this file goes red so the change gets argued about first.
    """
    # Match the IMPORT, not the word. The first version of this test
    # asserted "opportunity" was absent from the source and went red on
    # core/engine.py's own docstring -- "only trades when an event or
    # real opportunity arised in markets". The word is all over this
    # repo because it is the bot's name.
    import re
    imports = re.compile(
        r"^\s*(?:from\s+core\s+import\s+[^\n]*\bopportunity\b"
        r"|from\s+core\.opportunity\s+import"
        r"|import\s+core\.opportunity\b)", re.M)
    for name in ("core/engine.py", "core/auto_entry.py", "core/ranker.py",
                 "core/position_plan.py", "core/exit_plan.py"):
        src = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        assert not imports.search(src), (
            f"{name} imports core/opportunity.py. The brain has reached "
            f"the decision path -- that may be right, but it is a "
            f"deliberate change, not a quiet one.")
        # ...and a call through an alias would dodge the import check.
        assert "opportunity.evaluate(" not in src, name
        assert "opportunity.classify(" not in src, name


def test_the_module_says_out_loud_that_it_does_not_vote():
    src = (ROOT / "core" / "opportunity.py").read_text(encoding="utf-8")
    assert "does not vote" in src.lower()
    assert "does not vote" in op.verdict().lower()


def test_horizons_are_declared_and_honest():
    """A position sized on a 2.5% stop cannot ride a commodity cycle.
    Each family must say which it is, so "can this bot act on it" is
    answered rather than assumed.

    NOTE: this bot is NOT flat at 15:30. FORCE_SQUARE_OFF_AT_CLOSE is
    False and preflight reports "positions carry overnight (MTF)", so
    SESSION and DAYS are both reachable. Only QUARTERS is out."""
    for spec in op.TYPES:
        assert spec["horizon"] in (op.SESSION, op.DAYS, op.QUARTERS), \
            spec["key"]
    horizons = {s["key"]: s["horizon"] for s in op.TYPES}
    assert horizons["COMMODITY_CYCLE"] == op.QUARTERS
    assert horizons["SECTOR_ROTATION"] == op.QUARTERS
    assert horizons["ORDER_WIN"] == op.SESSION


# ---------------------------------------------------------------
# 5. IT HAS TO REACH THE SCREEN
# ---------------------------------------------------------------
#
# core/runup.py was correct, stored and invisible for a week. The
# watchlist panel was computed and drawn nowhere for three days. Both
# were found on 16 August by running the suite end to end, and both
# had tests that "passed" against pages that no longer existed. A
# reading nobody can see is indistinguishable from one never computed.

def test_the_snapshot_attaches_it_to_a_ranked_row():
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert "_opportunity_for" in src, (
        "dashboard/state.py never asks core/opportunity.py anything")
    assert 'row["opportunity"]' in src, (
        "it is computed but never attached to a ranked row")


def test_the_board_draws_it():
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    assert "r.opportunity" in page, (
        "core/opportunity.py types every ranked row and /board does not "
        "draw it -- he still cannot see what kind of opportunity it is")
    block = page[page.find("function reasonChips(r)"):
                 page.find("function capOf(")]
    assert "r.opportunity" in block, (
        "the type is on the page but not in the chips he reads while "
        "deciding")


def test_the_chip_says_which_horizon_it_is():
    """A commodity cycle and an order win must not look alike on the
    screen. One is tradeable by a 15:15 bot and one is not."""
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    block = page[page.find("function reasonChips(r)"):
                 page.find("function capOf(")]
    assert 'o.horizon === "SESSION"' in block, (
        "every family is drawn the same way, so a QUARTERS theme reads "
        "as an intraday opportunity")


def test_the_panel_never_takes_the_snapshot_down():
    """core/watchlist.py raised here on 4 August and killed the whole
    refresh -- every other panel was fine. One panel may cost itself."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    body = src[src.find("def _opportunity_for"):src.find("def build_members")]
    assert "except Exception" in body, (
        "_opportunity_for can raise, and it runs inside the ranked-row "
        "loop that builds the whole snapshot")


def test_every_family_is_reported_even_with_no_hits():
    """A family that never fired must still appear, with zero. Silence
    reads as "not happening"; a zero reads as "watched, never seen",
    and only one of those is true."""
    got = op.evaluate(since_days=1)
    if got["available"]:
        assert len(got["families"]) == len(op.TYPES)
