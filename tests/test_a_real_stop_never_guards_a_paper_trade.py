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

---- RE-KEYED TO THE SWITCH. 10 September 2026. ----

    "OFF = paper & ON = Real trades thats it & final" -- his rule

The refusal used to read config.TRADING_MODE. TRADING_MODE is frozen
at "PAPER" and the switch does not move it, so once the switch became
the whole answer this refused EVERY stop while the switch was ON --
real positions with no broker backstop, the opposite failure and just
as expensive.

The rule is unchanged; only its INPUT is. A resting order at Dhan may
only protect a position that was itself opened for real, and which
positions are real is decided PER POSITION by who opened it
(trading/execution._who_opened) -- not by a session-wide flag. That is
strictly stronger: a book holding both paper and real positions after
a mid-session flip is handled one position at a time.

TWO INDEPENDENT REFUSALS, because one flag deciding a live order is
what caused this:

  1. core/engine.py arms the broker stop on the pure capability
     (BROKER_STOP_ENABLED) and hands it a predicate that answers, per
     symbol, whether that position was opened for real.
  2. trading/broker_stop.place() refuses again at the moment of
     placement, asking that predicate -- and with NO predicate wired
     it fails closed and places nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from trading.broker_stop import BrokerStop

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


def _stop(opened=None, enabled=True):
    """A BrokerStop whose per-position predicate says which symbols were
    opened for real. `opened` maps SYMBOL -> "live"/"paper"; anything
    absent is unknown (None)."""
    opened = {k.upper(): v for k, v in (opened or {}).items()}
    return BrokerStop(
        dhan_client=_Dhan(), exchange_segment="NSE_EQ",
        product_type="MTF", enabled=enabled,
        is_live_position=lambda s: opened.get(str(s).upper()) == "live")


# ---------------------------------------------------------------
# THE PLACEMENT REFUSES A PAPER-OPENED POSITION
# ---------------------------------------------------------------

def test_no_order_is_sent_for_a_paper_opened_position():
    """THE NILKAMAL CASE. It was bought on paper; the protective SELL
    must not leave the machine."""
    stop = _stop(opened={"NILKAMAL": "paper"})
    got = stop.place("NILKAMAL", "1", 28, 2023.75)
    assert got is None
    assert stop.dhan.sent == [], "a real order was sent for a paper trade"


def test_it_refuses_when_the_origin_is_unknown():
    """Unknown fails closed. His own manual holdings and anything with
    no bot fill on record must not grow a bot stop."""
    stop = _stop(opened={})            # nothing on record for "X"
    assert stop.place("X", "1", 10, 100.0) is None
    assert stop.dhan.sent == []


def test_no_predicate_wired_fails_closed():
    """A BrokerStop built without a predicate cannot vouch for any
    position, so it places nothing. The expensive mistake is a real
    order nobody meant; a refused one costs a restart."""
    stop = BrokerStop(dhan_client=_Dhan(), exchange_segment="NSE_EQ",
                      product_type="MTF", enabled=True)
    assert stop.place("NILKAMAL", "1", 28, 2023.75) is None
    assert stop.dhan.sent == []


def test_a_live_opened_position_still_gets_its_stop():
    """The control. A guard that refuses everything would pass every
    test above and leave every real position unprotected."""
    stop = _stop(opened={"NILKAMAL": "live"})
    stop.place("NILKAMAL", "1", 28, 2023.75)
    assert stop.dhan.sent, "a real position lost its protective stop"


def test_a_mixed_book_is_handled_one_position_at_a_time():
    """THE REASON IT IS PER POSITION. After a mid-session flip the book
    holds both. The real one is protected; the paper one is not."""
    stop = _stop(opened={"REALCO": "live", "PAPERCO": "paper"})
    stop.place("PAPERCO", "1", 10, 100.0)
    stop.place("REALCO", "2", 5, 200.0)
    sent = [s["security_id"] for s in stop.dhan.sent]
    assert sent == ["2"], "the paper position was protected, or the real one was not"


def test_the_predicate_is_read_at_CALL_time_not_cached():
    """The switch can flip while a position is open. The predicate is
    asked at placement, so it reflects who opened THIS symbol -- not a
    value captured when the BrokerStop was built."""
    src = (ROOT / "trading" / "broker_stop.py").read_text(encoding="utf-8")
    place = src[src.find("def place("):]
    place = place[:place.find("\n    def ", 10)]
    code = "\n".join(ln for ln in place.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "self._is_live_position(symbol)" in code, (
        "placement no longer asks the per-symbol predicate")
    assert "TRADING_MODE" not in code, (
        "placement is reading the frozen mode again instead of the switch")


# ---------------------------------------------------------------
# AND THE ENGINE ARMS IT ON CAPABILITY, GATES IT PER POSITION
# ---------------------------------------------------------------

def test_the_engine_arms_on_capability_not_on_the_mode():
    """`enabled` is the pure capability now. TRADING_MODE must not
    decide whether a real stop can rest -- that is what left real
    positions unprotected while the switch was ON."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "enabled=BROKER_STOP_ENABLED," in code, (
        "the broker stop is no longer armed on the pure capability flag")
    assert "_stop_live" not in code, (
        "the removed TRADING_MODE gate is back on the broker stop")
    assert 'str(TRADING_MODE).upper() == "LIVE"' not in code


def test_the_engine_hands_it_a_per_position_predicate():
    """Two independent checks, because ONE flag deciding a live order
    is exactly what caused this. The engine's check is the predicate,
    keyed on who opened the position."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "is_live_position=" in code
    assert "_who_opened" in code


def test_cancelling_is_still_never_gated():
    """Cancelling removes exposure. It must work whatever the switch
    says, or a stray order from an earlier real session could not be
    cleaned up after switching back to paper."""
    src = (ROOT / "trading" / "broker_stop.py").read_text(encoding="utf-8")
    cancel = src[src.find("def cancel"):]
    cancel = cancel[:cancel.find("\n    def ", 10)]
    assert "_is_live_position" not in cancel, (
        "cancelling a live order now depends on provenance -- a stray "
        "order could not be cleared")


# ---------------------------------------------------------------
# THE SHAPE OF THE FAULT, PINNED
# ---------------------------------------------------------------

def test_the_order_it_would_send_is_a_forever_order():
    """What a real stop actually sends, pinned. Dhan's Forever Order
    endpoint is the right instrument for a stop that must outlive the
    process -- and the payload it receives is checked here rather than
    assumed, because on 19 August the payload and the booked order
    disagreed."""
    stop = _stop(opened={"NILKAMAL": "live"})
    stop.place("NILKAMAL", "1", 28, 2023.75)
    sent = stop.dhan.sent[0]
    assert sent["transaction_type"] == "SELL"
    assert sent["quantity"] == 28
    assert sent["trigger_Price"] == pytest.approx(2023.75)
    assert sent["product_type"] == "MTF"
