"""
==========================================================
His positions at Dhan are his. The bot watches them.
==========================================================

    "corona, deepakfert, deepakntr, sbin, solarinds are my long
     positions in dhan"          -- operator, 17 August 2026

Said in passing, and it exposed the worst thing in the book.

Those first three are in data/trade_memory.db as CLOSED trades --
TRAILING_STOP exits on 5 and 6 August, losses written down:

    CORONA      2266.24 -> 2096.70  q=100  -16,954   x2
    DEEPAKNTR   1799.94 -> 1736.70  q=100   -6,324   x2
    DEEPAKFERT  1675.00 -> 1594.40  q=50    -4,030   x2

HE STILL HOLDS THEM. ALERT_ONLY_MODE was on, so no order was ever
sent. The bot decided to exit, wrote the loss into its permanent
memory, and nothing happened at Dhan. Each was recorded twice --
re-adopted once per process start -- double-counting Rs 27,309 and
making the adopted book read 64% worse than it was.

SBIN and SOLARINDS have no row at all. It does not know he holds them.

HOW IT GOT THERE
----------------
5 Aug: "my goal is to stop manual trading & let the bot trade. do not
       ask me how? thats your job"      -> adopt_with_stops=True
6 Aug: "i told you too not track my old positions. only fresh from
       tomorrow"                        -> skip_symbols=_pre_existing

The intent reversed in a day. The flag stayed on and only ever guarded
what was open at STARTUP, so anything opened during a session was
still taken. core/broker_sync.py later grew an alert_only guard, after
adoption "armed a trailing stop on each, and sold all three out from
under him" -- real, and not enough, because it is tied to the switch.
Arm the bot and adoption resumes.

Asked directly on 17 August he chose: WATCH ONLY, never manage or
exit. These tests hold that, independently of the switch.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_dashboard_does_not_adopt_with_stops():
    """THE ONE THAT MATTERS. It was the only place in the repo that
    turned adoption on -- broker_sync's own default is False."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert "adopt_with_stops=False" in src, (
        "the dashboard is adopting his Dhan positions into the trading "
        "book again. Arm the bot and it will place real sell orders on "
        "positions he opened by hand.")
    assert "adopt_with_stops=True" not in src


def test_nothing_else_in_the_repo_turns_adoption_on():
    """A second caller would reintroduce it quietly."""
    on = []
    for folder in ("core", "dashboard", "tools"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            if "adopt_with_stops=True" in path.read_text(
                    encoding="utf-8", errors="replace"):
                on.append(path.relative_to(ROOT).as_posix())
    assert not on, f"adoption is switched on in: {on}"


def test_broker_syncs_own_default_is_still_off():
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    assert "adopt_with_stops=False" in src, (
        "BrokerSync's default changed -- every caller now adopts unless "
        "it says otherwise, which is the wrong way round for real money")


def test_the_alert_only_guard_is_still_there_as_well():
    """Belt and braces. The switch guard is not sufficient on its own,
    but removing it would be a second way back in."""
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    assert "alert_only" in src
    assert "_off and self.adopt_with_stops" in src


def test_he_is_still_told_when_a_position_has_no_stop():
    """WATCH ONLY is not BLIND. The 'no stop at Dhan' warning caught a
    real gap on 13 August and must survive the change."""
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    assert "unprotected" in src.lower() or "not protected" in src.lower()
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    assert "NO STOP AT DHAN" in page


def test_the_phantom_closes_are_left_in_the_record():
    """They are history and they stay. Deleting his trade record to
    make a number look better is not a fix -- the guard added in
    core/trade_memory.py stops NEW ones."""
    import sqlite3
    con = sqlite3.connect("file:data/trade_memory.db?mode=ro", uri=True)
    n = con.execute(
        "SELECT COUNT(*) FROM trade_memory "
        "WHERE entry_reason = 'ADOPTED_FROM_BROKER'").fetchone()[0]
    con.close()
    assert n > 0, (
        "the adopted rows were deleted. They are evidence of what "
        "happened and the fix is to stop making new ones.")
