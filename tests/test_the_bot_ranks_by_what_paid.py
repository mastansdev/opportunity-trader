"""
==========================================================
The bot ranked by how important an event SOUNDS
==========================================================

    "i'm not satisified the way you are working. bot is not fully
     equipped to find the opportunity ... u need to educate & make
     sure bot must understand about markets & which events will create
     opportunity to which sector stocks & trade in top ranker of that
     sector.
     why can't bot self adjust the trading based on the stock movement
     & news/events supporting the stock price movement. trailing in
     good moving stocks (strong supported events)."
                                -- operator, 19 August 2026

He was right, and the fault was structural rather than a bad number
here and there. An audit of the opportunity path found four things,
and this file holds the three that were fixed.

GAP 1 -- THE MECHANISM WEIGHT WAS TYPED, NOT MEASURED
core/ranker.py scores five terms and one is the strength of the
reason:

    score += W_MECHANISM * mech["weight"] * 2.0

Every weight core/why_moving.py hands it is hand-assigned: 0.95, 0.9,
0.85, 0.8, 0.65, 0.6, 0.55, 0.5. core/opportunity.py had separately
measured what each family is worth the session after it appears, and
the two disagree:

    ORDER_WIN         +0.64%   n=80     hand weight ~0.8
    BUSINESS_UPDATE   -0.32%   n=123    hand weight ~0.9

A business update outranked an order win on the board while being
worth less than nothing across 123 cases. That is the machinery
behind "the top-ranked three were the worst of the eleven" in the
8 August replay.

GAP 2 -- NOTHING RANKED WITHIN A SECTOR
There was no per-sector limit of any kind. An event happens to a
SECTOR and the sector hands the same reason to every name in it, so a
copper headline could put four correlated names on a board feeding a
three-position book. One idea wearing four tickers, and when it is
wrong every seat is wrong together.

GAP 3 -- THE TRAIL WAS ONE WIDTH FOR EVERY STOCK
The entry stop was fixed on 18 August. PEAK_TRAIL_PCT was left at a
flat 2.5% from the peak -- half an ordinary day for ICIL (4.99%) and
more than a whole one for POLYCAB (1.79%).

GAP 4 -- NAMED ON 19 AUGUST, BUILT THE SAME DAY
core/sector_map.sides() knows which companies a commodity move helps
and which it hurts, and nothing on the ranking path consulted it: a
copper spike scored a cable maker on the same footing as a copper
miner. He asked for the build straight after reading this, it was
measured over a year of daily bars first, and the guard test at the
bottom of this file was INVERTED rather than deleted -- it had been
written to fail on exactly this day.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from core import opportunity, ranker

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    opportunity.reset_payoff_cache()
    yield
    opportunity.reset_payoff_cache()


# ---------------------------------------------------------------
# GAP 1: RANK BY WHAT IT PAID
# ---------------------------------------------------------------

def test_a_family_that_paid_outranks_one_that_did_not(monkeypatch):
    """THE WHOLE POINT. Same sentence structure, opposite measured
    history, and the weights must now differ."""
    monkeypatch.setattr(opportunity, "payoff_table",
                        lambda min_cases=20: {"ORDER_WIN": 0.64,
                                              "BUSINESS_UPDATE": -0.32})
    good = opportunity.payoff_weight("company bags order worth Rs 450 crore")
    bad = opportunity.payoff_weight("business update for the quarter ended")
    assert good > 1.0, "a family that paid did not earn a boost"
    assert bad < 1.0, "a family measured NEGATIVE was not penalised"


def test_it_tilts_and_never_decides(monkeypatch):
    """A measurement may lean on one of five scoring terms. It may not
    veto a trade and it may not conjure one."""
    monkeypatch.setattr(opportunity, "payoff_table",
                        lambda min_cases=20: {"ORDER_WIN": 99.0,
                                              "TARIFF_DUTY": -99.0})
    assert opportunity.payoff_weight("bags order") <= \
        opportunity.PAYOFF_CEILING
    assert opportunity.payoff_weight(
        "anti-dumping duty imposed") >= opportunity.PAYOFF_FLOOR
    assert opportunity.PAYOFF_FLOOR > 0, (
        "a zero multiplier is a veto wearing a multiplier's clothes")


def test_a_thin_family_moves_nothing(monkeypatch):
    """Fewer than PAYOFF_MIN_CASES measured cases is an anecdote, and
    an anecdote must not reorder his morning."""
    monkeypatch.setattr(opportunity, "evaluate", lambda **kw: {"families": [
        {"key": "ORDER_WIN", "verdict": "measured", "measured": 3,
         "avg_pct": 5.0}]})
    assert opportunity.payoff_table() == {}
    assert opportunity.payoff_weight("bags order") == 1.0


def test_an_unrecognised_reason_is_left_exactly_alone():
    assert opportunity.payoff_weight("") == 1.0
    assert opportunity.payoff_weight(None) == 1.0
    assert opportunity.payoff_weight("a sentence about nothing at all") == 1.0


def test_it_never_raises_and_falls_back_to_no_opinion(monkeypatch):
    def _explode(**kw):
        raise RuntimeError("the events store is locked")
    monkeypatch.setattr(opportunity, "evaluate", _explode)
    assert opportunity.payoff_weight("bags order") == 1.0


def test_the_strongest_claim_wins_not_the_average(monkeypatch):
    """A sentence carrying an order win AND a routine update is an
    order win with an update attached, not the mean of the two."""
    monkeypatch.setattr(opportunity, "payoff_table",
                        lambda min_cases=20: {"ORDER_WIN": 1.0,
                                              "BUSINESS_UPDATE": -1.0})
    both = opportunity.payoff_weight(
        "business update: company bags order worth Rs 450 crore")
    assert both > 1.0


def test_why_moving_applies_it_and_shows_its_working(monkeypatch):
    """A score he cannot take apart is a score he has to trust."""
    from core import why_moving
    monkeypatch.setattr(
        why_moving, "_why_before_payoff",
        lambda **kw: {"text": "company bags order worth Rs 450 crore",
                      "weight": 0.8, "direction": "UP", "source": "test"})
    got = why_moving.why(symbol="X")
    assert got["weight"] != 0.8, "the hand weight was not adjusted"
    assert got["weight_before_payoff"] == 0.8
    assert got["payoff_mult"] > 1.0
    assert got["payoff_note"], "the tilt is not explained anywhere"


def test_the_switch_restores_the_old_behaviour_exactly(monkeypatch):
    from core import why_moving
    monkeypatch.setattr("core.rules.RANK_BY_MEASURED_PAYOFF", False)
    monkeypatch.setattr(
        why_moving, "_why_before_payoff",
        lambda **kw: {"text": "bags order", "weight": 0.8})
    got = why_moving.why(symbol="X")
    assert got["weight"] == 0.8
    assert "payoff_mult" not in got


def test_the_shape_the_ranker_reads_is_unchanged(monkeypatch):
    """core/ranker.py reads mechanism_of(symbol) -> {"text","weight"}.
    Adding fields is safe; changing that contract is not."""
    from core import why_moving
    monkeypatch.setattr(
        why_moving, "_why_before_payoff",
        lambda **kw: {"text": "bags order", "weight": 0.8,
                      "direction": "UP", "source": "test"})
    got = why_moving.why(symbol="X")
    for field in ("text", "weight", "direction", "source"):
        assert field in got


# ---------------------------------------------------------------
# GAP 2: THE BEST NAME IN EACH SECTOR COMES FIRST
# ---------------------------------------------------------------

def test_one_sector_can_no_longer_fill_the_whole_board():
    """A copper headline used to put four correlated names on a board
    feeding a three-position book."""
    rows = [{"symbol": "C1", "sector": "CHEMICALS"},
            {"symbol": "C2", "sector": "CHEMICALS"},
            {"symbol": "C3", "sector": "CHEMICALS"},
            {"symbol": "M1", "sector": "METALS"},
            {"symbol": "B1", "sector": "BANKS"}]
    got = [r["symbol"] for r in ranker._best_of_each_sector(rows)]
    assert got[:3] == ["C1", "M1", "B1"], (
        "the top of the board is still one idea wearing three tickers")


def test_nothing_is_thrown_away():
    """A cap would lose a real setup on a day one sector IS the story.
    This reorders; the book's own limits decide how many are taken."""
    rows = [{"symbol": f"C{i}", "sector": "CHEMICALS"} for i in range(4)]
    rows.append({"symbol": "M1", "sector": "METALS"})
    got = ranker._best_of_each_sector(rows)
    assert len(got) == len(rows)
    assert {r["symbol"] for r in got} == {r["symbol"] for r in rows}


def test_order_within_a_sector_is_preserved():
    """liveness-then-score still holds inside each group."""
    rows = [{"symbol": "C1", "sector": "CHEM"},
            {"symbol": "C2", "sector": "CHEM"},
            {"symbol": "C3", "sector": "CHEM"}]
    got = [r["symbol"] for r in ranker._best_of_each_sector(rows)]
    assert got == ["C1", "C2", "C3"]


def test_unknown_sectors_are_not_rationed_as_one_bucket():
    """Two stocks whose sector is blank are not the same bet, and
    grouping them would demote the second for no reason."""
    rows = [{"symbol": "U1", "sector": None},
            {"symbol": "U2", "sector": ""},
            {"symbol": "M1", "sector": "METALS"}]
    got = [r["symbol"] for r in ranker._best_of_each_sector(rows)]
    assert got[:3] == ["U1", "U2", "M1"]


def test_it_survives_junk():
    assert ranker._best_of_each_sector([]) == []
    assert ranker._best_of_each_sector(None) == []


def test_the_ranker_actually_calls_it():
    src = (ROOT / "core" / "ranker.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "out = _best_of_each_sector(out)" in code


# ---------------------------------------------------------------
# GAP 3: THE TRAIL FITS THE STOCK, AND WIDENS ON A CATALYST
# ---------------------------------------------------------------

def test_a_wild_stock_is_trailed_wider_than_a_calm_one():
    from core.trailing_stop import _trail_pct_for
    calm = _trail_pct_for("POLYCAB")
    wild = _trail_pct_for("ICIL")
    assert wild > calm, (
        "2.5% from the peak is half an ordinary day on one of these")


def test_a_catalyst_earns_more_room():
    """A pause inside a real event is not a failure."""
    from core.trailing_stop import _trail_pct_for
    assert _trail_pct_for("ICIL", has_event=True) > _trail_pct_for("ICIL")


def test_an_unmeasurable_stock_keeps_the_flat_trail():
    from config import PEAK_TRAIL_PCT
    from core.trailing_stop import _trail_pct_for
    assert _trail_pct_for("NEVERLISTEDCO") == pytest.approx(PEAK_TRAIL_PCT)


def test_the_trail_is_bounded_at_both_ends(monkeypatch):
    from config import TRAIL_MIN_PCT, TRAIL_MAX_PCT
    from core import trailing_stop
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 0.1)
    assert trailing_stop._trail_pct_for("X") == pytest.approx(
        TRAIL_MIN_PCT / 100.0)
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 40.0)
    assert trailing_stop._trail_pct_for("X", has_event=True) == \
        pytest.approx(TRAIL_MAX_PCT / 100.0)


def test_the_stop_and_the_trail_read_the_same_volatility():
    """Two definitions of 'how much this stock moves' would drift
    apart, and the trade would be sized on one and exited on the
    other."""
    for name in ("engine.py", "trailing_stop.py"):
        src = (ROOT / "core" / name).read_text(encoding="utf-8")
        assert "daily_atr_pct" in src


def test_the_engine_tells_the_trail_whether_there_is_an_event():
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert code.count("has_event=self._position_has_event(") == 2, (
        "one of the two trail seeds is not passing the event flag")
    body = src[src.find("def _position_has_event"):
               src.find("def _hard_stop_pct")]
    assert "_capture_reason" in body, (
        "a second definition of 'event' will drift from the first")


def test_the_switch_restores_the_flat_trail(monkeypatch):
    from config import PEAK_TRAIL_PCT
    from core import trailing_stop
    monkeypatch.setattr(trailing_stop, "VOLATILITY_SCALED_TRAIL", False)
    assert trailing_stop._trail_pct_for("ICIL") == pytest.approx(
        PEAK_TRAIL_PCT)


# ---------------------------------------------------------------
# GAP 4: NAMED, NOT SILENTLY DROPPED
# ---------------------------------------------------------------

def test_the_sector_polarity_arrived_with_its_measurement():
    """---- THIS TEST WAS WRITTEN TO FAIL TODAY. 19 August 2026. ----

    Yesterday it read "the sector polarity is still display only" and
    asserted no gate consulted it, so the wiring could not happen
    quietly in a diff. He asked for the build; it was measured over a
    year of daily bars first. The assertion is INVERTED rather than
    deleted, and it very nearly passed for the wrong reason -- the
    ranker calls commodity_tilt(), not sides(), so the old grep would
    have gone on saying "display only" about a scorer that had
    already been wired.

    What it guards from here: the tilt may enter the SCORE only, it
    stays bounded, and it stays switchable.
    """
    from core import rules, sector_map

    src = (ROOT / "core" / "ranker.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "commodity_tilt" in code, "the build was undone"
    assert "RANK_BY_COMMODITY_POLARITY" in code, "no switch"
    assert hasattr(rules, "RANK_BY_COMMODITY_POLARITY")
    assert 0.5 < sector_map.TILT_FLOOR < 1.0 < sector_map.TILT_CEILING < 1.5


def test_the_tilt_reorders_and_never_refuses():
    """A commodity reading is worth reordering a list. It is nowhere
    near strong enough to block a setup that passed every other gate
    -- the measured spread is about a tenth of a percent."""
    src = (ROOT / "core" / "ranker.py").read_text(encoding="utf-8")
    block = src[src.find("tilt, tilt_why = 1.0, None"):
                src.find("out.append(Candidate")]
    assert "refuse(" not in block
    assert "continue" not in block


def test_the_entry_path_still_does_not_read_polarity():
    """auto_entry and engine decide whether to BUY. Neither may ask."""
    for name in ("auto_entry.py", "engine.py"):
        src = (ROOT / "core" / name).read_text(encoding="utf-8")
        code = chr(10).join(ln for ln in src.splitlines()
                            if not ln.lstrip().startswith("#"))
        for banned in ("sector_map.sides", "commodity_tilt"):
            assert banned not in code, (
                f"core/{name} now gates on commodity polarity")


def test_a_stock_on_neither_side_is_left_alone():
    """HINDALCO makes the metal it is exposed to, so sides() cannot
    tell producer from converter and says so. UNKNOWN must never be
    quietly treated as one of the two."""
    from core import sector_map
    tilt, why = sector_map.commodity_tilt("HINDALCO")
    assert tilt == 1.0 and why is None


def test_the_tilt_reads_only_completed_sessions():
    """The series carries a row for TODAY, and while the market is
    open that row is half a session. Reading it asks a different
    question from the one that was measured -- and a tilt built on
    half a day changes its mind at lunchtime."""
    src = (ROOT / "core" / "sector_map.py").read_text(encoding="utf-8")
    body = src[src.find("def commodities_that_moved"):
               src.find("def commodity_tilt")]
    assert "< cutoff" in body, "today's partial bar is being read"
