"""
==========================================================
Built at both ends, dropped in the middle
==========================================================

core/auto_entry.take() stamps the fingerprint onto the position at the
instant it decides: door, volume_x, jump_x, liveness, off_high_pct,
run_up_pct, move_age_min, reason_kind, reason_pct_of_company.
core/trade_memory.record() reads every one of them back and has a
column for each.

Both ends were built. Both ends were wired. The middle hop dropped
them: _exit() rebuilt the closed row from a hand-written list of keys
that did not contain the fingerprint, so record() read None every time.

    All 95 trades, 7-10 September:  door = NULL, move_age_min = NULL

That is why "which door made money" and "were we late?" had to be
answered by replaying minute candles, instead of by asking the store
the question it was built to answer.

The partial-exit row was worse: it dropped the sector and the reason as
well, so a trimmed trade recorded strictly less than a full one. Two
hand-written lists, drifting apart -- the same shape of fault as the
switch and TRADING_MODE.

ONE LIST NOW. core/engine.CARRIED_FROM_ENTRY is used by both exit
paths, so a key added there reaches every closed trade by every route.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.engine import CARRIED_FROM_ENTRY, _carried_from_entry

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The nine stamped by core/auto_entry.take().
FINGERPRINT = (
    "door", "volume_x", "jump_x", "liveness", "off_high_pct",
    "run_up_pct", "move_age_min", "reason_kind", "reason_pct_of_company",
)


def test_the_fingerprint_is_carried():
    """THE CASE. Nine keys, stamped at entry, read at record, and not
    in the closed row."""
    for key in FINGERPRINT:
        assert key in CARRIED_FROM_ENTRY, f"{key} is dropped at exit again"


def test_the_reason_is_carried_too():
    for key in ("sector", "news_kind", "filing_kind", "results_grade",
                "days_since_results", "had_reason", "reason_summary",
                "rel_strength", "regime"):
        assert key in CARRIED_FROM_ENTRY


def test_a_missing_value_is_none_not_an_error():
    """A position that never got a fingerprint (a manual buy, a restart)
    must still close. None means the bot could not say."""
    got = _carried_from_entry({"door": "NEWS"})
    assert got["door"] == "NEWS"
    assert got["move_age_min"] is None
    assert set(got) == set(CARRIED_FROM_ENTRY)


def test_it_survives_an_empty_position():
    assert _carried_from_entry({}) == {k: None for k in CARRIED_FROM_ENTRY}
    assert _carried_from_entry(None) == {k: None for k in CARRIED_FROM_ENTRY}


# ---------------------------------------------------------------
# BOTH EXIT PATHS, ONE LIST
# ---------------------------------------------------------------

def _engine_src():
    return (ROOT / "core" / "engine.py").read_text(encoding="utf-8")


def test_both_exit_paths_use_the_one_list():
    """A second hand-written copy is what caused this. There are two
    places that build a closed row and both must go through the list."""
    src = _engine_src()
    assert src.count("self.closed_positions.append({") == 2, (
        "a third closed-row builder appeared -- it must use "
        "_carried_from_entry() too")
    assert src.count("**_carried_from_entry(position),") == 2, (
        "one of the exit paths is hand-writing its keys again")


def test_the_partial_exit_is_not_poorer_than_the_full_one():
    """A trimmed trade is a closed trade. It used to record no sector,
    no reason and no fingerprint at all."""
    src = _engine_src()
    first = src.index("self.closed_positions.append({")
    second = src.index("self.closed_positions.append({", first + 1)
    partial = src[first:second]
    assert "**_carried_from_entry(position)," in partial


def test_trade_memory_still_reads_every_carried_key():
    """The other end of the hop. If record() stops reading one, the
    column silently goes back to NULL and nothing here would notice."""
    src = (ROOT / "core" / "trade_memory.py").read_text(encoding="utf-8")
    for key in FINGERPRINT:
        assert f'closed_position.get("{key}")' in src or \
               f'"{key}"' in src, f"record() no longer reads {key}"


def test_auto_entry_still_stamps_every_fingerprint_key():
    """The first end of the hop."""
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    block = src[src.index("engine.entry_facts = {"):]
    block = block[:block.index("}")]
    for key in FINGERPRINT:
        assert f'"{key}"' in block, f"auto_entry no longer stamps {key}"
