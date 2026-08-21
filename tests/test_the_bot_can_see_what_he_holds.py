"""
==========================================================
Nine real positions at Dhan. The bot showed a phantom.
==========================================================

    "why bot is unable to see dhan account complete holdings? i'm
     expecting that bot must see the positions holding & update me
     about those stocks updates & reasons to hold / add / sell
     completely . none of them were happening then whats the use of
     the bot trading?"
                                -- operator, 21 August 2026

That morning he held nine positions at Dhan:

    CORONA 100   SBIN 500   AARTIPHARM 50   NEOGEN 50   TNPETRO 500
    PANAMAPET 100   SOLARINDS 10   DEEPAKFERT 50   KABRAEXTRU 100

His dashboard showed one NILKAMAL that had never been bought.

NOTHING WAS BROKEN. NOTHING WAS EVER ASKED.

The token worked. /holdings answered on the first attempt when it was
finally called by hand. The bot never called it, because this branch
threw the client away:

    self.executor = PaperExecution(turnover_lookup=turnover_lookup)

main.py has always passed the client in BOTH modes -- with a comment
explaining that PAPER ignores it deliberately. That was correct for
ORDERS and wrong for READS, and one line was deciding both.

Simulating a fill must never touch his account. Reading what he
already holds touches nothing at all.

WHY A CLASS WITH NO ORDER METHODS

On 19 August a PAPER position grew a REAL protective sell because one
flag decided whether a live order could leave. A mode check would be
the same shape of answer. BrokerView instead has no place_order, no
place_forever, no modify and no cancel -- not refusing to trade, but
having no way to. A later edit cannot reopen a door that was never
built.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from trading.broker_view import BrokerView

ROOT = pathlib.Path(__file__).resolve().parents[1]

HELD = [{"symbol": "CORONA", "qty": 100}, {"symbol": "SBIN", "qty": 500}]
INTRADAY = [{"symbol": "NCC", "qty": 169}]


class _Live:
    """Stands in for LiveExecution's read half."""

    def __init__(self, positions=None, holdings=None, boom=None):
        self._p, self._h, self._boom = positions, holdings, boom

    def positions(self):
        if self._boom == "positions":
            raise RuntimeError("connection reset")
        return self._p

    def holdings(self):
        if self._boom == "holdings":
            raise RuntimeError("connection reset")
        return self._h

    def broker_book(self):
        if self._boom == "broker_book":
            raise RuntimeError("connection reset")
        if self._p is None or self._h is None:
            return None
        return list(self._p) + list(self._h)


def _view(**kw):
    v = BrokerView.__new__(BrokerView)
    v.dhan = object()
    v._live = _Live(**kw)
    return v


# ---------------------------------------------------------------
# IT CAN SEE WHAT HE HOLDS
# ---------------------------------------------------------------

def test_it_reads_the_holdings():
    """THE CASE. Nine positions he could see in his app and the bot
    could not."""
    got = _view(holdings=HELD).holdings()
    assert [r["symbol"] for r in got] == ["CORONA", "SBIN"]


def test_the_whole_book_is_both_halves():
    """/positions is intraday, /holdings is overnight. Either alone is
    half his book."""
    got = _view(positions=INTRADAY, holdings=HELD).broker_book()
    assert {r["symbol"] for r in got} == {"NCC", "CORONA", "SBIN"}


# ---------------------------------------------------------------
# IT CANNOT TRADE. NOT "REFUSES TO" -- CANNOT.
# ---------------------------------------------------------------

def test_there_is_no_way_to_place_an_order():
    """The NILKAMAL lesson. A mode flag can be misread; a method that
    does not exist cannot be called."""
    view = _view(holdings=HELD)
    for method in ("place_order", "place_forever", "modify_forever",
                   "cancel_forever", "modify", "cancel", "exit",
                   "square_off", "sell", "buy"):
        assert not hasattr(view, method), f"BrokerView grew {method}()"


def test_the_class_body_contains_no_order_verb():
    """Read against the source, so adding one later fails here."""
    src = (ROOT / "trading" / "broker_view.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    body = code[code.find("class BrokerView"):]
    for banned in ("def place", "def modify", "def cancel", "def sell",
                   "def buy", "def exit"):
        assert banned not in body, f"an order path appeared: {banned}"


# ---------------------------------------------------------------
# NONE IS NOT EMPTY
# ---------------------------------------------------------------

def test_a_failed_read_is_None_not_an_empty_book():
    """"could not ask" and "he holds nothing" must never merge --
    that is how a network blip deletes real positions."""
    assert _view(boom="holdings").holdings() is None
    assert _view(boom="positions").positions() is None
    assert _view(boom="broker_book").broker_book() is None


def test_an_empty_book_is_reported_as_empty():
    assert _view(positions=[], holdings=[]).broker_book() == []


def test_half_a_book_is_no_book():
    """positions alone is the reading that made an MTF position look
    like it had vanished on 5 August."""
    assert _view(positions=INTRADAY, holdings=None).broker_book() is None


def test_no_client_means_no_view_and_no_crash():
    view = BrokerView(None)
    assert view.available is False
    assert view.holdings() is None
    assert view.broker_book() is None


def test_a_broken_constructor_degrades_quietly(monkeypatch):
    """A read-only panel failing must never stop the bot from trading.
    """
    import trading.broker_view as bv

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("dhanhq is unhappy")

    monkeypatch.setattr("trading.live_execution.LiveExecution", _Boom)
    view = bv.BrokerView(object())
    assert view.available is False
    assert view.holdings() is None


# ---------------------------------------------------------------
# AND PAPER MODE ACTUALLY GETS ONE
# ---------------------------------------------------------------

def test_the_paper_branch_wires_it_up():
    src = (ROOT / "trading" / "execution.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "BrokerView(dhan_client" in code, (
        "PAPER is throwing the Dhan client away again")
    assert "self.executor.broker_book = view.broker_book" in code


def test_the_sync_reader_finds_it():
    """core/broker_sync.py looks for broker_book on the EXECUTOR. If
    the attribute is hung anywhere else the panel stays blind."""
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    assert 'getattr(executor, "broker_book", None)' in src


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "trading" / "execution.py").read_text(encoding="utf-8")
    assert "holdings" in src and "NILKAMAL" in src
