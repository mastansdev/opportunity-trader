"""
==========================================================
Market Situational Awareness -- informs, never blocks
==========================================================

    "bot must inform the situation like a caution not block"
    "bot need to monitor continuously the news, events, global risks =
     bond yields, currency, commodities"
                                    -- operator, 3 August 2026

The single most important test in this file is the one that proves
this module cannot refuse a trade. Every other guard here exists to
stop a STALE input voting as if it were live -- because the two inputs
that go stale are the two he would most want to trust.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core import awareness
from core.awareness import assess, classify_event, read_flows, read_world


class Store:
    """Stands in for premarket / market_flows."""

    def __init__(self, data):
        self.data = data

    def snapshot(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def world(**moves):
    """A premarket snapshot with the given percentage moves."""
    rows = [{"key": k, "label": k, "last": 100.0, "change_pct": v,
             "stale": False, "available": True} for k, v in moves.items()]
    return {"available": True, "groups": {"ALL": rows}, "failed": []}


def idx(nifty=None, vix=None):
    out = {}
    if nifty is not None:
        out["nifty"] = {"ltp": 24774.0, "pct": nifty, "available": True}
    if vix is not None:
        out["vix"] = {"ltp": vix, "pct": None, "available": True}
    return out


def sectors(*pcts):
    return [{"name": f"S{i}", "pct": p} for i, p in enumerate(pcts)]


# ---------------------------------------------------------------
# 1. IT CANNOT BLOCK A TRADE
# ---------------------------------------------------------------
def test_the_reading_never_carries_a_block():
    """     "bot must inform the situation like a caution not block"

    No key a caller could read as permission. If one ever appears, a
    future panel will start greying out buttons and he will lose a
    trade to a number he never agreed to."""
    got = assess(premarket=Store(world(crude=9.0)), indices=idx(-2.0, 31.0),
                 sector_rows=sectors(-1, -1, -1, -1), breadth_pct=12.0)
    assert got["verdict"] == "Stay out"
    assert got["informs_only"] is True
    for banned in ("blocked", "block", "allowed", "veto", "gate",
                   "can_trade", "halt", "disabled"):
        assert banned not in got, banned


def test_even_the_worst_reading_returns_only_words():
    got = assess(premarket=Store(world(crude=12.0, dxy=3.0, us10y=6.0)),
                 indices=idx(-3.0, 40.0), sector_rows=sectors(-3, -3, -3),
                 breadth_pct=5.0)
    assert isinstance(got["verdict"], str)
    assert got["rows"]


def test_the_module_exposes_no_gate_function():
    """Nothing importable from here should look like permission."""
    for name in dir(awareness):
        low = name.lower()
        assert "block" not in low, name
        assert not low.startswith("can_"), name
        assert "veto" not in low, name


# ---------------------------------------------------------------
# 2. A STALE INPUT NEVER VOTES AS SUPPORT
# ---------------------------------------------------------------
def test_fii_is_always_labelled_previous_session():
    """NSE publishes it once, after the close. During the session it is
    yesterday's number and it must say so, every time."""
    verdict, line, _ = read_flows(Store({"available": True, "fii_cr": 2140.0,
                                         "dii_cr": 800.0, "as_of": "2026-08-01"}))
    assert verdict == "stale"
    assert "previous session" in line


def test_a_big_fii_number_still_does_not_count_as_support():
    got = assess(market_flows=Store({"available": True, "fii_cr": 9999.0,
                                     "dii_cr": 1.0}),
                 indices=idx(0.9, 12.0), sector_rows=sectors(1, 1, 1),
                 breadth_pct=70.0)
    flows = next(r for r in got["rows"] if r["key"] == "flows")
    assert flows["verdict"] == "stale"
    assert got["supports"] == 3


def test_a_dead_feed_never_reads_out_yesterdays_numbers():
    """     Checked against the real data/premarket.json on 3 August
            2026: all eighteen sources were in "failed" and every quote
            was flagged stale, yet the file still held crude at 80.22
            and Nasdaq at 25,373 from an older run.

    Reading those out as tonight's overnight picture would be the same
    mistake as drawing invented prices in a panel and calling them
    real. A feed that stopped says it stopped."""
    snap = world(crude=-5.26, nasdaq=3.81, usdinr=-0.33)
    for row in snap["groups"]["ALL"]:
        row["stale"] = True
    snap["failed"] = ["Crude oil", "Nasdaq", "USD / INR"]
    verdict, line, moves = read_world(Store(snap))
    assert verdict == "unknown"
    assert "not updating" in line
    assert moves == []


def test_a_partial_failure_still_uses_what_did_arrive():
    """One dead source must not throw away the seventeen that worked."""
    snap = world(crude=-5.26, nasdaq=3.81)
    snap["failed"] = ["Crude oil"]
    verdict, _, moves = read_world(Store(snap))
    assert verdict != "unknown"
    assert moves


def test_morning_only_world_data_reads_as_stale():
    """     main.py runs PreMarket(fetcher=None) -- it only reads what
            the 08:45 job stored. By 11:00 it is three hours old."""
    snap = world(crude=4.0)
    snap["groups"]["ALL"][0]["stale"] = True
    verdict, line, _ = read_world(Store(snap))
    assert verdict == "stale"
    assert "morning" in line


# ---------------------------------------------------------------
# 3. THE DRIVERS HE NAMED ARE ACTUALLY THERE
# ---------------------------------------------------------------
#     "crude , gold, commodities, currencies , bond yields, fed, rbi,
#      govt decisions , AI bubble = indian IT sell off"
@pytest.mark.parametrize("key", ["crude", "gold", "copper", "natgas",
                                 "dxy", "usdinr", "us10y", "us2y",
                                 "sp500", "nasdaq"])
def test_every_named_driver_is_mapped(key):
    assert key in awareness.DRIVERS_BY_KEY


def test_every_driver_carries_a_reason_in_plain_words():
    for driver in awareness.DRIVERS:
        assert driver.why and len(driver.why) > 20, driver.key
        assert driver.label, driver.key


def test_a_weak_rupee_helps_exporters_and_hurts_importers():
    d = awareness.DRIVERS_BY_KEY["usdinr"]
    assert "IT" in d.helps and "Pharma" in d.helps
    # Refiners buy the barrel in dollars; airlines buy the fuel.
    assert "Oil refining" in d.hurts and "Aviation" in d.hurts


def test_rising_yields_hurt_the_rate_sensitives():
    d = awareness.DRIVERS_BY_KEY["us10y"]
    assert "Realty" in d.hurts
    assert not d.helps


def test_drivers_point_at_groups_not_hardcoded_symbols():
    """     "pls make sure we will trade only NSE listed stocks"

    Writing BPCL, INDIGO, ASIANPAINT into this file from memory is how
    FINNIFTY ended up in the config labelled 'midcap'. Drivers name
    GROUPS; core/sector_map.py resolves those to symbols out of the
    verified master."""
    from config import SECTOR_INDICES
    from core.sector_map import FAN_OUT_GROUPS
    known = set(SECTOR_INDICES.values()) | set(FAN_OUT_GROUPS)
    for driver in awareness.DRIVERS:
        for sector in tuple(driver.helps) + tuple(driver.hurts):
            assert sector in known, f"{driver.key} -> {sector}"


def test_every_group_a_driver_names_holds_real_stocks():
    """A group that resolves to nothing is a silent dead end: the chain
    runs, produces a direction, and puts no stock on the screen."""
    from core import sector_map
    sector_map.reset()
    for driver in awareness.DRIVERS:
        for group in tuple(driver.helps) + tuple(driver.hurts):
            assert sector_map.members(group), f"{driver.key} -> {group}"


def test_gold_points_at_jewellers_and_not_at_air_conditioners():
    """     Checked in data/master_stocks.csv on 3 August 2026.

    This driver first read helps=("Consumer Durables",), which was
    wrong. TITAN, KALYANKJIL and SENCO are CONSUMER DISCRETIONARY /
    "JEWELLERY / WATCHES RETAIL". CONSUMER DURABLES is footwear, air
    conditioners and home appliances. A gold headline was pointing at
    the wrong shops."""
    from core import sector_map
    assert awareness.DRIVERS_BY_KEY["gold"].helps == ("Jewellery",)
    jewellers = sector_map.members("Jewellery")
    assert "TITAN" in jewellers and "KALYANKJIL" in jewellers
    assert "TITAN" not in sector_map.members("Consumer Durables")


def test_crude_splits_the_producers_from_the_refiners():
    """The whole reason the chain produced nothing for crude before:
    ONGC and BPCL sit in the same index and move opposite ways."""
    from core import sector_map
    crude = awareness.DRIVERS_BY_KEY["crude"]
    assert "Oil exploration" in crude.helps
    assert "Oil refining" in crude.hurts
    assert "ONGC" in sector_map.members("Oil exploration")
    assert "BPCL" in sector_map.members("Oil refining")


# ---------------------------------------------------------------
# 4. EVENTS COME OFF THE CHANNELS, NOT OFF A CALENDAR
# ---------------------------------------------------------------
#     "bot needed live news, events which will get sourced from our
#      news channels - Day trader & News Pulse"
@pytest.mark.parametrize("headline,kind", [
    ("RBI MPC keeps repo rate unchanged", "policy"),
    ("Fed signals a rate cut in September", "policy"),
    ("Government raises gold import duty", "government"),
    ("No MDR on digital payment modes", "government"),
    ("Tensions rise in the Strait of Hormuz", "geopolitics"),
    ("OpenAI launches agent that automates back office", "disruption"),
    ("FII turn buyers after MSCI rebalance", "flows"),
])
def test_a_market_wide_headline_is_recognised(headline, kind):
    assert classify_event(headline) == kind


def test_a_single_company_headline_is_not_an_event():
    """It already has a home in the cause-and-effect panel. Showing it
    twice under two different words is the clutter he threw out."""
    assert classify_event("Titan Q1 revenue up 18% on jewellery") is None
    assert classify_event("") is None
    assert classify_event(None) is None


def test_no_event_date_is_hardcoded():
    """A date written into a source file is right briefly and wrong
    forever. The RBI MPC on 5 August 2026 is real, and it still does
    not belong in here."""
    src = open("core/awareness.py", encoding="utf-8").read()
    body = src[src.index("EVENT_WORDS"):]
    for stamp in ("2026-08-05", "2026-08", "August 5", "5 August 2026"):
        assert stamp not in body, stamp


def test_a_live_event_pulls_a_good_day_down_to_careful():
    good = dict(premarket=Store(world()), indices=idx(0.9, 12.0),
                sector_rows=sectors(1, 1, 1, 1), breadth_pct=72.0)
    assert assess(**good)["verdict"] == "Good to trade"
    with_event = assess(events=[{"headline": "RBI MPC outcome due at 10:00",
                                 "source": "Day Trader Telugu"}], **good)
    assert with_event["verdict"] == "Be careful"
    assert any(r["key"] == "event" for r in with_event["rows"])


# ---------------------------------------------------------------
# 5. THE VERDICT IS PLAIN ENGLISH
# ---------------------------------------------------------------
#     "i do not want user to trouble with some highfive name"
def test_the_verdict_is_something_he_can_act_on():
    got = assess(indices=idx(0.9, 12.0), sector_rows=sectors(1, 1, 1),
                 breadth_pct=70.0, premarket=Store(world()))
    assert got["verdict"] in ("Good to trade", "Be careful", "Stay out")


def test_no_jargon_reaches_the_reading():
    got = assess(premarket=Store(world(crude=5.0)), indices=idx(0.4, 15.0),
                 sector_rows=sectors(1, -1, 1), breadth_pct=55.0)
    text = " ".join([got["verdict"], got["headline"]]
                    + [r["line"] for r in got["rows"]]).lower()
    for word in ("regime", "risk-on", "risk off", "contested", "hysteresis",
                 "confidence", "z-score", "percentile", "beta"):
        assert word not in text, word


# ---------------------------------------------------------------
# 6. IT NEVER TAKES THE SCREEN DOWN
# ---------------------------------------------------------------
def test_nothing_wired_at_all_is_survivable():
    got = assess()
    assert got["verdict"] in ("Good to trade", "Be careful", "Stay out")
    assert len(got["rows"]) == 5


def test_an_unreadable_store_does_not_raise():
    got = assess(premarket=Store(RuntimeError("locked")),
                 market_flows=Store(RuntimeError("locked")))
    assert got["rows"]
    world_row = next(r for r in got["rows"] if r["key"] == "world")
    assert world_row["verdict"] == "unknown"


def test_every_leg_is_always_present():
    got = assess()
    assert [r["key"] for r in got["rows"]] == list(awareness.LEG_ORDER)
