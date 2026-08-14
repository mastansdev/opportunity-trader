"""
==========================================================
Something big just happened
==========================================================

    "war news will move all stocks fall. & cease fire agreement done
     all stocks were positive . in this situation also some stocks get
     more benifits & some stocks will fall. remember crude raise & fall
     concept?"                      -- operator, 3 August 2026

The two tests that matter most in this file:

    * a ceasefire is not read as a war, even though the sentence
      contains the word "war"
    * the words alone still produce something, because the MDR story
      proved the bot beats News Pulse by fourteen minutes and an alert
      that waits for the tape throws that away every time

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core import shock
from core.shock import assess, event_kind, sectors_for, tape_moved


def movers(n_down=0, n_up=0, sector="Auto", pct=1.2):
    rows = []
    for i in range(n_down):
        rows.append({"symbol": f"D{i}", "sector": sector,
                     "recent_pct": -pct, "change_pct": -pct * 2})
    for i in range(n_up):
        rows.append({"symbol": f"U{i}", "sector": sector,
                     "recent_pct": pct, "change_pct": pct * 2})
    return rows


# ---------------------------------------------------------------
# 1. READING THE HEADLINE
# ---------------------------------------------------------------
@pytest.mark.parametrize("headline,kind", [
    ("Missile strike near the Strait of Hormuz", "war"),
    ("Israel and Iran agree a ceasefire", "ceasefire"),
    ("RBI cuts repo rate by 25bp", "rate_cut"),
    ("Fed hikes rate, signals more to come", "rate_hike"),
    ("OpenAI launches agent that automates back office", "ai_disruption"),
])
def test_the_event_is_recognised(headline, kind):
    assert event_kind(headline) == kind


def test_a_ceasefire_is_not_read_as_a_war():
    """     "cease fire agreement done all stocks were positive"

    "Ceasefire agreed in the war" contains the word war. Checked in the
    wrong order this fires a war alert on peace news and points every
    button the wrong way -- on the one day the whole market gaps up."""
    assert event_kind("Ceasefire agreed in the war with Iran") == "ceasefire"
    assert event_kind("Truce holds after weeks of conflict") == "ceasefire"


def test_ordinary_news_is_not_a_shock():
    assert event_kind("Titan Q1 revenue up 18% on jewellery") is None
    assert event_kind("") is None
    assert event_kind(None) is None


# ---------------------------------------------------------------
# 2. THE CRUDE CHAIN, WALKED BOTH WAYS
# ---------------------------------------------------------------
#     "remember crude raise & fall concept?"
def test_war_pushes_crude_up_and_that_hurts_the_burners():
    got = sectors_for("war")
    assert got["Auto"] == -1            # pays more for everything
    assert got["Infra"] == -1


def test_the_producers_and_the_refiners_are_split_apart():
    """     "remember crude raise & fall concept?"

    The first version of this chain named the sector index Oil & Gas.
    That index holds ONGC and BPCL: crude up helps one and hurts the
    other, so the two cancelled and the chain produced NOTHING for the
    driver he names most often. The code was right to refuse a view on
    the basket -- a BUY on a basket holding both sides of a trade is
    worse than silence -- but the answer was to stop using the basket.

    Split at industry level, both sides survive with opposite signs,
    which is exactly "some stocks get more benefits & some will fall".
    """
    war = sectors_for("war")
    assert war["Oil exploration"] == 1
    assert war["Oil refining"] == -1
    assert war["Aviation"] == -1

    from core import sector_map
    assert "ONGC" in sector_map.members("Oil exploration")
    assert "BPCL" in sector_map.members("Oil refining")


def test_a_ceasefire_is_the_same_road_backwards():
    war, peace = sectors_for("war"), sectors_for("ceasefire")
    shared = set(war) & set(peace)
    assert shared, "the two events touch nothing in common"
    for sector in shared:
        assert war[sector] == -peace[sector], sector


def test_a_weak_rupee_still_helps_exporters_during_a_war():
    """Everything falls on war news -- but not everything. IT is paid in
    dollars, and that is the whole point of showing two lists."""
    assert sectors_for("war")["IT"] == 1


def test_a_rate_cut_helps_the_rate_sensitives():
    got = sectors_for("rate_cut")
    assert got.get("Realty") == 1


def test_an_unknown_event_maps_to_nothing():
    assert sectors_for("budget") == {}
    assert sectors_for(None) == {}


def test_every_group_named_resolves_to_real_tradeable_stocks():
    """A group that resolves to nothing is a silent dead end: the chain
    runs, produces a direction, and puts no stock on the screen."""
    from core import sector_map
    sector_map.reset()
    for kind in shock.EVENT_DRIVERS:
        for group in sectors_for(kind):
            assert sector_map.members(group), f"{kind} -> {group}"


# ---------------------------------------------------------------
# 3. THE TAPE
# ---------------------------------------------------------------
def test_the_whole_market_falling_is_a_shock():
    got = tape_moved(movers(n_down=600), index_pct=-1.1)
    assert got["side"] == "down"
    assert got["count"] == 600


def test_a_few_stocks_moving_is_not():
    assert tape_moved(movers(n_down=50), index_pct=-1.1) is None


def test_a_quiet_index_means_it_is_a_rotation_not_a_shock():
    """Hundreds of stocks can move while one sector rotates into
    another. If NIFTY has not moved, the market has not moved."""
    assert tape_moved(movers(n_down=600), index_pct=-0.1) is None


def test_the_index_has_to_agree_with_the_crowd():
    assert tape_moved(movers(n_down=600), index_pct=+1.1) is None


def test_it_reads_the_recent_move_not_the_day_change():
    """     "MOST top gainers were sitting at top and not moving in
             either direction"

    A stock that gapped 12% at 09:15 and has not ticked since is not
    moving now. Day change would count it and call a dead tape a
    shock."""
    stalled = [{"symbol": f"S{i}", "sector": "Auto", "change_pct": -12.0,
                "recent_pct": 0.0} for i in range(900)]
    assert tape_moved(stalled, index_pct=-1.5) is None


def test_no_prices_at_all_is_not_a_shock():
    assert tape_moved([], index_pct=-2.0) is None
    assert tape_moved(None, index_pct=-2.0) is None


# ---------------------------------------------------------------
# 4. TWO TIERS -- THE HEAD START IS NOT THROWN AWAY
# ---------------------------------------------------------------
def test_the_headline_alone_still_says_something():
    """     On 3 August the bot had the MDR story with five affected
            stocks FOURTEEN MINUTES before News Pulse carried it.

    An alert that waits for tape confirmation discards that head start
    on every single event."""
    got = assess(headlines=[{"headline": "Missile strike near Hormuz",
                             "source": "Day Trader Telugu"}])
    assert got is not None
    assert got["tier"] == "heads_up"


def test_the_tape_confirming_raises_it_to_a_full_alert():
    got = assess(headlines=[{"headline": "Missile strike near Hormuz"}],
                 movers=movers(n_down=700), index_pct=-1.2)
    assert got["tier"] == "alert"
    assert "700 stocks moved down" in got["detail"]


def test_the_tape_alone_is_an_alert_even_with_no_headline():
    """The words can be late or absent. 800 stocks falling in four
    minutes is a fact that needs no reader."""
    got = assess(movers=movers(n_down=800), index_pct=-1.4)
    assert got["tier"] == "alert"
    assert got["kind"] is None


def test_a_quiet_market_and_quiet_news_says_nothing():
    """     "AN EMPTY LIST IS AN ANSWER"

    A screen that finds a crisis every day finds none on the day there
    is one."""
    assert assess(headlines=[{"headline": "Titan Q1 revenue up 18%"}],
                  movers=movers(n_down=20), index_pct=-0.1) is None
    assert assess() is None


# ---------------------------------------------------------------
# 5. WHAT REACHES THE SCREEN
# ---------------------------------------------------------------
def test_his_open_positions_come_first():
    got = assess(headlines=[{"headline": "Ceasefire agreed"}],
                 movers=movers(n_up=600), index_pct=1.3,
                 positions=[{"symbol": "TITAN", "qty": 28,
                             "change_pct": -1.9, "pnl": -2072}])
    assert got["positions"][0]["symbol"] == "TITAN"
    assert got["positions"][0]["qty"] == 28


def test_the_two_lists_carry_a_direction_and_a_reason():
    # IT is the side that RISES on war news -- a weaker rupee pays
    # exporters more, which is exactly the "some stocks get more
    # benefits" half of what he described.
    rows = (movers(n_up=3, sector="IT")
            + movers(n_down=3, sector="Auto"))
    got = assess(headlines=[{"headline": "Missile strike near Hormuz"}],
                 movers=rows + movers(n_down=700, sector="Metal"),
                 index_pct=-1.2)
    assert got["up"] and got["down"]
    for row in got["up"]:
        assert row["action"] == "BUY"
        assert row["why"]
    for row in got["down"]:
        assert row["action"] == "SELL"


def test_the_reason_is_the_driver_in_plain_words():
    from core.shock import why_for
    line = why_for("war", "Oil exploration")
    assert "crude oil up" in line
    assert "z-score" not in line and "beta" not in line


def test_it_never_returns_permission():
    """     "bot must inform the situation like a caution not block" """
    got = assess(movers=movers(n_down=900), index_pct=-2.4)
    assert got["informs_only"] is True
    for banned in ("blocked", "allowed", "veto", "can_trade", "halt"):
        assert banned not in got, banned


def test_the_module_exposes_no_gate():
    for name in dir(shock):
        low = name.lower()
        assert "block" not in low, name
        assert "veto" not in low, name


def test_the_banner_words_are_ones_he_can_act_on():
    got = assess(headlines=[{"headline": "Ceasefire agreed with Iran"}],
                 movers=movers(n_up=700), index_pct=1.2)
    assert got["headline"] == "A ceasefire has been reported"
    text = (got["headline"] + got["detail"]).lower()
    for word in ("regime", "risk-on", "contested", "sigma", "percentile"):
        assert word not in text, word
