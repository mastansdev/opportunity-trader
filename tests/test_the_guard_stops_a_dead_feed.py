"""
==========================================================
The checklist is not only a door
==========================================================

    "so if the collector dies at 11 o'clock while the bot is already
     trading, the bot keeps going ... yes build that"
                                -- operator, 7 August 2026

/api/bot_trading/on refuses to arm while a morning input is missing.
It checked ONCE and never looked again, so a collector that died at
11:00 left the bot buying at 11:30 on news that stopped arriving half
an hour earlier.

These drive core/morning_ready.LiveGuard directly -- a real object, a
real sqlite store whose newest message the test controls, and a real
disarm callback whose effect is asserted. Not source text.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import pytest

from core.morning_ready import STRIKES_TO_DISARM, LiveGuard

NOW = datetime(2026, 8, 7, 11, 0)


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("create table messages "
                "(at text, seen_at text, ocr_text text, symbols text)")
    con.commit()
    con.close()
    yield path
    os.unlink(path)


def last_message(path, when):
    con = sqlite3.connect(path)
    con.execute("delete from messages")
    con.execute("insert into messages values (?,?,'','')",
                (when.isoformat(), when.isoformat()))
    con.commit()
    con.close()


class _Bot:
    def __init__(self):
        self.armed = True

    def disarm(self):
        self.armed = False


def test_a_live_feed_is_left_alone(store):
    last_message(store, NOW - timedelta(minutes=2))
    bot = _Bot()
    guard = LiveGuard(disarm=bot.disarm)
    got = guard.poll(now=NOW, telegram_db=store)
    assert got["ok"] is True
    assert bot.armed is True, "it disarmed a healthy bot"


def test_one_quiet_check_does_not_disarm(store):
    """The channels go quiet. A pause is not a failure."""
    last_message(store, NOW - timedelta(minutes=45))
    bot = _Bot()
    guard = LiveGuard(disarm=bot.disarm)
    guard.poll(now=NOW, telegram_db=store)
    assert bot.armed is True, (
        "it disarmed on the first quiet check -- too twitchy")


def test_a_dead_feed_disarms_it_after_the_strikes(store):
    last_message(store, NOW - timedelta(minutes=45))
    bot = _Bot()
    guard = LiveGuard(disarm=bot.disarm)
    for _ in range(STRIKES_TO_DISARM):
        guard.poll(now=NOW, telegram_db=store)
    assert bot.armed is False, (
        f"still armed after {STRIKES_TO_DISARM} dead checks")


def test_a_recovery_resets_the_count(store):
    """A blip must not accumulate towards a disarm an hour later."""
    bot = _Bot()
    guard = LiveGuard(disarm=bot.disarm)
    last_message(store, NOW - timedelta(minutes=45))
    guard.poll(now=NOW, telegram_db=store)
    guard.poll(now=NOW, telegram_db=store)
    assert guard.strikes == 2
    last_message(store, NOW - timedelta(minutes=1))
    guard.poll(now=NOW, telegram_db=store)
    assert guard.strikes == 0, "a recovery did not clear the strikes"
    assert bot.armed is True


def test_it_does_nothing_when_the_bot_is_not_armed(store):
    """Nothing to protect, and the count must not carry over."""
    last_message(store, NOW - timedelta(hours=9))
    guard = LiveGuard(disarm=lambda: pytest.fail("disarmed a bot that "
                                                 "was not trading"))
    got = guard.poll(now=NOW, armed=False, telegram_db=store)
    assert got["acted"] is False
    assert guard.strikes == 0


def test_a_broken_disarm_never_takes_the_loop_down(store):
    """It runs on the trading loop. It may not raise."""
    last_message(store, NOW - timedelta(minutes=45))
    said = []
    guard = LiveGuard(disarm=lambda: 1 / 0, say=said.append)
    for _ in range(STRIKES_TO_DISARM):
        guard.poll(now=NOW, telegram_db=store)
    assert any("COULD NOT DISARM" in line for line in said), (
        "it failed silently -- he would never know")


def test_a_missing_store_never_takes_the_loop_down(tmp_path):
    # Not under data/: sqlite3.connect() creates the file it is given,
    # and this left an empty data/does-not-exist.db behind on every run.
    guard = LiveGuard(disarm=lambda: None)
    got = guard.poll(now=NOW, telegram_db=str(tmp_path / "no-such-store.db"))
    assert got["acted"] is False


def test_main_creates_the_guard_before_it_polls_it():
    """The ranker sat unwired through 3,541 green tests. Not again."""
    src = open("main.py", encoding="utf-8").read()
    created = src.find("_live_guard = _LiveGuard")
    used = src.find("_live_guard.poll")
    assert created > 0, "main.py never builds the guard"
    assert used > created, "main.py polls the guard before creating it"


def test_disarming_stops_new_entries_and_nothing_else():
    """It must never close what he is holding."""
    src = open("main.py", encoding="utf-8").read()
    block = src[src.find("def _disarm_for_dead_feed"):]
    block = block[:block.find("_live_guard =")]
    assert "alert_only = True" in block
    for forbidden in ("close", "exit", "sell", "square"):
        assert forbidden not in block.lower(), (
            f"the disarm touches positions: found '{forbidden}'")
