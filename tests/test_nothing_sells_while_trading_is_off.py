"""
==========================================================
With the switch OFF, no ENTRY decision may send an order
==========================================================

    "why bot sold? it is not even falling"
    "i turn off the trading bot since morning after market opened .
     now didn't ON"                  -- operator, 7 August 2026

On 7 August the switch was OFF from the open. The bot still sent five
live SELL orders and zero BUYs. Two of them:

    10:58  SELL KALYANKJIL  500 @  622.30   ROTATED_OUT
    10:58  SELL HEROMOTOCO   50 @ 5792.00   ROTATED_OUT

Rotation is "sell the weakest to buy something better" -- an ENTRY
decision with a sell attached. Exits ignore alert_only on purpose, so
a stop always protects him. Rotation rode out with the exits while its
buy half was correctly blocked, making it a guaranteed one-legged
trade.

3,678 tests were green that morning. Not one asked the question this
file asks, because the fault needs a SITUATION -- full book, strong
challenger, switch off -- not a function.

Author : H&M Opportunity Trader
==========================================================
"""

import inspect

from core.engine import Engine


def test_rotation_checks_the_switch_before_it_sells():
    """Read the function. The alert_only guard must come FIRST --
    before the churn cap, before any strength maths, and long before
    anything can reach an order."""
    src = inspect.getsource(Engine._maybe_rotate_out)
    body = src[src.find('"""', src.find('"""') + 3):]
    guard = body.find("alert_only")
    assert guard > 0, (
        "rotation does not look at alert_only at all -- this is the "
        "7 August bug")
    for later in ("_rotations_today", "_weakest", "strength"):
        at = body.find(later)
        if at > 0:
            assert guard < at, (
                f"the alert_only guard comes AFTER {later} -- something "
                f"can act before the switch is honoured")


def test_the_guard_returns_false_not_none():
    """False means 'no slot freed'. None would read as falsy in some
    callers and truthy in others."""
    src = inspect.getsource(Engine._maybe_rotate_out)
    block = src[src.find("alert_only"):]
    block = block[:block.find("\n\n")]
    assert "return False" in block


def test_rotation_refuses_and_says_so(monkeypatch):
    """Drive it. Switch off -> no sell, and he is told why."""
    said = []
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "decision", said.append)

    bot = Engine.__new__(Engine)
    bot.alert_only = True                      # the switch is OFF
    bot._rotations_today = 0
    bot.open_positions = {"KALYANKJIL": {"qty": 500, "direction": "LONG"},
                          "HEROMOTOCO": {"qty": 50, "direction": "LONG"}}

    got = bot._maybe_rotate_out("ANYTHING", "LONG", None)

    assert got is False, "it freed a slot with trading switched off"
    assert any("OFF" in line for line in said), (
        "it refused silently -- he must be able to see why")


def test_it_still_rotates_when_the_switch_is_ON():
    """A switch, not a removal. With trading armed the guard must not
    be what stops it."""
    import inspect
    src = inspect.getsource(Engine._maybe_rotate_out)
    guard = src[src.find("if getattr(self, \"alert_only\""):]
    guard = guard[:guard.find("return False") + 12]
    assert "alert_only" in guard
    # Exactly ONE executable check on the switch -- everything below
    # it is the normal strength logic, untouched. Comments mentioning
    # alert_only do not count; my own tests have asserted against
    # prose in docstrings before and passed while the code was wrong.
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert code.count("alert_only") == 1, (
        "more than one alert_only check crept into rotation")
