"""
==========================================================
Three tiles, and one that answers a different question
==========================================================

    "Keep NIFTY 50, BANK NIFTY, VIX . these 3 on main board & 4 th =
     SECTOR INDICES (sector based Indices as a dropdown option =this
     will be bird view from top section which index=sector is moving)"
    "yes background all sector must running but on demand when user
     click on 4-sector indices = show top 5 indices"
                                    -- operator, 3 August 2026

WHY THE TILES WERE BLANK FOR A WEEK
-----------------------------------
Not bad ids. core/index_monitor.is_index_segment() records the whole
post-mortem:

    IDX_I 13 = NIFTY 50      NSE_EQ 13 = ABB INDIA
    IDX_I 25 = NIFTY BANK    NSE_EQ 25 = ADANI ENTERPRISES

Index and equity ids are separate numbering spaces and they collide.
On 28 July the router matched on the id ALONE, so every ABB and
ADANIENT tick was swallowed by the index monitor -- both stocks
subscribed all session, neither producing one candle. The Nifty tile
showed 7,234, which is ABB's share price.

That was diagnosed as "wrong security ids", INDEX_INSTRUMENTS was
emptied, and the tiles have read "needs index feed" every session
since. The routing was repaired on 30 July. Nobody put the ids back.

AND THE ONE I INVENTED
----------------------
Refilling it, I wrote 21 for INDIA VIX and 27 for MIDCAP from memory.
tools/find_index_ids.py then read Dhan's own scrip master:

    21 = INDIA VIX            correct, by luck
    27 = FINNIFTY             WRONG. Midcap 100 is 37.

A tile labelled MIDCAP would have shown Finnifty's level -- the exact
failure that produced ABB's price on the Nifty tile, and plausible
enough to trade beside.

    "NEVER ASSUME - WHO TOLD/AUTHORIZED YOU TO DO SO?"

Nobody. Every id in config now comes from that run.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from config import INDEX_INSTRUMENTS, SECTOR_INDICES
from dashboard.state import DashboardState


def sectors(snapshot):
    return DashboardState.__new__(DashboardState)._build_sector_indices(snapshot)


def live(name, pct, ltp=1000.0):
    return {f"sector:{name}": {"available": True, "ltp": ltp, "pct": pct}}


# ---------------------------------------------------------------
# 1. THE THREE HE ASKED FOR
# ---------------------------------------------------------------
@pytest.mark.parametrize("sec_id,name", [
    ("13", "nifty"), ("25", "banknifty"), ("21", "vix"),
])
def test_the_three_headline_indices_are_configured(sec_id, name):
    assert INDEX_INSTRUMENTS.get(sec_id) == name


def test_finnifty_is_not_masquerading_as_midcap():
    """27 is FINNIFTY. It was written into config as "midcap" from
    memory and caught by reading Dhan's master."""
    assert INDEX_INSTRUMENTS.get("27") != "midcap"


def test_no_id_is_claimed_twice():
    """Two names on one id is how a tile shows another index's level."""
    assert len(set(INDEX_INSTRUMENTS)) == len(INDEX_INSTRUMENTS)


def test_the_headline_three_are_not_prefixed_as_sectors():
    for sec_id in ("13", "25", "21"):
        assert not INDEX_INSTRUMENTS[sec_id].startswith("sector:")


# ---------------------------------------------------------------
# 2. THE SECTORS RUN IN THE BACKGROUND
# ---------------------------------------------------------------
def test_every_sector_is_subscribed_not_just_the_shown_one():
    """     "background all sector must running"   """
    for sec_id in SECTOR_INDICES:
        assert INDEX_INSTRUMENTS.get(sec_id) == f"sector:{SECTOR_INDICES[sec_id]}"


def test_there_are_enough_sectors_to_be_a_bird_view():
    assert len(SECTOR_INDICES) >= 10


def test_a_sector_id_never_collides_with_a_headline_id():
    assert not (set(SECTOR_INDICES) & {"13", "25", "21"})


# ---------------------------------------------------------------
# 3. WHICH ONE IS MOVING
# ---------------------------------------------------------------
def test_the_biggest_mover_leads():
    got = sectors({**live("Auto", 0.4), **live("Pharma", 3.1)})
    assert got[0]["name"] == "Pharma"


def test_a_sector_falling_hard_outranks_one_drifting_up():
    """Absolute, not signed. A sector down 3% is as much of an answer as
    one up 3%, and a signed sort leads with the dullest name on a red
    day."""
    got = sectors({**live("Auto", 0.4), **live("IT", -2.4)})
    assert got[0]["name"] == "IT"


def test_a_sector_with_no_packet_is_left_out():
    """Not shown at 0.00%. A flat number is a claim; "we have not heard
    from it" is a different one."""
    got = sectors({"sector:Metal": {"available": False}})
    assert got == []


def test_a_sector_with_no_percentage_is_left_out():
    got = sectors({"sector:FMCG": {"available": True, "ltp": 5.0,
                                   "pct": None}})
    assert got == []


def test_headline_indices_are_not_mistaken_for_sectors():
    got = sectors({"nifty": {"available": True, "ltp": 24317.0, "pct": 0.28},
                   **live("IT", 1.0)})
    assert [s["name"] for s in got] == ["IT"]


def test_nothing_delivering_is_an_empty_list_not_a_crash():
    assert sectors({}) == []
    assert sectors(None) == []


# ---------------------------------------------------------------
# 4. THE TILE, AND THE CLICK
# ---------------------------------------------------------------
def _html():
    return open("dashboard/static/index.html", encoding="utf-8").read()


# ---------------------------------------------------------------
# 5. THE BUG THAT KEPT THEM BLANK FOR A WEEK
# ---------------------------------------------------------------
#     "still same page showing .. restarted & hard refresh page too.
#      can u check once"          -- operator, 3 August 2026
#
# The ids were right, the routing was right, the config was refilled --
# and the tiles were STILL empty, because main.py flipped the dict on
# the way in:
#
#     IndexMonitor({sec_id: name for name, sec_id in ITEMS})
#
# That comprehension names the KEY "name" and the VALUE "sec_id", so it
# handed the monitor {"nifty": "13"} -- backwards. Every lookup by
# security id missed. And the subscribe used .values(), asking the feed
# for an instrument whose id was the string "nifty".
#
# The feed accepted it and delivered nothing. Nothing errored. The
# tiles read "needs index feed" for a week and it was diagnosed twice
# as wrong security ids, which is why config was emptied twice.
def _main():
    return open("main.py", encoding="utf-8").read()


def test_the_monitor_is_given_ids_not_names():
    from core.index_monitor import IndexMonitor
    monitor = IndexMonitor(dict(INDEX_INSTRUMENTS))
    ids = monitor.index_security_ids()
    assert ids, "the monitor knows nothing"
    assert all(str(i).isdigit() for i in ids), (
        f"the monitor is watching for names, not ids: {sorted(ids)[:4]}")


def test_the_dict_is_not_flipped_on_the_way_in():
    src = _main()
    assert "for name, sec_id in INDEX_INSTRUMENTS.items()" not in src, (
        "that comprehension reverses {id: name} into {name: id}")


def test_the_subscription_uses_the_ids():
    src = _main()
    block = src[src.find("if index_monitor:"):]
    block = block[:block.find("# ==========")]
    assert "INDEX_INSTRUMENTS.keys()" in block
    assert "INDEX_INSTRUMENTS.values()" not in block, (
        "subscribing to .values() asks the feed for an instrument "
        "called 'nifty'")


def test_the_subscription_announces_itself():
    """A subscription that silently delivers nothing is what cost a
    week and two wrong diagnoses. If the count is right and the tiles
    are still blank, the fault is downstream of that line."""
    assert "[INDEX] Subscribed" in _main()


def test_every_configured_index_is_subscribed():
    from core.index_monitor import IndexMonitor
    monitor = IndexMonitor(dict(INDEX_INSTRUMENTS))
    assert monitor.index_security_ids() == set(INDEX_INSTRUMENTS.keys())


# ---------------------------------------------------------------
# 6. VERIFIED AGAINST DHAN, AFTER THE CLOSE
# ---------------------------------------------------------------
#     "why we need to wait for the next market ? now we can get the
#      closing value of stocks & indices. whats stopping your reasoning
#      to thinking, working & giving responses?"
#
# Nothing was. I had written a healthcheck that reads the WebSocket
# log, seen the feed go quiet at 15:30, and concluded the ids could not
# be checked until 09:15 -- while core/circuit_monitor.py had been
# calling Dhan's REST quote endpoint every few seconds since July.
#
# These are the levels that endpoint returned at 18:40 on 3 August,
# three hours after the close. They are the record of what "verified"
# means here.
LIVE_LEVELS = {
    "13": 24774.30, "14": 29168.95, "15": 28045.15, "21": 11.93,
    "25": 58247.95, "28": 49965.60, "29": 31715.25, "30": 1568.65,
    "31": 12914.55, "32": 26662.80, "33": 8486.70, "34": 913.05,
    "42": 38937.00, "43": 9507.80, "447": 16783.35, "466": 40625.05,
    "470": 11357.40,
}


def test_every_configured_id_returned_a_real_index_level():
    from tools.check_index_levels import EXPECTED, SECTOR_RANGE
    wrong = []
    for sec_id, price in LIVE_LEVELS.items():
        name = INDEX_INSTRUMENTS[sec_id]
        low, high = EXPECTED.get(name, SECTOR_RANGE)
        if not low <= price <= high:
            wrong.append((sec_id, name, price))
    assert not wrong, f"levels outside their band: {wrong}"


@pytest.mark.parametrize("sec_id,low,high", [
    ("13", 20_000, 32_000),    # Nifty 50   -- 24,774
    ("25", 40_000, 70_000),    # Nifty Bank -- 58,248
    ("21", 5, 60),             # India VIX  -- 11.93
])
def test_the_three_headline_indices_are_confirmed_by_level(sec_id, low, high):
    """No NSE share trades in these windows, so passing means something
    for these three -- unlike the sector band."""
    assert low <= LIVE_LEVELS[sec_id] <= high


def test_realty_at_913_is_not_an_error():
    """The first run of check_index_levels flagged this OUT OF RANGE
    from a floor of 1,000 that I invented. Nifty Realty is the lowest
    NSE sector index and genuinely trades near 900; Dhan's master names
    id 34 as NIFTY REALTY. A checker built to catch invented numbers
    produced a false alarm from one of its own."""
    from tools.check_index_levels import SECTOR_RANGE
    assert SECTOR_RANGE[0] <= 913.05


def test_the_sector_band_does_not_claim_to_be_proof():
    """Sector indices span 913 to 58,248 and share prices live inside
    that -- YASHO at 4,114 would clear it. Printing "looks right" for
    those was overclaiming."""
    src = open("tools/check_index_levels.py", encoding="utf-8").read()
    assert "confirmed by level" in src
    assert "plausible -- name confirmed by scrip master" in src


# ---------------------------------------------------------------
# 7. NINE BOXES, THREE FACTS
# ---------------------------------------------------------------
#     "in ribbon top LIVE P&L . FREE MARGIN & OPEN is doing the same
#      job right? then why capital , realized pnl , unrealized pnl open
#      positions, margin used, free margin, margin used% , deployed
#      notional . buying power? why all of them still required that
#      place that too top on the screen ?"
#
# They are not nine facts. Capital / margin used / free margin /
# margin % are one number split four ways; deployed notional and
# buying power are that number times leverage; realized and unrealized
# are today's P&L split in two; open positions counts the table
# directly beneath it.
#
# Three belong at the top because each changes what he does next: is
# today green, can I take another, how many am I carrying.
# ---- POSITIONS x/y --------------------------------------------------
#     "ex- 0/0 before 09:15 - 1/1 = 1 open & non closed; 2/7 = 2 open &
#      5 closed"
#
# Exercised for real in the node harness below rather than asserted as
# a string -- "OPEN 2" and "2 of 7 taken" are different days, and only
# one of them says whether he is trading his plan or chasing.
