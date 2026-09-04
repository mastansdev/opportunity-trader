"""A log line that describes code that no longer exists is worse than
no log line at all.

    "fix those lying log messages"        -- the operator, 4 Sep 2026

Two of them had been wrong for weeks, and both were wrong in the
direction that would make him act:

[SLOW] said "Entries read this snapshot, so they are deciding on
prices that old". Untrue since core/auto_entry.price_now() landed on
2 September -- the order price, the liveness check and (from 4 Sep)
the stop and the size are all rebuilt off the tick. Believing it, the
fix for a slow board looks like an entry-price problem. It is not:
what a slow rebuild delays is a stock APPEARING AT ALL, which on
4 September cost Rs 77,779 across nine trades that were found late,
not priced late. The wrong sentence hid the real cost.

CIRCUIT PROXIMITY EXIT said "irrespective of direction". Untrue since
29 July 2026, when CIRCUIT_RULE_DIRECTION_AWARE made the rule leave a
LONG walking into its UPPER circuit alone -- a stock with no sellers
left is the day's best position, not a trapped one. On 4 September TBZ
was locked at its upper circuit and he asked about it. A reader who
believed that line would have concluded the bot was about to sell it.

These assert the messages against the BEHAVIOUR, not against a
wording, so a future rewrite is free as long as it stays true. Each
one reads the method that EMITS the line, by name, so a rename fails
here loudly rather than quietly searching a whole module and matching
some comment that happens to contain the same words.
"""

import inspect

from core import engine as engine_mod
from core.trailing_stop import LONG


def _source(obj):
    return inspect.getsource(obj)


def _engine_with_flag(side):
    """A bare Engine with only the circuit monitor it needs. __init__
    opens files and sockets; this test is about one method."""
    class _Monitor:
        def get_flag(self, _symbol):
            return {"side": side, "gap_pct": 0.01} if side else {}
    engine = object.__new__(engine_mod.Engine)
    engine.circuit_monitor = _Monitor()
    return engine


# ------------------------------------------------------------ [SLOW]

def _slow_message():
    from dashboard.state import DashboardState
    body = _source(DashboardState._report_slow_panels)
    return body[body.index("[SLOW]"):]


def test_the_slow_board_warning_does_not_blame_entry_prices():
    """Entries have re-read the tick since 2 September."""
    assert "Entries read this" not in _slow_message(), (
        "[SLOW] still claims entries read the board snapshot -- they "
        "have read the tick since core/auto_entry.price_now()")


def test_the_slow_board_warning_names_the_delay_that_is_real():
    assert "APPEARING" in _slow_message(), (
        "[SLOW] no longer says what a slow rebuild actually costs: a "
        "stock cannot be bought until a rebuild puts it on the board")


# -------------------------------------------------- circuit proximity

def _circuit_message():
    body = _source(engine_mod.Engine._check_circuit_proximity)
    return body[body.index("CIRCUIT PROXIMITY EXIT"):][:400]


def test_a_long_at_its_upper_circuit_is_left_alone():
    """THE behaviour the message has to describe. A stock with no
    sellers left is not trapped -- this is TBZ on 4 September."""
    assert _engine_with_flag("UPPER")._circuit_blocks("TBZ", LONG) is False


def test_a_long_at_its_lower_circuit_is_closed():
    """The case the rule exists for: if it locks there is no buyer
    left to sell into."""
    assert _engine_with_flag("LOWER")._circuit_blocks("ANY", LONG) is True


def test_an_unreadable_flag_still_closes_the_position():
    """Fails CLOSED. An unreadable side is not evidence that the
    approach is in our favour."""
    assert _engine_with_flag(None)._circuit_blocks("ANY", LONG) is True


def test_the_circuit_exit_no_longer_claims_to_ignore_direction():
    assert "irrespective of direction" not in _circuit_message(), (
        "the exit still tells him it closes regardless of direction, "
        "which has been false since CIRCUIT_RULE_DIRECTION_AWARE")


def test_the_circuit_exit_says_which_side_is_against_the_position():
    chunk = _circuit_message()
    assert "against" in chunk and "{side}" in chunk, (
        "the exit should name the side it is closing ahead of, so the "
        "line can be checked against the position it closed")
