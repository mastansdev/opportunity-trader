"""
==========================================================
A second front door, not a second order path
==========================================================

    "our bot needs telegram command center with alerting user about the
     opportunities & commands to buy,sell,exitall options & everything
     thats matter for user"      -- operator, 17 August 2026

He chose FULL CONTROL WITH A CONFIRM STEP when asked directly.

That is a trade-execution path over a chat app, so the tests below are
mostly about what must NOT happen. Three things could go badly:

  1. A Telegram bot is discoverable by handle -- a stranger can message
     it. Every command from any chat but his is refused, and REPORTED
     rather than silently dropped, so an attempt is visible.

  2. A fat finger on a phone. BUY / SELL / EXITALL are quoted back and
     wait for YES. The pending command expires by itself after 60s: a
     YES typed into a stale conversation must never fire an order.

  3. A second order path drifting from the first. Every command ends at
     trading/trade_controller.py -- the same object dashboard/server.py
     calls. Nothing in core/telegram_desk.py builds an order or speaks
     to Dhan, so ALERT_ONLY_MODE and every gate still apply because the
     decision is still made where it always was.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import time

import pytest

from core.telegram_desk import CONFIRM_SECONDS, TelegramDesk

ROOT = pathlib.Path(__file__).resolve().parents[1]
ME = "787902453"
STRANGER = "999999999"


class _Ctl:
    def __init__(self):
        self.calls = []

    def request_buy(self, symbol, qty=None):
        self.calls.append(("BUY", symbol, qty))

    def request_exit(self, symbol, qty=None):
        self.calls.append(("SELL", symbol, qty))

    def request_exit_all(self):
        self.calls.append(("EXITALL", None, None))

    def note_action(self, ok, text):
        pass


class _Engine:
    alert_only = True


class _Loader:
    def all_symbols(self, include_blocked=False):
        return ["TCS", "RELIANCE"]


@pytest.fixture
def desk(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", ME)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:token")
    ctl = _Ctl()
    d = TelegramDesk(controller=ctl, engine=_Engine(), master_loader=_Loader())
    d.ctl = ctl
    return d


# ---------------------------------------------------------------
# 1. ONLY HIM
# ---------------------------------------------------------------

@pytest.mark.parametrize("command", ["EXITALL", "BUY TCS", "SELL TCS", "ON"])
def test_a_stranger_can_command_nothing(desk, command):
    """THE ONE THAT MATTERS MOST. The handle is discoverable."""
    assert desk.handle(command, STRANGER) is None
    assert desk.ctl.calls == [], "a stranger reached the order path"


def test_a_stranger_cannot_confirm_his_pending_command(desk):
    """The nastiest shape: he quotes a BUY, someone else says YES."""
    desk.handle("BUY TCS", ME)
    assert desk.handle("YES", STRANGER) is None
    assert desk.ctl.calls == []
    assert desk.handle("YES", ME) is not None      # still his to confirm
    assert desk.ctl.calls == [("BUY", "TCS", None)]


# ---------------------------------------------------------------
# 2. THE CONFIRM STEP
# ---------------------------------------------------------------

@pytest.mark.parametrize("command", ["BUY TCS", "SELL TCS", "EXITALL"])
def test_nothing_fires_without_a_yes(desk, command):
    reply = desk.handle(command, ME)
    assert "YES" in reply
    assert desk.ctl.calls == [], f"{command} placed an order unconfirmed"


def test_yes_fires_exactly_once(desk):
    desk.handle("BUY TCS 10", ME)
    assert desk.handle("YES", ME) is not None
    assert desk.ctl.calls == [("BUY", "TCS", 10)]
    assert desk.handle("YES", ME) == "Nothing to confirm."
    assert len(desk.ctl.calls) == 1, "a second YES repeated the order"


def test_a_stale_yes_never_trades(desk):
    """A confirmation is only meaningful while he still remembers what
    he asked for. Typed into yesterday's chat it must do nothing."""
    desk.handle("EXITALL", ME)
    with desk._lock:
        verb, sym, qty, _ = desk._pending
        desk._pending = (verb, sym, qty, time.time() - 1)
    reply = desk.handle("YES", ME)
    assert "expired" in reply.lower()
    assert desk.ctl.calls == []


def test_no_cancels_it(desk):
    desk.handle("EXITALL", ME)
    assert desk.handle("NO", ME) == "Cancelled."
    assert desk.ctl.calls == []


def test_the_quote_names_the_switch_that_actually_decides(desk,
                                                          monkeypatch):
    """---- THE FIRST VERSION OF THIS PROMPT WAS WRONG. ----

    It said "ALERT ONLY is ON -- this will be recorded, not sent to
    Dhan". ALERT_ONLY_MODE does not do that. It governs THE BOT'S OWN
    entries -- checked in core/engine.py's breakout path and NOT in
    the manual path, so a BUY he asks for goes through whether the bot
    is armed or not. That is deliberate: it is his trade.

    What decides whether an order reaches Dhan is TRADING_MODE, read
    by trading/execution.py. With TRADING_MODE=LIVE and
    ALERT_ONLY_MODE=True the old message would have said "not sent to
    Dhan" WHILE PLACING A REAL ORDER.

    A confirmation prompt that is wrong about safety is worse than no
    prompt.
    """
    import config

    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    paper = desk.handle("BUY TCS", ME)
    assert "PAPER" in paper and "does not reach Dhan" in paper

    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    live = desk.handle("BUY TCS", ME)
    assert "REAL order" in live, "a LIVE order was not announced as real"
    assert "cannot be cancelled" in live


def test_the_quote_never_claims_safety_it_cannot_deliver(desk,
                                                         monkeypatch):
    """The exact regression: LIVE mode with the bot disarmed must not
    read as safe."""
    import config

    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    desk.engine.alert_only = True          # bot OFF, order still real
    reply = desk.handle("BUY TCS", ME)
    assert "does not reach Dhan" not in reply, (
        "the prompt promises the order stays local while TRADING_MODE "
        "is LIVE -- this is the bug that made it worse than no prompt")


def test_an_unreadable_mode_assumes_the_dangerous_answer(desk,
                                                         monkeypatch):
    """If it cannot tell, it must not say 'safe'."""
    import core.telegram_desk as td

    monkeypatch.setattr(
        td.TelegramDesk, "_reach",
        staticmethod(lambda: "Could not read TRADING_MODE -- "
                             "assume this is REAL until checked"))
    assert "REAL" in desk.handle("BUY TCS", ME)


def test_an_unknown_symbol_is_never_quoted(desk):
    reply = desk.handle("BUY NOTAREALSTOCK", ME)
    assert "not in the tradeable universe" in reply
    assert desk._pending is None, "a typo was left pending a YES"


def test_a_bad_quantity_is_refused(desk):
    assert "not a quantity" in desk.handle("BUY TCS abc", ME)
    assert desk._pending is None


# ---------------------------------------------------------------
# 3. ONE ORDER PATH
# ---------------------------------------------------------------

def test_it_never_talks_to_dhan_itself():
    """THE LINE THAT MUST NOT MOVE. A chat app that built its own
    orders would be a second set of rules to keep in step, and they
    would drift."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    for banned in ("dhanhq", "place_order", "DhanContext", "order_type"):
        assert banned not in src, (
            f"core/telegram_desk.py references {banned} -- it must go "
            f"through trade_controller like every other caller")


def test_it_uses_the_same_controller_methods_as_the_dashboard():
    desk_src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    server_src = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    for method in ("request_buy(", "request_exit(", "request_exit_all("):
        assert method in desk_src and method in server_src, (
            f"{method} is not shared between the phone and the screen")


def test_the_handler_never_raises(desk):
    """It is the least important thing in the process and must not be
    able to stop the trading loop."""
    for junk in (None, "", "   ", "BUY", "WHY", "\n", "/" * 200,
                 "BUY " + "X" * 500, "\u0000"):
        desk.handle(junk, ME)          # must not raise


def test_it_stays_quiet_when_not_configured(monkeypatch):
    from core.telegram_desk import available
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert available() is False
    assert TelegramDesk().start() is False


def test_the_token_is_never_logged():
    """A traceback or a diagnostic carrying the token would put it in
    logs/ -- 976 files, none of them encrypted."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if ("diagnostic(" in line or "warn(" in line or "decision(" in line):
            assert "token" not in line.lower() or "TELEGRAM_BOT_TOKEN" in line, line


def test_main_starts_it_and_survives_it_failing():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "TelegramDesk(" in src
    block = src[src.find("from core.telegram_desk import"):]
    assert "except Exception" in block[:900], (
        "a failing chat integration can stop the bot starting")
