"""
==========================================================
Two live paper positions, deleted for being simulated.
==========================================================

21 August 2026. The bot was given a read-only view of the real Dhan
book in PAPER for the first time -- trading/broker_view.py, built that
morning so it could finally see the operator's nine real holdings
instead of a phantom.

Ninety seconds after the restart:

    11:19:09  NCC: the bot still holds 230, Dhan has none -- it was
              closed elsewhere.
    11:19:09  NCC: removed from the bot's book. It will not be managed
              or exited.
    11:19:09  URBANCO: the bot still holds 201, Dhan has none.
    11:19:09  URBANCO: removed from the bot's book.

NCC and URBANCO were open PAPER positions from that morning's session.
They do not exist at Dhan because they were never sent to Dhan. That
is not a discrepancy -- it is the definition of a simulation.

THE DISTINCTION THE FIX DRAWS

    READING the broker        safe in every mode, and the whole
                              point of the view
    RECONCILING against it    only meaningful when both books are
                              supposed to describe the same money

---- RE-KEYED TO PROVENANCE. 10 September 2026. ----

The guard used to be a session-wide TRADING_MODE == "LIVE": the whole
reconciler was OFF in PAPER. TRADING_MODE is frozen at "PAPER" and the
switch does not move it, so once the switch became the whole answer
that gate was wrong both ways -- a REAL position (switch ON) was never
reconciled, and a mixed book after a mid-session flip could not be
handled at all.

So the reconciler is wired whenever there is a book, and it decides
PER POSITION: only a position the bot opened for real is ever dropped
or warned about. Who opened it is remembered on the fill
(trading/execution._who_opened). A paper or unknown-origin position is
left exactly alone -- which is what protected NCC and URBANCO, now for
the right reason and in a mixed book too.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.broker_sync import BrokerSync

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Execution:
    """Stands in for trading/execution.Execution: it remembers who
    opened each symbol."""

    def __init__(self, opened):
        self._opened = {k.upper(): v for k, v in opened.items()}

    def _who_opened(self, symbol):
        return self._opened.get(str(symbol or "").upper())


class _Engine:
    def __init__(self, **positions):
        self.open_positions = dict(positions)


def _sync(engine, opened=None):
    sync = BrokerSync.__new__(BrokerSync)
    sync.engine = engine
    sync.execution = _Execution(opened or {})
    return sync


# ---------------------------------------------------------------
# A PAPER (OR UNKNOWN) POSITION SURVIVES
# ---------------------------------------------------------------

def test_a_paper_opened_position_is_not_dropped():
    """THE CASE. NCC, deleted ninety seconds after a restart for the
    crime of being simulated. drop() exists now, but it refuses."""
    engine = _Engine(NCC={"qty": 230})
    drop = _sync(engine, opened={"NCC": "paper"})._drop_closed_fn()
    assert drop is not None
    drop("NCC")
    assert list(engine.open_positions) == ["NCC"], (
        "a paper position was deleted as a Dhan discrepancy")


def test_an_unknown_origin_position_is_not_dropped():
    """His own manual holdings, and anything with no bot fill on
    record, are unknown. Deleting one wrongly costs a position that
    then gets no stop and no exit."""
    engine = _Engine(NCC={"qty": 230})
    _sync(engine, opened={})._drop_closed_fn()("NCC")
    assert list(engine.open_positions) == ["NCC"]


def test_no_execution_wired_drops_nothing():
    """Provenance cannot be read -> nothing is dropped. Fails closed."""
    engine = _Engine(NCC={"qty": 230})
    sync = BrokerSync.__new__(BrokerSync)
    sync.engine = engine
    # no sync.execution at all
    sync._drop_closed_fn()("NCC")
    assert list(engine.open_positions) == ["NCC"]


# ---------------------------------------------------------------
# A REAL POSITION IS STILL RECONCILED
# ---------------------------------------------------------------

def test_a_live_opened_position_is_dropped():
    """The control. A position the bot opened for real that Dhan does
    not have IS a real disagreement, and this suite must not have
    disabled the reconciler to fix the paper case."""
    engine = _Engine(NCC={"qty": 230}, SBIN={"qty": 500})
    drop = _sync(engine, opened={"NCC": "live", "SBIN": "live"})._drop_closed_fn()
    assert drop is not None
    drop("NCC")
    assert list(engine.open_positions) == ["SBIN"]


def test_the_live_drop_is_case_insensitive():
    engine = _Engine(NCC={"qty": 230})
    _sync(engine, opened={"NCC": "live"})._drop_closed_fn()("ncc")
    assert engine.open_positions == {}


def test_a_mixed_book_drops_only_the_real_one():
    """THE REASON IT IS PER POSITION. After a mid-session flip the book
    holds both. The real closed one is dropped; the paper one stays."""
    engine = _Engine(REALCO={"qty": 100}, PAPERCO={"qty": 50})
    drop = _sync(engine,
                 opened={"REALCO": "live", "PAPERCO": "paper"})._drop_closed_fn()
    drop("REALCO")
    drop("PAPERCO")
    assert list(engine.open_positions) == ["PAPERCO"]


def test_it_still_needs_an_engine():
    """The older rule: no engine, nothing to drop from."""
    sync = BrokerSync.__new__(BrokerSync)
    sync.engine = None
    sync.execution = _Execution({})
    assert sync._drop_closed_fn() is None


# ---------------------------------------------------------------
# READING IS NOT RECONCILING
# ---------------------------------------------------------------

def test_provenance_is_read_not_the_mode():
    """The switch is the whole answer. The reconciler must decide by
    who opened the position, not by config.TRADING_MODE (frozen at
    PAPER, and the same lesson the broker stop learned on 19 August)."""
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    body = src[src.find("def _drop_closed_fn"):src.find("def check(")]
    assert "_opened_live" in body
    # The read forms, which cannot appear in the explanatory prose:
    assert "from config import TRADING_MODE" not in body, (
        "the reconciler is importing the frozen mode again")
    assert "str(TRADING_MODE)" not in body, (
        "the reconciler is reading the frozen mode again")


def test_the_read_only_view_is_untouched():
    """The view exists so PAPER can SEE his real holdings. Fixing the
    reconciler must not have taken that away again."""
    from trading.broker_view import BrokerView
    for method in ("holdings", "positions", "broker_book"):
        assert hasattr(BrokerView, method)


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    body = src[src.find("def _drop_closed_fn"):src.find("def check(")]
    assert "URBANCO" in body and "simulation" in body
