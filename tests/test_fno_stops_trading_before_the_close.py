"""---- F&O STOCKS FINISH IN AN AUCTION. 31 August 2026. ----

    "FnO stocks will be traded CAS mechanism , forgot about that , why?"
                                                  -- the operator

Measurable in his own store. On 31 August, of 1,288 stocks with minute
data:

    209 have no bar after 15:14   -- ALL 209 are F&O
  1,079 traded to the close       -- exactly ONE is

F&O leaves continuous trading at 15:15 and finishes in the closing
auction. That is not the recorder failing; it is the market, and the
bot did not know which stocks it applied to.

WHAT THIS FILE GUARDS AND WHAT IT DOES NOT
------------------------------------------
It guards the MEMBERSHIP: the bot must know which stocks are F&O, and
that knowledge must not be allowed to rot. On 31 August the list was 32
days old. core/index_members.py has MAX_AGE_DAYS = 7 and an is_stale()
that was returning True, and the only caller of refresh() in the whole
repository was a tool run by hand. Three stocks -- ATHERENERG, MAHABANK
and SAGILITY -- had joined F&O since 30 July, and the bot still had
them down as ordinary cash stocks. After a refresh the list holds 211
and covers all 209.

It does NOT guard a square-off deadline, because there is no square-off:

    "no square off at all & thats deliberately avoided."

That is his design. MTF exists to hold when holding is right, and what
closes a position is the buying drying up, not a clock.

WHAT IS STILL OPEN. A stop or a buying-dried-up exit that fires at
15:20 in an F&O stock has no continuous market to fill into. In paper
that costs nothing. With real orders it is the "recorded an exit that
never happened" fault, which is the worst one available. Unsolved, and
written down here so it is not forgotten twice.
"""

import json
from pathlib import Path

import pytest


def test_the_fno_list_is_fresh_enough_to_trust():
    """It knew it was stale. MAX_AGE_DAYS = 7, is_stale() returned True,
    and nothing asked -- for 32 days."""
    from core.index_members import IndexMembers

    members = IndexMembers()
    assert not members.is_stale(), (
        "the F&O list is stale. Run py tools/index_members.py -- and it "
        "should not have got here, the nightly chain refreshes it")


def test_the_nightly_chain_refreshes_it():
    """The fix for the 32 days. A cache with an age limit and no
    scheduled refresh is a cache that is always about to be wrong."""
    from tools.nightly import STEPS

    names = [s[0] for s in STEPS]
    assert "membership" in names, (
        "nothing refreshes the F&O list -- it will go stale again")
    assert names.index("membership") < names.index("universe"), (
        "the universe step reads membership, so it must run after")


def test_the_membership_step_runs_the_real_tool():
    from tools.nightly import STEPS

    step = next(s for s in STEPS if s[0] == "membership")
    assert step[2] == ["tools/index_members.py"]


def test_the_list_covers_the_stocks_that_actually_stopped_at_1514():
    """The proof, from his own data. These three joined F&O after 30
    July and were missing from the stale list -- they are the reason the
    refresh matters. If the list ever stops matching the tape, this is
    where it shows."""
    path = Path("data/index_members.json")
    if not path.exists():
        pytest.skip("no membership cache on this machine")
    fno = {s.upper() for s in
           json.loads(path.read_text(encoding="utf-8"))["members"]["fno"]}
    for symbol in ("ATHERENERG", "MAHABANK", "SAGILITY"):
        assert symbol in fno, (
            f"{symbol} stopped trading at 15:14 on 31 August, so it is "
            f"F&O, and the list does not know it")


# ------------------------------------------------- and no square-off

def test_there_is_no_forced_square_off():
    """His design, stated twice:

        "no square off at all & thats deliberately avoided."

    MTF is there to hold when holding is right. I turned this on
    earlier the same evening because NCC and CDSL had been carried for
    ten days -- the right problem, the wrong fix. They were not carried
    for want of a daily liquidation; they were carried because nothing
    could close them at all."""
    import config

    assert config.FORCE_SQUARE_OFF_AT_CLOSE is False, (
        "a forced square-off is back. He has said twice that carrying "
        "is deliberate -- if this is being turned on, it is his call "
        "and this assertion should say so")


def test_something_can_still_close_a_winner():
    """The reason a square-off is not needed. Without this the ten-day
    hold comes straight back: the bot's own entries get no profit
    target, and a stop that is never reached closes nothing."""
    from core.engine import Engine

    assert hasattr(Engine, "_buying_dried_up"), (
        "nothing books a winner any more -- with no square-off either, "
        "a position can be held indefinitely again")
