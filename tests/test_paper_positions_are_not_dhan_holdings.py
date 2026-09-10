"""A simulated position missing from Dhan is not a discrepancy.

    "old paper trades are treated as still dhan holdings"
                                    -- operator, 24 August 2026

On the 24 August pre-open the bot carried three PAPER positions from
Friday -- CDSL, JBMA, NCC -- compared them against his real eight-
holding Dhan account, and warned once a MINUTE for 37 minutes that
each "was closed elsewhere". Nothing closed them. They were never open
anywhere except the simulation.

---- RE-KEYED TO PROVENANCE. 10 September 2026. ----

Whether a position is real used to be a session-wide _is_live() that
read config.TRADING_MODE. TRADING_MODE is frozen at "PAPER" and the
switch does not move it, so once the switch became the whole answer a
REAL position (switch ON) reconciled as if it were paper. The switch
can also flip mid-session, so the book can hold both kinds at once.

So it is decided PER POSITION now, by who opened it
(trading/execution._who_opened), via BrokerSync._opened_live(). This
test holds that a paper-opened (or unknown-origin) position is never
treated as a Dhan discrepancy, and never raises on the trading loop.
"""

import core.broker_sync as broker_sync


class _Execution:
    def __init__(self, opened):
        self._opened = {k.upper(): v for k, v in opened.items()}

    def _who_opened(self, symbol):
        return self._opened.get(str(symbol or "").upper())


def _sync(opened=None):
    sync = broker_sync.BrokerSync.__new__(broker_sync.BrokerSync)
    sync.execution = _Execution(opened or {})
    return sync


def test_a_paper_position_is_not_real():
    assert _sync(opened={"NCC": "paper"})._opened_live("NCC") is False


def test_a_live_position_is_real():
    assert _sync(opened={"NCC": "live"})._opened_live("NCC") is True


def test_an_unknown_origin_is_unknown():
    # His own manual holdings, and anything with no bot fill on record.
    # Unknown is None, and every caller treats it as "leave it alone".
    assert _sync(opened={})._opened_live("NCC") is None


def test_it_is_read_per_call_not_cached():
    # The switch can flip while a position is open. Provenance is read
    # fresh, so a symbol re-opened for real reports live afterwards.
    sync = broker_sync.BrokerSync.__new__(broker_sync.BrokerSync)
    sync.execution = _Execution({"NCC": "paper"})
    assert sync._opened_live("NCC") is False
    sync.execution = _Execution({"NCC": "live"})
    assert sync._opened_live("NCC") is True


def test_no_execution_never_raises():
    # This runs on the trading loop and must never raise. No execution
    # -> unknown -> "leave it alone", which suppresses a warning rather
    # than deleting a book.
    sync = broker_sync.BrokerSync.__new__(broker_sync.BrokerSync)
    # no sync.execution attribute at all
    assert sync._opened_live("NCC") is None


def test_a_broken_who_opened_reads_as_unknown():
    class _Boom:
        def _who_opened(self, symbol):
            raise RuntimeError("provenance store is broken")
    sync = broker_sync.BrokerSync.__new__(broker_sync.BrokerSync)
    sync.execution = _Boom()
    assert sync._opened_live("NCC") is None


def test_paper_still_refuses_to_drop_a_position():
    # The other half of the same rule, fixed 21 August: a paper
    # position absent from Dhan must never be deleted. The drop fn
    # exists now, but it refuses a paper-opened symbol.
    class _Engine:
        def __init__(self):
            self.open_positions = {"NCC": {"qty": 230}}
    engine = _Engine()
    sync = broker_sync.BrokerSync.__new__(broker_sync.BrokerSync)
    sync.engine = engine
    sync.execution = _Execution({"NCC": "paper"})
    sync._drop_closed_fn()("NCC")
    assert list(engine.open_positions) == ["NCC"]
