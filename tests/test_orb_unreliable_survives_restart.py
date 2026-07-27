"""
"This range can't be trusted" must survive a restart.

Operator-found live on 2026-07-27, from that day's own log:

    09:16  TBZ went stale INSIDE its own ORB window -- range flagged
           unreliable; structural entries skipped for it today.
    ...
    14:59  PAPER BUY TBZ qty=729 @ 274.15 (STRUCTURAL_LONG_BREAKOUT)

The feed went quiet for TBZ during the fifteen minutes the bot was
measuring its opening range, so the range may have missed the real high
or low entirely (the SONACOMS incident). MarketData flagged it and the
engine correctly refused structural entries in it.

Then the bot was restarted twice. The flag lived only in memory, so it
was forgotten, and at 14:59 the bot took the exact trade it had already
ruled out -- on a range built around a hole in the data.

That trade made Rs 4,993, which is the worst possible outcome: a rule
that silently stops applying looks harmless right up until it isn't,
and a profit earned by ignoring it is not evidence of anything.
"""

import json
import os

from core import state_store
from core.market_data import MarketData


def _md():
    try:
        return MarketData()
    except TypeError:
        return MarketData.__new__(MarketData)


def test_the_flag_round_trips_through_the_state_file(tmp_path):
    path = os.path.join(str(tmp_path), "state.json")
    state_store.save({}, {}, orb_unreliable=["TBZ", "SONACOMS"], path=path)
    assert sorted(state_store.load_orb_unreliable(path=path)) == \
        ["SONACOMS", "TBZ"]


def test_a_flag_from_a_different_day_is_ignored(tmp_path):
    """Yesterday's dead feed says nothing about today's range."""
    path = os.path.join(str(tmp_path), "state.json")
    state_store.save({}, {}, orb_unreliable=["TBZ"], path=path)
    payload = json.load(open(path))
    payload["date"] = "1999-01-01"
    json.dump(payload, open(path, "w"))
    assert state_store.load_orb_unreliable(path=path) == []


def test_missing_file_is_not_an_error(tmp_path):
    assert state_store.load_orb_unreliable(
        path=os.path.join(str(tmp_path), "nope.json")) == []


def test_restoring_marks_the_symbol_unreliable_again():
    md = _md()
    md._orb_window_stale_symbols = set()
    assert md.is_orb_window_unreliable("TBZ") is False
    md.load_orb_unreliable(["TBZ"])
    assert md.is_orb_window_unreliable("TBZ") is True, \
        "TBZ is tradeable again after a restart -- this is the 2026-07-27 bug"


def test_restoring_MERGES_and_never_drops_a_live_flag():
    """One-way flag: anything flagged since the snapshot was written is
    just as real as what's in it. Overwriting either way re-opens the
    hole this exists to close."""
    md = _md()
    md._orb_window_stale_symbols = {"LIVEFLAG"}
    md.load_orb_unreliable(["FROMDISK"])
    assert md.is_orb_window_unreliable("LIVEFLAG") is True
    assert md.is_orb_window_unreliable("FROMDISK") is True


def test_restoring_nothing_changes_nothing():
    md = _md()
    md._orb_window_stale_symbols = {"KEEP"}
    md.load_orb_unreliable([])
    md.load_orb_unreliable(None)
    assert md.is_orb_window_unreliable("KEEP") is True


def test_old_callers_that_pass_no_flag_still_work(tmp_path):
    """save() is called from several places; none may break."""
    path = os.path.join(str(tmp_path), "state.json")
    state_store.save({"X": {"high": 1, "low": 0, "complete": True}}, {},
                     path=path)
    assert state_store.load_orb_unreliable(path=path) == []
