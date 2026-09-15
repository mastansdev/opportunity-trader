"""
==========================================================
Alert me about the opportunity, but do not buy
==========================================================

    "No daily loss in both modes. its wantedly switched OFF; i need to
     some mechanism like OFF the new entries completely once my profit
     or loss or any work & i need to move away from system. so that bot
     can alert me about the opportunity but no buy. like in telegram"
                                    -- the operator, 14 September 2026

TWO THINGS, and they are deliberately separate.

THE DAILY CAP IS OFF ON BOTH SIDES. It used to apply to real money and
not to paper, which is the dual setting he abolished the same day. He
has said which way it resolves: off for both. The brake is HIS now.

AND HE GETS A BRAKE TO HOLD. PAUSE stops NEW positions being opened.
It is NOT the switch and NOT a mode:

    the switch   ON / OFF      whose money -- real or paper
    the pause    PAUSE/RESUME  may a NEW position be opened

Neither reads the other. That separation is the whole point: loading a
second meaning onto OFF is exactly what produced the third state he
abolished on 31 August, after 65 alerts and 0 trades.

WHAT KEEPS RUNNING while paused: every open position. Stops, trails,
the profit lock, BUYING_DRIED_UP, the drift exit, the circuit guard.
Walking away from an open book is not abandoning it.

WHAT HE STILL HEARS: the opportunities. A pick refused by the pause
alerts him with the stock and the reason -- the same treatment a full
book gets, because both are refusals about the SESSION rather than
about the stock, and those are the ones he can act on himself.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.auto_entry import refuse_reason

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Engine:
    def __init__(self, paused=False, positions=None):
        self.entries_paused = paused
        self.open_positions = dict(positions or {})


def _row(**kw):
    row = {"symbol": "ABC", "action": "BUY", "state": "live",
           "plan": {"ok": True, "qty": 10, "stop": 90.0}}
    row.update(kw)
    return row


# ---------------------------------------------------------------
# THE PAUSE
# ---------------------------------------------------------------

def test_a_paused_bot_buys_nothing():
    why = refuse_reason(_row(), _Engine(paused=True), held=set())
    assert why and "PAUSED" in why


def test_an_unpaused_bot_still_buys():
    """The control. A pause that never lifts is just a stopped bot."""
    assert refuse_reason(_row(), _Engine(paused=False), held=set()) is None


def test_an_engine_that_never_heard_of_it_still_trades():
    """Older engines, and every test harness that builds a bare one."""
    class _Bare:
        pass
    assert refuse_reason(_row(), _Bare(), held=set()) is None


def test_the_refusal_says_it_passed_everything_else():
    """So he can tell 'I stopped this' from 'the bot did not want it'."""
    why = refuse_reason(_row(), _Engine(paused=True), held=set())
    assert "passed every other gate" in why
    assert "you stopped them" in why


def test_it_is_asked_before_the_stock_is_judged():
    """The reason he is shown must name the pause, not whichever gate
    the stock would have met next."""
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    body = src[src.index("def refuse_reason"):]
    assert body.index("entries_paused") < body.index('row.get("state") == "fading"')


# ---------------------------------------------------------------
# AND HE IS STILL TOLD
# ---------------------------------------------------------------

def test_a_paused_refusal_is_alerted_like_a_full_book():
    """'alert me about the opportunity but no buy'. Both are refusals
    about the SESSION, not about the stock."""
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    block = src[src.index("lost_a_seat = ("):]
    block = block[:block.index("\n", block.index("already holding"))]
    assert '"PAUSED" in why' in block


# ---------------------------------------------------------------
# IT IS NOT THE SWITCH
# ---------------------------------------------------------------

def test_the_pause_never_reads_the_switch():
    """Two controls, two questions. Neither may answer for the other."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    body = src[src.index("def _pause(self, paused):"):]
    body = body[:body.index("# ---------------- the poll loop")]
    for forbidden in ("apply_switch", "TRADING_MODE", "execution.live"):
        assert forbidden not in body


def test_the_switch_never_touches_the_pause():
    src = (ROOT / "core" / "trading_gate.py").read_text(encoding="utf-8")
    assert "entries_paused" not in src


def test_telegram_has_both_words_and_says_what_each_does():
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    assert '"PAUSE", "HOLD", "STOP"' in src
    assert '"RESUME", "GO", "CONTINUE", "UNPAUSE"' in src
    # The help text used to claim ON/OFF "arm or disarm new entries",
    # which is what PAUSE does. ON/OFF is whose money.
    assert "whose money" in src
    assert "arm or disarm new entries" not in src


def test_there_is_one_pause_and_the_buying_lane_reads_it():
    """15 Sep 2026: the dashboard said "new entries PAUSED" and the
    ranked lane -- the one that buys -- never read that flag. Now
    Engine.entries_paused is a view of trade_controller's flag, so the
    dashboard button and Telegram PAUSE are the same switch.

    It survives a restart (main.py restore_pause_state, 25 July: a crash
    must never silently resume buying); preflight names the file."""
    from core.engine import Engine
    engine = Engine()
    engine.trade_controller._write_pause_flag = lambda paused: None
    assert engine.entries_paused is False
    engine.trade_controller.request_pause_new_entries()   # dashboard
    assert engine.entries_paused is True
    engine.entries_paused = False                         # Telegram RESUME
    assert engine.trade_controller.is_new_entries_paused() is False
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    assert "self.entries_paused = False" not in src


# ---------------------------------------------------------------
# THE DAILY CAP, OFF ON BOTH SIDES
# ---------------------------------------------------------------

def test_the_cap_is_off_whichever_way_the_switch_is_set():
    from core.engine import _daily_cap_applies

    class _Live:
        live = True
        _live = object()
    assert _daily_cap_applies(_Live()) is False
    assert _daily_cap_applies(None) is False


def test_it_can_be_put_back_on_both_sides_at_once(monkeypatch):
    from core.engine import _daily_cap_applies
    monkeypatch.setattr("config.DAILY_LOSS_CAP_ENABLED", True)

    class _Live:
        live = True
        _live = object()
    assert _daily_cap_applies(_Live()) is True
    assert _daily_cap_applies(None) is True


def test_there_is_no_way_to_have_it_on_one_side_only():
    """The dual setting is gone, not renamed."""
    import config
    assert not hasattr(config, "DAILY_LOSS_CAP_APPLIES_IN_PAPER")
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.index("def _daily_cap_applies"):]
    body = body[:body.index("\ndef ", 10)]
    assert "_switch_is_live" not in body
