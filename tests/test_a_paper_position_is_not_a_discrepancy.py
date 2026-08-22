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

WHY IT HAD NEVER HAPPENED BEFORE

core/broker_sync.py's reconciler has always been correct in LIVE:
a position the bot thinks it holds that the broker does not have is a
real and dangerous disagreement, and dropping it from the bot's book
is right.

In PAPER the question had simply never been ASKED, because _reader()
returned None -- there was no broker view at all. Giving PAPER a
reader answered a question nobody had checked the reconciler could
handle, and it answered it by deleting his positions.

THE DISTINCTION THE FIX DRAWS

    READING the broker        safe in every mode, and the whole
                              point of the view
    RECONCILING against it    only meaningful when both books are
                              supposed to describe the same money

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.broker_sync import BrokerSync

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Engine:
    def __init__(self, **positions):
        self.open_positions = dict(positions)
        self.alert_only = True


def _sync(engine):
    sync = BrokerSync.__new__(BrokerSync)
    sync.engine = engine
    return sync


# ---------------------------------------------------------------
# PAPER POSITIONS SURVIVE
# ---------------------------------------------------------------

def test_paper_mode_cannot_drop_a_position(monkeypatch):
    """THE CASE. NCC and URBANCO, deleted ninety seconds after a
    restart for the crime of being simulated."""
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")
    assert _sync(_Engine(NCC={"qty": 230}))._drop_closed_fn() is None


def test_no_non_live_mode_can_drop_a_position(monkeypatch):
    for mode in ("PAPER", "paper", "BACKTEST", "REPLAY", "", None):
        monkeypatch.setattr("config.TRADING_MODE", mode)
        assert _sync(_Engine(NCC={"qty": 230}))._drop_closed_fn() is None, mode


def test_an_unreadable_mode_does_not_delete(monkeypatch):
    """Refusing to reconcile costs a stale row on a panel. Deleting
    wrongly costs a position that then gets no stop and no exit."""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "config":
            raise RuntimeError("config is broken")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert _sync(_Engine(NCC={"qty": 230}))._drop_closed_fn() is None


# ---------------------------------------------------------------
# LIVE RECONCILIATION STILL WORKS
# ---------------------------------------------------------------

def test_live_mode_still_drops_a_closed_position(monkeypatch):
    """The control. In LIVE a position the broker does not have IS a
    real disagreement, and this suite must not have disabled the
    reconciler to fix the paper case."""
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    engine = _Engine(NCC={"qty": 230}, SBIN={"qty": 500})
    drop = _sync(engine)._drop_closed_fn()
    assert drop is not None
    drop("NCC")
    assert list(engine.open_positions) == ["SBIN"]


def test_live_drop_is_case_insensitive(monkeypatch):
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    engine = _Engine(NCC={"qty": 230})
    _sync(engine)._drop_closed_fn()("ncc")
    assert engine.open_positions == {}


def test_it_still_needs_an_engine(monkeypatch):
    """The older rule: no engine, nothing to drop from."""
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")
    sync = BrokerSync.__new__(BrokerSync)
    sync.engine = None
    assert sync._drop_closed_fn() is None


# ---------------------------------------------------------------
# READING IS NOT RECONCILING
# ---------------------------------------------------------------

def test_the_mode_is_read_at_call_time():
    """He edits the mode between sessions. A value captured at import
    describes the last run -- the same lesson the broker stop learned
    on 19 August."""
    src = (ROOT / "core" / "broker_sync.py").read_text(encoding="utf-8")
    body = src[src.find("def _drop_closed_fn"):src.find("def check(")]
    assert "from config import TRADING_MODE" in body


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
