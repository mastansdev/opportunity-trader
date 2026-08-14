"""
==========================================================
A call that rewrites itself is not a call
==========================================================

    "in dashboard chips are changing constantly - on Yasho some times
     AVOID, BUY, WAIT, EXCELLENT"
                        -- operator, 3 August 2026, first live session

He was holding YASHO and watching the one chip that is supposed to tell
him what to do change its mind every second.

WHY
---
call() is pure and gets recomputed on every dashboard refresh -- once a
second -- from two facts that move with price:

    falling_hard    change_pct <= -3.0
    volume_absent   vol_ratio  <   1.5

YASHO traded 4090 -> 4199 -> 4002 -> 4077 that morning. It crossed
-3.0% repeatedly. Every crossing rewrote the chip, so BUY, AVOID and
WAIT all appeared within seconds of each other while he was deciding
whether to hold.

EXCELLENT beside AVOID was NOT a contradiction, incidentally -- that is
the publisher's grade on the result, which does not change, next to a
live read on the price, which does. But the panel gave no hint they
were different kinds of thing, so it read as the bot arguing with
itself.

THE TWO GUARDS
--------------
A BAND, so the threshold itself stops flickering: once a stock is
called falling_hard it must recover MEANINGFULLY before that clears,
not by a hundredth of a percent.

A MINIMUM HOLD, for everything else: a new call must survive twenty
seconds before it replaces what is on screen. A genuine move through
the band still lands almost immediately; noise never does.

WHAT THIS MUST NOT DO
---------------------
Slow down a real signal, or show a stale one. A stock that truly falls
through the band and stays there gets its AVOID -- and the FIRST call
for a symbol is never delayed, because there is nothing on screen yet
to protect.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.chain import (AVOID, BUY, WAIT, HOLD_SECONDS, SteadyCall, call,
                        steady_facts)


def facts(pct, vol=3.0, layers=2):
    """A row that would read BUY but for the price."""
    return {
        "layers": layers,
        "strong_result": True,
        "vol_ratio": vol,
        "volume_confirms": vol >= 1.5,
        "volume_absent": vol < 1.5,
        "change_pct": pct,
        "falling_hard": pct <= -3.0,
    }


# ---------------------------------------------------------------
# 1. YASHO'S MORNING
# ---------------------------------------------------------------
def test_a_price_hovering_at_the_threshold_does_not_flip_the_chip():
    """The complaint, replayed at one-second refreshes."""
    steady = SteadyCall(hold_seconds=20)
    shown = set()
    for i, pct in enumerate([1.5, -2.9, -3.1, -2.8, -3.2, -2.95, -3.05]):
        shown.add(steady("YASHO", facts(pct), now=float(i)))
    assert shown == {BUY}, f"the chip changed: {shown}"


def test_the_raw_call_really_does_flip_underneath():
    """Proof the test above is testing something. Without the guard,
    these same inputs produce three different answers."""
    raw = {call(facts(pct)) for pct in (-2.9, -3.1, -2.8, -3.2)}
    assert len(raw) > 1


# ---------------------------------------------------------------
# 2. A REAL MOVE STILL GETS THROUGH
# ---------------------------------------------------------------
def test_a_genuine_fall_that_persists_does_change_the_call():
    steady = SteadyCall(hold_seconds=20)
    steady("YASHO", facts(1.5), now=0)
    for t in range(1, 40):
        got = steady("YASHO", facts(-6.0), now=float(t))
    assert got == AVOID


def test_it_changes_as_soon_as_the_hold_elapses_and_not_before():
    """The clock starts when the new call is FIRST PROPOSED, not when
    the old one was set.

    My first version of this test asserted a flip at t=20.1 having
    proposed AVOID at t=5, and it failed -- correctly. Twenty seconds
    of the NEW answer is the promise; anything else would mean a call
    made at 09:29:59 could be replaced at 09:30:00 by one that had been
    true for a single second.
    """
    steady = SteadyCall(hold_seconds=20)
    steady("YASHO", facts(1.5), now=0)
    assert steady("YASHO", facts(-6.0), now=5) == BUY      # proposed here
    assert steady("YASHO", facts(-6.0), now=24.9) == BUY   # 19.9s of it
    assert steady("YASHO", facts(-6.0), now=25.1) == AVOID  # 20.1s of it


def test_the_first_call_for_a_symbol_is_never_delayed():
    """There is nothing on screen yet, so there is nothing to protect."""
    steady = SteadyCall(hold_seconds=20)
    assert steady("NEWNAME", facts(-6.0), now=0) == AVOID


def test_a_candidate_that_changes_its_mind_resets_the_clock():
    """AVOID for ten seconds, then WAIT, must not inherit the ten."""
    steady = SteadyCall(hold_seconds=20)
    steady("X", facts(1.5), now=0)
    steady("X", facts(-6.0), now=1)          # candidate AVOID
    steady("X", facts(0.5, vol=0.2), now=11)  # candidate becomes WAIT
    assert steady("X", facts(0.5, vol=0.2), now=25) == BUY, (
        "the WAIT has only been waiting 14s, not 24s")
    assert steady("X", facts(0.5, vol=0.2), now=32) == WAIT


# ---------------------------------------------------------------
# 3. THE BAND
# ---------------------------------------------------------------
def test_once_avoiding_a_hair_of_recovery_does_not_clear_it():
    """-3.00% to -2.99% is not news."""
    assert steady_facts(facts(-2.9), previous=AVOID)["falling_hard"] is True


def test_a_real_recovery_does_clear_it():
    assert steady_facts(facts(-1.0), previous=AVOID)["falling_hard"] is False


def test_the_band_only_applies_once_it_is_already_avoiding():
    """Widening the threshold for a stock that was fine would make the
    call MORE eager to turn negative, which is the opposite of the
    point."""
    assert steady_facts(facts(-2.9), previous=BUY)["falling_hard"] is False


def test_the_volume_band_works_the_same_way():
    got = steady_facts(facts(1.0, vol=1.6), previous=WAIT)
    assert got["volume_absent"] is True
    assert steady_facts(facts(1.0, vol=1.9), previous=WAIT)["volume_absent"] is False


def test_a_missing_price_or_volume_is_left_alone():
    """No number, no band. It must not invent a flag that was not there."""
    bare = {"layers": 2, "strong_result": True}
    assert steady_facts(bare, previous=AVOID) == bare


# ---------------------------------------------------------------
# 4. SYMBOLS DO NOT LEAK INTO EACH OTHER
# ---------------------------------------------------------------
def test_two_symbols_are_held_independently():
    steady = SteadyCall(hold_seconds=20)
    assert steady("AAA", facts(1.5), now=0) == BUY
    assert steady("BBB", facts(-6.0), now=0) == AVOID
    assert steady("AAA", facts(1.5), now=1) == BUY


def test_the_symbol_is_matched_case_insensitively():
    steady = SteadyCall(hold_seconds=20)
    steady("yasho", facts(1.5), now=0)
    assert steady("YASHO", facts(-6.0), now=1) == BUY


def test_it_reports_when_the_call_last_changed():
    """A chip that can say when it decided is honest. One that silently
    rewrites itself is the thing being fixed."""
    steady = SteadyCall(hold_seconds=20)
    steady("X", facts(1.5), now=100.0)
    assert steady.since("X") == 100.0
    assert steady.since("NEVERSEEN") is None


# ---------------------------------------------------------------
# 5. IT IS ACTUALLY WIRED IN
# ---------------------------------------------------------------
def test_the_shortlist_uses_the_steady_call():
    src = open("core/shortlist.py", encoding="utf-8").read()
    assert '"chain_state": self._steady_call(symbol, chain_facts),' in src
    assert "self._steady_call = SteadyCall()" in src


def test_one_builder_holds_one_memory_across_refreshes():
    """A SteadyCall built fresh inside rank() would remember nothing and
    the chip would flicker exactly as before."""
    from core.shortlist import ShortlistBuilder
    builder = ShortlistBuilder()
    first = builder._steady_call
    builder.rank([{"symbol": "ZZFIXTURE", "ltp": 100.0, "change_pct": 1.0,
                   "sector": "Chemicals"}], top=5, today="2026-08-03")
    assert builder._steady_call is first


def test_the_chip_does_not_flicker_through_the_real_builder():
    from core.shortlist import ShortlistBuilder
    builder = ShortlistBuilder()
    seen = set()
    for pct in (6.1, -3.1, -2.9, -3.2, -2.8, -3.4):
        out = builder.rank([{"symbol": "ZZFIXTURE", "ltp": 100.0,
                             "change_pct": pct, "sector": "Chemicals"}],
                           top=5, today="2026-08-03")
        rows = out.get("rows") or []
        if rows:
            seen.add(rows[0].get("chain_state"))
    assert len(seen) == 1, f"the chip still flickers: {seen}"


def test_the_default_hold_is_long_enough_to_read():
    assert HOLD_SECONDS >= 10
