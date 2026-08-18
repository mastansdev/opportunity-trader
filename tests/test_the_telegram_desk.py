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
    start = src.find("from core.telegram_desk import")
    block = src[start:src.find("dashboard_state.refresh()", start)]
    assert "except Exception" in block, (
        "a failing chat integration can stop the bot starting")

# ---------------------------------------------------------------
# THE ALERT HAS TO REACH THE PHONE
# ---------------------------------------------------------------
#
#     "why i didn't get any alerts to buy stocks in telegram ?
#      i want to see the bot alerts me by stock name & reason to buy"
#                                 -- operator, 18 August 2026
#
# Both halves already worked. core/engine.py._manual_alert wrote 2,652
# buy alerts between 31 July and that morning -- TIINDIA, NEOGEN, PCBL
# and ACE were four of them, alerted at 09:44, 09:47, 09:48 and 10:18
# on the 18th -- and core/telegram_desk.send() had been delivering
# since the 17th. Nothing introduced them, so every alert reached a log
# file and a web page and no phone.
#
# These tests hold the join, in both directions: the Engine must go on
# working with nothing attached, and the message that arrives must be
# the message the board shows.

RANKED = {
    "symbol": "TIINDIA",
    "kind": "ranked-buy",
    "at": "09:44:23",
    "message": ("TIINDIA BUY 11 @ 2888.8 stop 2760.3 target 3145.8 -- "
                "up 5.4%, while Automobile is up 0.3%, 1.5x its normal "
                "volume - reported results 4 sessions ago"),
}


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone to Telegram. Nothing leaves."""
    out = []
    monkeypatch.setattr("core.telegram_desk._call",
                        lambda method, **kw: (out.append(kw) or {"ok": True}))
    return out


def test_the_stock_and_the_reason_both_arrive(desk, sent):
    assert desk.push(RANKED) is True
    text = sent[0]["text"]
    assert "TIINDIA" in text, "he asked to be alerted BY STOCK NAME"
    assert "1.5x its normal volume" in text, "and by REASON TO BUY"


def test_the_phone_says_exactly_what_the_board_says(desk, sent):
    """Not a paraphrase. A second copy of the sentence is how a
    dashboard and an alert start disagreeing about one trade."""
    desk.push(RANKED)
    assert RANKED["message"] in sent[0]["text"]


def test_it_carries_the_command_that_takes_the_trade(desk, sent):
    desk.push(RANKED)
    assert "BUY TIINDIA" in sent[0]["text"]
    assert "YES" in sent[0]["text"], "a command with no confirm step shown"


def test_a_position_alert_offers_SELL_not_BUY(desk, sent):
    desk.push({"symbol": "KAYNES", "kind": "TRAIL",
               "message": "KAYNES has fallen back to 3,410. NOT sold."})
    text = sent[0]["text"]
    assert "SELL KAYNES" in text
    assert "BUY KAYNES" not in text


def test_a_sizing_refusal_never_reaches_the_phone(desk, sent):
    """He asked what to BUY. A stream of near-misses buries that."""
    assert desk.push({"symbol": "X", "kind": "stop-too-wide",
                      "message": "the stop is too wide"}) is False
    assert sent == []


def test_an_unknown_kind_is_still_delivered(desk, sent):
    """A kind this file has not heard of is a gap in a lookup table,
    not a reason to drop an alert the Engine thought worth writing."""
    assert desk.push({"symbol": "SBIN", "kind": "brand-new",
                      "message": "something happened"}) is True


def test_the_daily_cap_stops_it_and_says_so(desk, sent):
    """311 alerts were written on 11 August. That volume on a phone
    trains him to swipe them away unread."""
    from core.telegram_desk import PUSH_MAX_PER_DAY
    for i in range(PUSH_MAX_PER_DAY + 5):
        desk.push(dict(RANKED, symbol=f"SYM{i}"))
    assert len(sent) == PUSH_MAX_PER_DAY + 1, (
        "the cap either leaked or went silent without saying so")
    assert "cap" in sent[-1]["text"].lower()


def test_push_never_raises_whatever_it_is_given(desk):
    for junk in (None, "", [], {}, {"symbol": None}, {"kind": 7},
                 {"symbol": "X", "kind": "ranked-buy", "message": None}):
        assert desk.push(junk) is False


def test_it_sends_nothing_when_no_phone_is_configured(desk, sent,
                                                      monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert desk.push(RANKED) is False
    assert sent == []


# ---------------------------------------------------------------
# THE ENGINE SIDE OF THE JOIN
# ---------------------------------------------------------------

def test_the_engine_forwards_every_note_it_writes():
    from core.engine import Engine
    got = []
    eng = Engine.__new__(Engine)
    eng.manual_alerts = []
    eng._manual_alerts_seen = set()
    eng.on_alert = got.append
    eng._manual_alert("TIINDIA", "ranked-buy", "TIINDIA BUY 11 @ 2888.8")
    assert len(got) == 1
    assert got[0]["symbol"] == "TIINDIA"
    assert got[0]["kind"] == "ranked-buy"
    assert "2888.8" in got[0]["message"]


def test_the_note_is_recorded_before_it_is_forwarded():
    """A phone that is off must cost him nothing he had before."""
    from core.engine import Engine
    eng = Engine.__new__(Engine)
    eng.manual_alerts = []
    eng._manual_alerts_seen = set()

    def _explode(note):
        raise RuntimeError("telegram timed out")

    eng.on_alert = _explode
    eng._manual_alert("SBIN", "ranked-buy", "SBIN BUY 40")
    assert len(eng.manual_alerts) == 1, (
        "a dead phone erased an alert that was already his")


def test_the_engine_runs_with_no_phone_at_all():
    from core.engine import Engine
    eng = Engine.__new__(Engine)
    eng.manual_alerts = []
    eng._manual_alerts_seen = set()
    eng.on_alert = None
    eng._manual_alert("SBIN", "ranked-buy", "SBIN BUY 40")
    assert len(eng.manual_alerts) == 1


def test_the_engine_never_imports_telegram():
    """The sink is assigned by main.py. core/engine.py must not know
    that a chat app exists."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    imports = [ln for ln in src.splitlines()
               if ln.lstrip().startswith(("import ", "from "))]
    assert not [ln for ln in imports if "telegram" in ln.lower()], (
        "core/engine.py imports the chat app it must not know about")


def test_main_actually_connects_the_two():
    """The line whose absence was the entire fault."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "engine.on_alert = telegram_desk.push" in src


def test_only_one_listener_so_nothing_is_sent_twice():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert src.count("engine.on_alert") == 1


# ---------------------------------------------------------------
# THE HELP TEXT MUST NOT ADVERTISE A COMMAND THAT DOES NOT EXIST
# ---------------------------------------------------------------

def test_every_command_in_the_help_text_is_handled(desk):
    """OPP was in _HELP from the first day and had no branch, so the
    bot answered "Unknown command" to its own instructions."""
    import re
    from core.telegram_desk import _HELP
    for verb in re.findall(r"`([A-Z]+)", _HELP):
        reply = desk.handle(verb, ME) or ""
        assert not reply.startswith("Unknown command"), (
            f"HELP advertises {verb} and handle() has no branch for it")

# ---------------------------------------------------------------
# IF IT IS NOT MTF, IT IS NOT BOUGHT
# ---------------------------------------------------------------
#
#     "BY SEEING THAT ALERT I'LL GIVE COMMAND BUY X SHARES IN MTF
#      (INCASE NON-MTF - NO BUY)"    -- operator, 18 August 2026
#
# trading/live_execution.py has always sent product_type=MTF, so the
# ORDER was never the problem: a cash-only scrip would be sent as a
# margin order and rejected at Dhan, or filled in a way he did not
# ask for. The question had to be asked BEFORE the quote, and the
# ranker was the only thing asking it.
#
# Three answers, not two. The third -- "could not be asked" -- is the
# one that matters, because reading it as a pass is the assumption he
# has told this project never to make.


class _State:
    """A board with a price and an MTF answer, both controllable."""

    def __init__(self, mtf=None, price=2888.8, snap=None):
        self._mtf = mtf
        self._price = price
        self._snap = snap if snap is not None else {
            "ranked": {"rows": [{"symbol": "TCS", "ltp": price,
                                 "why": "up 5.4% on 1.5x volume"}]},
        }

    def get_snapshot(self):
        return self._snap

    def _mtf_for(self, symbol, row=None):
        return self._mtf


def _desk_with(state, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", ME)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:token")
    ctl = _Ctl()
    d = TelegramDesk(controller=ctl, state=state, engine=_Engine(),
                     master_loader=_Loader())
    d.ctl = ctl
    return d


def test_a_cash_only_stock_is_refused_outright(monkeypatch):
    desk = _desk_with(_State(mtf={"eligible": False}), monkeypatch)
    reply = desk.handle("BUY TCS 10", ME)
    assert "NO BUY" in reply
    assert "cash only" in reply.lower()
    assert desk._pending is None, (
        "a refused BUY left something a stray YES could fire")


def test_a_yes_after_that_refusal_trades_nothing(monkeypatch):
    desk = _desk_with(_State(mtf={"eligible": False}), monkeypatch)
    desk.handle("BUY TCS 10", ME)
    desk.handle("YES", ME)
    assert desk.ctl.calls == []


def test_an_mtf_stock_is_quoted_and_says_the_leverage(monkeypatch):
    desk = _desk_with(_State(mtf={"eligible": True, "leverage": 4.0}),
                      monkeypatch)
    reply = desk.handle("BUY TCS 10", ME)
    assert "MTF 4.0x" in reply
    assert "YES" in reply
    desk.handle("YES", ME)
    assert desk.ctl.calls == [("BUY", "TCS", 10)]


def test_an_unasked_mtf_question_is_never_reported_as_a_pass(monkeypatch):
    """NEVER ASSUME. With no broker attached the answer is unknown,
    and the quote has to say unknown -- not stay silent, which reads
    as eligible."""
    desk = _desk_with(_State(mtf=None), monkeypatch)
    reply = desk.handle("BUY TCS 10", ME)
    assert "not checked" in reply.lower()
    assert "MTF 4" not in reply
    assert "eligible" not in reply.lower().replace("not checked", "")


def test_no_price_yet_is_also_not_a_pass(monkeypatch):
    desk = _desk_with(_State(mtf={"eligible": True, "leverage": 4.0},
                             snap={"ranked": {"rows": []}}), monkeypatch)
    reply = desk.handle("BUY TCS 10", ME)
    assert "not checked" in reply.lower()


def test_selling_is_never_blocked_by_the_mtf_rule(monkeypatch):
    """The rule is about what he BUYS. A gate that can stop him
    closing a position is a gate that can trap him in one."""
    desk = _desk_with(_State(mtf={"eligible": False}), monkeypatch)
    reply = desk.handle("SELL TCS", ME)
    assert "NO BUY" not in reply
    desk.handle("YES", ME)
    assert desk.ctl.calls == [("SELL", "TCS", None)]


def test_exitall_is_never_blocked_by_it_either(monkeypatch):
    desk = _desk_with(_State(mtf={"eligible": False}), monkeypatch)
    desk.handle("EXITALL", ME)
    desk.handle("YES", ME)
    assert desk.ctl.calls == [("EXITALL", None, None)]


def test_this_file_keeps_no_list_of_mtf_stocks():
    """Dhan decides which scrips are marginable and changes it. A copy
    here would go stale silently, which is the worst way to be wrong
    about whether an order can be placed."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "mtf_for" in code, "it must ASK, and it currently does not"


# ---------------------------------------------------------------
# THE REST OF THE CONTROL HE ASKED FOR
# ---------------------------------------------------------------
#
#     "give me complete control through telegram"
#
# Read-only, all three. Nothing here can move money.

def test_top_lists_what_the_bot_likes_now(monkeypatch):
    desk = _desk_with(_State(), monkeypatch)
    reply = desk.handle("TOP", ME)
    assert "TCS" in reply
    assert "1.5x volume" in reply, "a pick with no reason is not a pick"


def test_alerts_replays_everything_raised_today(monkeypatch):
    """The daily push cap limits what is SENT, never what he can ask
    for -- otherwise the cap would hide alerts instead of pacing them."""
    state = _State(snap={"alerts": [
        {"at": "09:44:23", "symbol": "TIINDIA",
         "message": "TIINDIA BUY 11 @ 2888.8 -- 1.5x normal volume"}]})
    desk = _desk_with(state, monkeypatch)
    reply = desk.handle("ALERTS", ME)
    assert "TIINDIA" in reply and "09:44:23" in reply


def test_funds_reports_the_same_numbers_the_sizing_uses(monkeypatch):
    state = _State(snap={"capital": {"available_buying_power": 120000,
                                     "deployed_capital": 30000,
                                     "used_margin": 7500,
                                     "realized_pnl": 2982}})
    desk = _desk_with(state, monkeypatch)
    reply = desk.handle("FUNDS", ME)
    assert "120,000" in reply and "2,982" in reply


def test_the_read_only_commands_cannot_trade(monkeypatch):
    desk = _desk_with(_State(), monkeypatch)
    for verb in ("TOP", "ALERTS", "FUNDS", "STATUS", "POSITIONS", "PNL",
                 "OPP"):
        desk.handle(verb, ME)
    assert desk.ctl.calls == []


def test_they_all_survive_a_board_that_is_not_there(desk):
    """state=None is the real case before the dashboard has built its
    first snapshot, and a crash there would kill the poll thread."""
    for verb in ("TOP", "ALERTS", "FUNDS"):
        assert desk.handle(verb, ME)
