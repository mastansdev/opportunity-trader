"""
This is the test that stops the sediment growing back.

    "why you created this bot as a mess of files? how many times i need
     to tell you don't complicate the work."
                                -- operator, 11 August 2026

He was not complaining about file count, though 429 is a lot. He was
complaining about the consequence of this:

    MIN_MOVE_PCT       four files, three values
    MIN_VOLUME_RATIO   three files, two values
    RISK_PER_TRADE_RS  config 2000, position_plan 1500

Fix one and nothing changes, because the others keep running the old
number. He configured Rs 2,000 of risk per trade and every trade the
bot ever sized risked Rs 1,500 -- silently, for weeks, with no error
anywhere, because both numbers were perfectly valid Python.

core/rules.py now owns those names. This test fails the build if any
core module declares one of them itself again.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not flag config.py, backtest/ or tools/. Two of the six names
he was shown as duplicates turned out not to be:

    MIN_STOP_DISTANCE_PCT   config 0.01 is a FRACTION used as
                            `price * 0.01` by backtest/*.py, i.e. 1%.
                            position_plan's 0.75 is a PERCENT. Same
                            name, different units, both correct.

    MIN_TURNOVER_RS         universe_builder Rs 5 Cr is an AVERAGE
                            DAY. engine's Rs 2 Cr is TRADED SO FAR
                            TODAY. Different questions.

A test that forced those together would be enforcing a bug. Merging
two rules that share a name is exactly as wrong as splitting one rule
across four files, and rather harder to notice afterwards.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def _assignments(path):
    """Top-level NAME = <literal> in this file, ignoring imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:                                    # pragma: no cover
        return {}
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, (ast.Constant, ast.UnaryOp)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                found[target.id] = node.lineno
    return found


def _owned():
    from core.rules import OWNED
    return set(OWNED)


def test_rules_declares_every_name_it_claims_to_own():
    """OWNED must not list a name rules.py forgot to define."""
    import core.rules as rules
    missing = [n for n in _owned() if not hasattr(rules, n)]
    # MIN_MOVE_PCT is listed as a name that must NEVER come back, not
    # as one rules.py provides -- it is the ambiguous name we split.
    missing = [n for n in missing if n != "MIN_MOVE_PCT"]
    assert not missing, f"core/rules.py claims but does not define: {missing}"


@pytest.mark.parametrize("path", sorted(CORE.glob("*.py")),
                         ids=lambda p: p.name)
def test_no_core_module_redeclares_a_rule(path):
    """The whole point. One owner per number."""
    if path.name in ("rules.py", "__init__.py"):
        return
    clash = sorted(set(_assignments(path)) & _owned())
    assert not clash, (
        f"{path.name} declares {clash} itself. That name belongs to "
        f"core/rules.py -- import it from there. This is the fault that "
        f"made his configured Rs 2,000 risk silently run as Rs 1,500."
    )


def test_the_numbers_he_approved_are_the_numbers_in_the_file():
    """He approved these on 11 August. Pinned so a later edit has to
    be deliberate rather than accidental."""
    from core import rules
    assert rules.RISK_PER_TRADE_RS == 1500.0
    # RAISED 1.5 -> 2.5 on 20 August 2026, on measurement rather than
    # taste: 13,272 scored signals put "under 2x normal volume" at
    # 44.3% up at close and "over 10x" at 60.0%. 1.5 sat in the worst
    # band the bot measures. This test's job is to prove the number is
    # in ONE place and was CHOSEN -- not to hold a particular value.
    assert rules.MIN_VOLUME_RATIO == 2.5
    assert rules.MIN_TRADABLE_PRICE_RS == 50.0
    assert rules.MIN_STOP_DISTANCE_PCT == 0.75
    assert rules.MAX_STOP_DISTANCE_PCT == 6.0


def test_the_two_move_thresholds_stay_apart():
    """They measure from different places. Merging them was the
    mistake that made a whole day of replays measure the wrong bot."""
    from core import rules
    assert rules.MIN_MOVE_FROM_PREV_CLOSE_PCT != \
        rules.MIN_MOVE_FROM_OPEN_PCT
    assert not hasattr(rules, "MIN_MOVE_PCT"), (
        "the ambiguous name is back -- it meant two different things")


def test_every_module_that_used_to_copy_a_rule_now_imports_it():
    """The modules that were the problem, checked by value."""
    from core import (position_plan, ranker, select, shortlist,
                      universe_builder, watchlist_builder)
    from core import rules

    assert position_plan.RISK_PER_TRADE_RS == rules.RISK_PER_TRADE_RS
    assert ranker.MIN_VOLUME_RATIO == rules.MIN_VOLUME_RATIO == 2.5
    assert select.MIN_VOLUME_RATIO == rules.MIN_VOLUME_RATIO
    assert watchlist_builder.MIN_VOLUME_RATIO == rules.MIN_VOLUME_RATIO
    assert ranker.MIN_MOVE_PCT == rules.MIN_MOVE_FROM_PREV_CLOSE_PCT
    assert select.MIN_MOVE_PCT == rules.MIN_MOVE_FROM_OPEN_PCT
    assert shortlist.MIN_MOVE_PCT == rules.SHORTLIST_MIN_MOVE_PCT == 2.0
    assert universe_builder.MIN_TURNOVER_RS == \
        rules.MIN_UNIVERSE_TURNOVER_RS


def test_the_ranker_now_applies_the_price_floor():
    """MSUMI and SEPC, 5 August: thirty candidate slots burned on two
    stocks the order gate could never accept."""
    import inspect
    from core.ranker import rank
    src = inspect.getsource(rank)
    assert "MIN_TRADABLE_PRICE_RS" in src, (
        "the ranker still scores stocks it can never buy")


# ==========================================================
# THE TWO FILES THIS TEST WAS NOT WATCHING.  12 August 2026.
# ==========================================================
#
# The header above says, deliberately, "it does not flag config.py".
# That exemption was written for MIN_STOP_DISTANCE_PCT and
# MIN_TURNOVER_RS, which genuinely mean different things in the two
# places -- and it silently covered RISK_PER_TRADE_RS too, which does
# not. config.py said 2,000, core/rules.py said 1,500, and BOTH were
# live: core/engine.py sized its own entries off config's and
# core/position_plan.py sized the ranker's off rules'.
#
# So the file whose entire job is to stop this exact fault could not
# see the most expensive instance of it, and AUDIT_2026-08-12.md
# recorded RISK_PER_TRADE_RS as "legacy, sizes nothing" while it was
# sizing every trade the engine made.
#
# The blanket exemption is gone. Names still genuinely different in
# config are listed one by one, with the reason, instead.

#: Names config.py may hold its own value for, because they answer a
#: different question there. Each needs a reason, not a category.
CONFIG_MAY_DIFFER = {
    # A FRACTION (price * 0.01 = 1%), read by backtest/*.py. rules'
    # 0.75 is a PERCENT. Same name, different units, both correct.
    "MIN_STOP_DISTANCE_PCT",
    # Rs 2 Cr TRADED SO FAR TODAY, read by core/engine.py's liquidity
    # floor. rules' MIN_UNIVERSE_TURNOVER_RS is an AVERAGE DAY.
    "MIN_TURNOVER_RS",
    # The engine's own book cap is read from core/capital.py against
    # the real balance; this is the fallback when that cannot be read.
    "MAX_OPEN_POSITIONS",
    # Margin Dhan blocks per MTF position. Same number in both places
    # and read from config by main.py's funding checks.
    "MTF_MARGIN_PER_POSITION_RS",
    # The price floor, same value, enforced at the order gate.
    "MIN_TRADABLE_PRICE_RS",
}


def test_config_does_not_hold_a_rival_value_for_an_owned_rule():
    import config
    from core import rules
    clash = []
    for name in sorted(_owned()):
        if name in CONFIG_MAY_DIFFER or name == "MIN_MOVE_PCT":
            continue
        if not hasattr(config, name) or not hasattr(rules, name):
            continue
        if getattr(config, name) != getattr(rules, name):
            clash.append(f"{name}: config={getattr(config, name)} "
                         f"rules={getattr(rules, name)}")
    assert not clash, (
        "config.py disagrees with core/rules.py about: "
        + "; ".join(clash)
        + ". Either import it from core/rules.py, or add it to "
          "CONFIG_MAY_DIFFER with the reason it means something else."
    )


def test_both_entry_lanes_risk_the_same_money():
    """THE ONE THAT WAS ACTUALLY COSTING SOMETHING.

    core/engine.py reaches _enter() from an ORB breakout.
    core/position_plan.py sizes what the ranker sends to the same
    _enter(). If these two disagree, the bot risks a different amount
    depending on which half of itself found the trade -- and neither
    number is wrong on its own, so nothing ever errors.
    """
    import config
    from core import engine, position_plan, rules
    budgets = {
        "core/rules.py (the owner)": rules.RISK_PER_TRADE_RS,
        "core/engine.py (ORB lane)": engine.RISK_PER_TRADE_RS,
        "core/position_plan.py (ranker lane)": position_plan.RISK_PER_TRADE_RS,
        "config.py (read by backtest/)": config.RISK_PER_TRADE_RS,
    }
    assert len(set(budgets.values())) == 1, (
        "the two entry lanes are sizing to different risk budgets: "
        + ", ".join(f"{k} = Rs {v:,.0f}" for k, v in budgets.items())
    )
    assert rules.RISK_PER_TRADE_RS == 1500.0
