"""
==========================================================
Ten sugar names ran 17%. The bot said "no event behind it".
==========================================================

    "does bot know the same sector/ theme stocks ? does it identify
     today sugar stocks were rallied?"
    "if complete sector is being rallied then something is happening
     underlying right?"
                                -- operator, 20 August 2026

Yes to the first. No to the second, and here is what that cost.

20 August, the sugar complex by 10:58 -- half a session:

    BAJAJHIND  +16.7   DWARKESH   +15.6   MAGADSUGAR +9.9
    DHAMPURSUG  +9.9   RENUKA      +9.5   AVADHSUGAR +9.5
    DALMIASUG   +9.0   UTTAMSUGAR  +8.5   UGARSUGAR  +8.1
    TRIVENI     +7.4   BALRAMCHIN  +4.5

Not one alert. The bot's own journal says why:

    MAGADSUGAR  vol 15.11x  "no event behind it"
    BALRAMCHIN  vol  4.37x  "no event behind it"
    DALMIASUG   vol  4.18x  "no event behind it"

It asks "does THIS stock have a reason" one stock at a time. Each
name individually had no filing, so each was refused -- correctly, by
the rule as written. Ten names moving together was invisible because
nothing ever asked about the group. The bot owns the sector map and
knows all 21 sugar names.

MEASURED BEFORE ARMING, a year of daily bars. Next session, minus
that session's market median:

    control: ANY lone 5% mover    n=3622   +0.550
    4 members co-moving           n=1036   +0.526
    6 members co-moving           n= 417   +0.925
    8 members co-moving           n= 149   +0.763

FOUR IS NOTHING -- a co-mover does no better than an ordinary mover,
so "the sector is moving" is not evidence on its own and a rule built
on four would have been wrong. SIX is where the excess appears. The
threshold is six, and the honest reading is that a sector has to move
BROADLY before it says anything the stock's own momentum did not.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core import sector_map as sm

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The real numbers off his board that morning.
SUGAR_DAY = {
    "BAJAJHIND": 16.7, "DWARKESH": 15.6, "MAGADSUGAR": 9.9,
    "DHAMPURSUG": 9.9, "RENUKA": 9.5, "AVADHSUGAR": 9.5,
    "DALMIASUG": 9.0, "UTTAMSUGAR": 8.5, "UGARSUGAR": 8.1,
    "TRIVENI": 7.4, "BALRAMCHIN": 4.5, "TCS": 0.2, "RELIANCE": -0.4,
}


# ---------------------------------------------------------------
# THE DAY IT MISSED
# ---------------------------------------------------------------

def test_the_sugar_rally_is_recognised():
    """THE EXACT MORNING. Ten names, and the bot said nothing."""
    groups = sm.co_moving(SUGAR_DAY)
    assert "SUGAR" in groups, "the sugar complex is still invisible"
    assert len(groups["SUGAR"]) >= 6


def test_a_member_gets_a_sentence_he_can_argue_with():
    """A count and a group, not a verdict. He can disagree with a
    count."""
    said = sm.co_move_reason("MAGADSUGAR", SUGAR_DAY)
    assert said and "SUGAR" in said
    assert "10" in said, "it does not say how many are moving"


def test_a_stock_outside_the_move_gets_nothing():
    assert sm.co_move_reason("TCS", SUGAR_DAY) is None
    assert sm.co_move_reason("RELIANCE", SUGAR_DAY) is None


def test_a_member_that_did_not_move_is_not_credited():
    """BALRAMCHIN was +4.48%, under the 5% that was MEASURED. Crediting
    it would extend the rule past its evidence -- the excess was
    measured on members that moved, not on everyone wearing the tag.
    """
    assert sm.co_move_reason("BALRAMCHIN", SUGAR_DAY) is None


# ---------------------------------------------------------------
# FOUR MEASURED AS NOTHING, SO FOUR IS NOT ENOUGH
# ---------------------------------------------------------------

def test_five_movers_are_not_a_sector_event():
    """+0.526 against a +0.550 control. A rule built on four would
    have fired on noise all year."""
    five = {s: v for s, v in list(SUGAR_DAY.items())[:5]}
    assert sm.co_moving(five) == {}
    assert sm.co_move_reason("BAJAJHIND", five) is None


def test_the_threshold_is_the_one_that_was_measured():
    assert sm.CO_MOVE_MIN_MEMBERS == 6, (
        "the threshold moved away from the measured one")
    assert sm.CO_MOVE_PCT == 5.0


def test_a_huge_group_cannot_qualify():
    """Two hundred names 'co-moving' is the market having a good day,
    not a sector event."""
    assert sm.CO_MOVE_MAX_GROUP <= 100
    assert sm.CO_MOVE_MIN_GROUP >= 3


# ---------------------------------------------------------------
# IT NEVER RAISES AND NEVER DECIDES
# ---------------------------------------------------------------

def test_it_survives_junk():
    for moves in (None, {}, {"X": None}, {"X": "abc"}, {None: 5.0},
                  {"X": float("nan")}):
        assert isinstance(sm.co_moving(moves), dict)
        assert sm.co_move_reason("X", moves) is None or True


def test_it_is_a_reason_and_not_a_score():
    """It satisfies "no event, no trade". It must never become a
    number added to the ranking -- that would need its own
    measurement, and this one measured a REASON."""
    src = (ROOT / "core" / "ranker.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    for banned in ("co_moving", "co_move_reason"):
        assert banned not in code, (
            "the sector co-move is being scored, not just believed")


def test_the_engine_asks_and_records_it():
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_sector_co_move_reason(symbol)" in code
    assert '"sector_move"' in code, (
        "the reason is found and then dropped before the record")


def test_it_reads_the_same_picture_the_board_draws():
    """The circuit poller's snapshot, so the alert and the gainers
    table cannot disagree about what moved."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _sector_co_move_reason"):
               src.find("def _channel_event_kind")]
    assert "circuit_monitor.get_snapshot" in body


def test_it_can_be_switched_off_in_one_place():
    from core import rules
    assert hasattr(rules, "SECTOR_CO_MOVE_IS_A_REASON")


def test_it_works_against_the_real_master():
    """Against data/master_stocks.csv itself -- 21 sugar names by
    commodity exposure. If the groupings move under this, it fails
    here rather than going quietly blind."""
    assert len(sm.carrying("SUGAR")) >= 1
    groups = sm.co_moving(SUGAR_DAY)
    assert groups, "the real master no longer groups the sugar names"
