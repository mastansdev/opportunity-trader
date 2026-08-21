"""
==========================================================
Armed in PAPER. The dashboard said "placing REAL orders".
==========================================================

    21 August 2026, 07:51. He armed the ranked lane from the
    dashboard, in PAPER, and the board answered:

        {"on": true, "note": "placing REAL orders"}

Nothing real was leaving the machine. TRADING_MODE was PAPER and
every fill was simulated. The note was hardcoded to the SWITCH and
never read the MODE:

        "note": ("placing REAL orders" if not alert_only else ...)

THIS IS THE NILKAMAL FAULT POINTING THE OTHER WAY

On 19 August a PAPER position quietly grew a REAL protective sell,
because BROKER_STOP_ENABLED read its own flag and nothing else. Here
a PAPER session is LABELLED real, because the note read the switch and
nothing else. Same shape both times: one flag answering a question it
does not have the information to answer.

The direction matters less than it looks. A label that overstates
teaches him to discount it, and the day it says "REAL" and means it is
the day he needs to believe it.

WHAT HE READS IT FOR

That note is the sentence on the board that tells him whether money is
moving. It has to name the money.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from dashboard.server import _bot_trading_now

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _State:
    def __init__(self, alert_only, positions=0):
        self.engine = type("E", (), {
            "alert_only": alert_only,
            "open_positions": {str(i): 1 for i in range(positions)},
        })()


# ---------------------------------------------------------------
# THE NOTE NAMES THE MONEY
# ---------------------------------------------------------------

def test_armed_in_paper_does_not_claim_real_orders(monkeypatch):
    """THE CASE. Armed, PAPER, and the board said REAL."""
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")
    got = _bot_trading_now(_State(alert_only=False))
    assert got["on"] is True
    assert "REAL" not in got["note"], got["note"]
    assert got["placing_real_orders"] is False
    assert got["mode"] == "PAPER"


def test_armed_in_live_says_so_plainly(monkeypatch):
    """The control. A note that never says REAL is as useless as one
    that always does."""
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    got = _bot_trading_now(_State(alert_only=False))
    assert got["placing_real_orders"] is True
    assert "REAL" in got["note"]


def test_every_non_live_mode_is_reported_as_simulated(monkeypatch):
    for mode in ("PAPER", "paper", "BACKTEST", "REPLAY", ""):
        monkeypatch.setattr("config.TRADING_MODE", mode)
        got = _bot_trading_now(_State(alert_only=False))
        assert got["placing_real_orders"] is False, mode
        assert "REAL" not in got["note"], mode


def test_watching_is_still_watching(monkeypatch):
    """Disarmed says nothing is being placed, in any mode."""
    for mode in ("PAPER", "LIVE"):
        monkeypatch.setattr("config.TRADING_MODE", mode)
        got = _bot_trading_now(_State(alert_only=True))
        assert got["on"] is False
        assert "places nothing" in got["note"]
        assert got["placing_real_orders"] is False


# ---------------------------------------------------------------
# IT IS READ AT CALL TIME
# ---------------------------------------------------------------

def test_the_mode_is_read_at_call_time_not_import(monkeypatch):
    """He edits the mode between sessions. A value captured at import
    describes the last run, not this one -- the same lesson the broker
    stop learned on 19 August."""
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")
    assert _bot_trading_now(_State(False))["mode"] == "PAPER"
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    assert _bot_trading_now(_State(False))["mode"] == "LIVE"


def test_an_unreadable_mode_never_claims_real(monkeypatch):
    """If the mode cannot be read, the safe answer is NOT to promise
    real orders -- but it must also not promise safety. It reports
    UNKNOWN and does not claim REAL."""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "config":
            raise RuntimeError("config is broken")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    got = _bot_trading_now(_State(alert_only=False))
    assert got["mode"] == "UNKNOWN"
    assert got["placing_real_orders"] is False


# ---------------------------------------------------------------
# NOTHING THAT WORKED MAY CHANGE
# ---------------------------------------------------------------

def test_an_unreadable_engine_is_still_unknown_not_off():
    """The older rule this function already had: answering "off" when
    nothing can be read would tell him he is safe at the one moment we
    cannot say so."""
    got = _bot_trading_now(type("S", (), {"engine": None})())
    assert got["known"] is False
    assert got["on"] is None


def test_the_open_position_count_survives(monkeypatch):
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")
    assert _bot_trading_now(_State(False, positions=3))["open_positions"] == 3


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    body = src[src.find("def _bot_trading_now"):src.find("def build_app")]
    assert "PAPER" in body and "NILKAMAL" in body
