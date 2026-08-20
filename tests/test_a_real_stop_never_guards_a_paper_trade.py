"""
==========================================================
The buy was imaginary. The sell was real.
==========================================================

    "why dhan pipeline activiated & order placed to SELL NILKAMAL?"
    "order placed= MTF SELL at 2027.20 limit order & today one rule
     saved MTF SELL cannot be placed without actual MTF position held
     in dhan. otherwise it would have worst."
                                -- operator, 19 August 2026

Ten seconds apart in his log:

    14:26:33  PAPER BUY NILKAMAL qty=28 @ 2075.64
              (MANUAL_BUY_DASHBOARD)
    14:26:43  [BROKER_STOP] NILKAMAL: SELL 28 resting at Dhan,
              trigger 2023.75 (id 23132608191377)

TRADING_MODE was PAPER. The BUY was simulated and no order left the
machine. BROKER_STOP_ENABLED read its own flag and nothing else, so
the protective SELL was placed FOR REAL against a position that
existed only in memory.

    NILKAMAL   SELL 28 LIMIT MTF -> REJECTED

Dhan refused it -- there was no MTF position to sell -- and that
rejection is the only reason it cost nothing. The protection was the
EXCHANGE'S, not the bot's. Had he been holding NILKAMAL from his own
trading, a stop derived from an imaginary entry could have been
accepted against real shares and sold them at a level the bot made up.

He put it better than this comment can: "otherwise it would have
worst."

TWO INDEPENDENT REFUSALS, because one flag deciding a live order is
what caused this:

  1. core/engine.py will not ARM the broker stop unless TRADING_MODE
     is LIVE, and says so at startup.
  2. trading/broker_stop.place() refuses again at the moment of
     placement, reading TRADING_MODE at CALL TIME -- he edits .env
     between sessions and a cached answer here places live orders.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from trading.broker_stop import BrokerStop, _trading_is_live

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Dhan:
    """A broker that would happily accept anything.

    place_forever() is the method BrokerStop.place() actually calls --
    Dhan's Forever Order endpoint. The first version of this double
    only had place_order(), so the LIVE control below "passed" by
    never reaching the broker at all. A double that drifts from the
    thing it doubles tests nothing, which this suite has learned more
    than once.
    """

    def __init__(self):
        self.sent = []

    def place_forever(self, **kw):
        self.sent.append(kw)
        return {"status": "success", "data": {"orderId": "123"}}


def _stop(enabled=True):
    return BrokerStop(dhan_client=_Dhan(), exchange_segment="NSE_EQ",
                      product_type="MTF", enabled=enabled)


# ---------------------------------------------------------------
# THE PLACEMENT REFUSES
# ---------------------------------------------------------------

def test_no_order_is_sent_while_trading_mode_is_paper(monkeypatch):
    """THE NILKAMAL CASE. Same call, same flag, and nothing leaves."""
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")
    stop = _stop()
    got = stop.place("NILKAMAL", "1", 28, 2023.75)
    assert got is None
    assert stop.dhan.sent == [], "a real order was sent for a paper trade"


def test_it_refuses_for_every_non_live_mode(monkeypatch):
    for mode in ("PAPER", "paper", "BACKTEST", "", "REPLAY", None):
        monkeypatch.setattr("config.TRADING_MODE", mode)
        stop = _stop()
        assert stop.place("X", "1", 10, 100.0) is None
        assert stop.dhan.sent == []


def test_an_unreadable_mode_is_treated_as_NOT_live(monkeypatch):
    """Refusing costs a restart. Placing costs money that cannot be
    taken back once it fills."""
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "config":
            raise RuntimeError("config is broken")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert _trading_is_live() is False


def test_it_is_read_at_CALL_time_not_cached():
    """He edits .env between sessions. A mode captured at import would
    place live orders on the strength of yesterday's setting."""
    src = (ROOT / "trading" / "broker_stop.py").read_text(encoding="utf-8")
    body = src[src.find("def _trading_is_live"):src.find("class BrokerStop")]
    assert "from config import TRADING_MODE" in body, (
        "TRADING_MODE is being read somewhere other than at call time")


def test_a_live_mode_still_places_the_stop(monkeypatch):
    """The control. A guard that refuses everything would pass every
    test above and leave every real position unprotected."""
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    stop = _stop()
    stop.place("NILKAMAL", "1", 28, 2023.75)
    assert stop.dhan.sent, "LIVE trading lost its protective stop"


# ---------------------------------------------------------------
# AND IT IS NEVER ARMED IN THE FIRST PLACE
# ---------------------------------------------------------------

def test_the_engine_will_not_arm_it_outside_live_mode():
    """Two independent checks, because ONE flag deciding a live order
    is exactly what caused this."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "enabled=BROKER_STOP_ENABLED and _stop_live," in code, (
        "the broker stop can be armed without checking TRADING_MODE")
    assert '_stop_live = str(TRADING_MODE).upper() == "LIVE"' in code


def test_the_refusal_is_announced_at_startup():
    """He turned BROKER_STOP_ENABLED on deliberately. If it is not
    going to arm, he has to be told once, loudly -- silence would read
    as protection he does not have."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    assert "BROKER_STOP_ENABLED is on" in src
    assert "TRADING_MODE is" in src


def test_cancelling_is_still_never_gated():
    """Cancelling removes exposure. It must work in every mode, or a
    stray order from an earlier LIVE session could not be cleaned up
    after switching back to PAPER."""
    src = (ROOT / "trading" / "broker_stop.py").read_text(encoding="utf-8")
    cancel = src[src.find("def cancel"):]
    cancel = cancel[:cancel.find("\n    def ", 10)]
    assert "_trading_is_live" not in cancel, (
        "cancelling a live order now depends on the mode -- a stray "
        "order could not be cleared")


# ---------------------------------------------------------------
# THE SHAPE OF THE FAULT, PINNED
# ---------------------------------------------------------------

def test_the_order_it_would_send_is_a_forever_order(monkeypatch):
    """What LIVE actually sends, pinned. Dhan's Forever Order endpoint
    is the right instrument for a stop that must outlive the process
    -- and the payload it receives is checked here rather than
    assumed, because on 19 August the payload and the booked order
    disagreed."""
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    stop = _stop()
    stop.place("NILKAMAL", "1", 28, 2023.75)
    sent = stop.dhan.sent[0]
    assert sent["transaction_type"] == "SELL"
    assert sent["quantity"] == 28
    assert sent["trigger_Price"] == pytest.approx(2023.75)
    assert sent["product_type"] == "MTF"
