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


# ---- THE GUARD MOVED, THE LESSON DID NOT. 5 September 2026. ----
#
# These read core/engine._maybe_rotate_out() for an alert_only check.
# That flag was retired on 5 September with the collapse to two -- and
# removing it reopened this exact bug for about an hour, caught by
# this file, which is the reason it exists.
#
# The replacement names the condition the old flag only approximated.
# On a SELL, trading/execution._route() asks _who_opened(): a position
# opened for real sells for real. So the dangerous combination is
#
#     the holder was opened for real   -> its sell would be REAL
#     the switch is now OFF            -> the buy would be PAPER
#
# which is the one-legged trade of 7 August. Rotation refuses exactly
# that, and refuses on any state it cannot establish.


def _bot(opened, live_now):
    """An Engine with only what _maybe_rotate_out() reaches for."""
    class _Execution:
        live = live_now

        def _who_opened(self, _symbol):
            return opened

    class _Monitor:
        """Enough of a snapshot for _symbol_strength() to answer. The
        guard sits after the strength maths -- before any order, but
        after the reads -- so the double has to get that far."""

        def get_snapshot(self):
            return {"KALYANKJIL": {"last_price": 100.0, "volume": 1,
                                   "ohlc": {"close": 99.0}},
                    "HEROMOTOCO": {"last_price": 100.0, "volume": 1,
                                   "ohlc": {"close": 99.0}},
                    "ANYTHING": {"last_price": 200.0, "volume": 1,
                                 "ohlc": {"close": 100.0}}}

    bot = Engine.__new__(Engine)
    bot.execution = _Execution()
    bot.circuit_monitor = _Monitor()
    bot._trend_cache = None
    bot._rotations_today = 0
    bot._rotation_cap_logged = False
    bot.open_positions = {"KALYANKJIL": {"qty": 500, "direction": "LONG"},
                          "HEROMOTOCO": {"qty": 50, "direction": "LONG"}}

    # The strength maths runs before the guard and needs a working
    # snapshot, a confirmation count and a weakest-holder pick. Doubled
    # so this test is about ONE thing: whether a real position can be
    # sold while the switch is off.
    bot._symbol_strength = lambda sym, d: 1.0 if sym == "ANYTHING" else 0.0
    bot._confirmation_count = lambda sym: 0
    bot._weakest_holder_for_rotation = lambda: ("KALYANKJIL", 0.0)
    return bot


def test_a_real_position_is_not_sold_while_the_switch_is_off(monkeypatch):
    """THE 7 August bug: five live SELLs and zero BUYs that morning."""
    said = []
    import core.engine as engine_module
    monkeypatch.setattr(engine_module, "decision", said.append)

    got = _bot(opened="live", live_now=False)._maybe_rotate_out(
        "ANYTHING", "LONG", None)

    assert got is False, "it freed a slot by selling a real position"
    assert any("OFF" in line for line in said), (
        "it refused silently -- he must be able to see why")


def test_a_paper_position_is_not_blocked_by_this_guard():
    """Both legs would be paper, so nothing is one-legged. Refusing
    here would stop rotation being TESTED on paper at all, which is
    what he asked to do on 5 September."""
    import inspect
    src = inspect.getsource(Engine._maybe_rotate_out)
    guard = src[src.index("BOTH LEGS OR NEITHER"):]
    guard = guard[:guard.index("return False") + 12]
    assert 'opened != "paper"' in guard, (
        "the guard no longer distinguishes a paper position, so paper "
        "rotation can never be tested")


def test_the_guard_comes_before_anything_can_reach_an_order():
    import inspect
    src = inspect.getsource(Engine._maybe_rotate_out)
    body = src[src.find('"""', src.find('"""') + 3):]
    guard = body.find("BOTH LEGS OR NEITHER")
    assert guard > 0, "the one-legged-trade guard is gone -- 7 August"
    for later in ("_bot_may_close", "self._exit("):
        at = body.find(later)
        if at > 0:
            assert guard < at, (
                f"the guard comes AFTER {later} -- an order can leave "
                f"before the check runs")


def test_an_unknowable_state_refuses():
    """Fails closed: if it cannot establish who opened the position,
    it does not rotate."""
    class _Broken:
        live = False

        def _who_opened(self, _symbol):
            raise RuntimeError("no record")

    bot = _bot(opened="live", live_now=False)
    bot.execution = _Broken()
    assert bot._maybe_rotate_out("ANYTHING", "LONG", None) is False
