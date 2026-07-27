"""
Restored entry blocks must not outlive the rule that created them.

2026-07-27: BLOCK_REENTRY_AFTER_STOPOUT was switched off mid-session
and the bot restarted. AUBANK and CAPLIPOINT had been blocked before
the restart, the blocks were in the state snapshot, and
_try_structural_entry reads self.entry_blocked directly with no flag
check -- so both stayed locked out by a rule that was no longer live.

The fix filters on the way in, at load_entry_blocks(). These tests pin
the two halves that matter: strategy blocks go, factual blocks stay.
"""

import core.engine as engine_module
from core.engine import Engine


def _engine():
    return Engine()


def test_stopout_blocks_are_dropped_when_the_rule_is_off(monkeypatch):
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", False)
    engine = _engine()
    engine.load_entry_blocks({
        "AUBANK": {"LONG": "stopped out once today -- no repeat attempts "
                           "in the same direction"},
        "CAPLIPOINT": {"LONG": "stopped out once today -- no repeat "
                               "attempts in the same direction"},
    })
    assert engine.entry_blocked == {}


def test_circuit_proximity_blocks_are_dropped_too(monkeypatch):
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", False)
    engine = _engine()
    engine.load_entry_blocks({
        "STYL": {"SHORT": "flagged near its circuit limit once today -- "
                          "no repeat attempts in the same direction"},
    })
    assert engine.entry_blocked == {}


def test_stopout_blocks_survive_while_the_rule_is_on(monkeypatch):
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", True)
    engine = _engine()
    blocks = {"AUBANK": {"LONG": "stopped out once today -- no repeat "
                                 "attempts in the same direction"}}
    engine.load_entry_blocks(blocks)
    assert engine.entry_blocked == blocks


def test_corporate_action_blocks_are_never_dropped(monkeypatch):
    """A split is a fact about the stock, not a strategy choice. It must
    survive regardless of how the re-entry rule is set -- this is the
    JLHL class of bug (a 2:10 split read as -80%)."""
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", False)
    engine = _engine()
    blocks = {
        "JLHL": {"LONG": "corporate action today -- SPLIT. Price is not "
                         "comparable to yesterday's close"},
    }
    engine.load_entry_blocks(blocks)
    assert engine.entry_blocked == blocks


def test_a_symbol_keeps_its_factual_block_and_loses_its_strategy_one(
        monkeypatch):
    """Same symbol, both kinds of block on different directions."""
    monkeypatch.setattr(engine_module, "BLOCK_REENTRY_AFTER_STOPOUT", False)
    engine = _engine()
    engine.load_entry_blocks({
        "X": {
            "LONG": "stopped out once today -- no repeat attempts in the "
                    "same direction",
            "SHORT": "corporate action today -- BONUS. Price is not "
                     "comparable to yesterday's close",
        },
    })
    assert "LONG" not in engine.entry_blocked["X"]
    assert "SHORT" in engine.entry_blocked["X"]
