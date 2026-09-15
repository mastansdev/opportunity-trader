"""
==========================================================
A stock he can never buy does not belong in the money table
==========================================================

    "why stocks with below 50 rs cmp is showing on dashboard? we are
     not trading them right?"     -- operator, 17 August 2026

Right on both counts, and the answer is a category error in the
screen rather than a bug in the rules.

config.MIN_TRADABLE_PRICE_RS is an ENTRY rule. core/engine.py checks
it twice -- at the breakout gate and again inside _enter() -- and
data/decisions.db has 1,075 refusals reading "under the Rs 50 floor
-- never tradeable". It appears NOWHERE in dashboard/state.py or
core/ranker.py, because it was never a display rule.

The Live table merges three sources, and one of them is the raw
gainers list, which is built from PRICES rather than from the
tradeable universe. So a Rs 12 stock that moved 9% arrived at the top
of the one table he asked to be "the money".

    "this line is not worth at top place ... the main centre page
     belongs to money generating table with stocks worth having a
     priority than others"          -- operator, 9 August 2026

PERMANENT versus SITUATIONAL. Under the floor is a fact about the
stock and will be true tomorrow. "No volume behind it" or "fading" is
a fact about today and is worth reading -- those refusals still show.
Only the never-tradeable ones are dropped, and only from this table:
the row stays in the snapshot, so WHY and the stock card still answer
for it.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOARD = ROOT / "dashboard" / "static" / "board.html"


def test_the_snapshot_publishes_the_floor():
    """The screen must not carry its own copy of a rule -- that is the
    sediment core/rules.py exists to prevent."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert '"min_tradable_price"' in src
    assert "MIN_TRADABLE_PRICE_RS" in src


def test_the_engine_still_refuses_them_itself():
    """The screen change must not be mistaken for the rule. The entry
    gate is where it actually matters."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    assert src.count("min_tradable_price") >= 3, (
        "the entry-side floor was weakened while tidying the screen")
