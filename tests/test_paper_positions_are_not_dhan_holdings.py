"""A simulated position missing from Dhan is not a discrepancy.

    "old paper trades are treated as still dhan holdings"
                                    -- operator, 24 August 2026

On the 24 August pre-open the bot carried three PAPER positions from
Friday -- CDSL, JBMA, NCC -- compared them against his real eight-
holding Dhan account, and warned once a MINUTE for 37 minutes that
each "was closed elsewhere". Nothing closed them. They were never open
anywhere except the simulation.
"""

import core.broker_sync as broker_sync


def _sync():
    return broker_sync.BrokerSync.__new__(broker_sync.BrokerSync)


def test_paper_is_not_live(monkeypatch):
    monkeypatch.setattr("config.TRADING_MODE", "PAPER", raising=False)
    assert _sync()._is_live() is False


def test_live_is_live(monkeypatch):
    monkeypatch.setattr("config.TRADING_MODE", "LIVE", raising=False)
    assert _sync()._is_live() is True


def test_the_mode_is_read_at_call_time_not_import_time(monkeypatch):
    # A value captured at import once told him the bot was "placing
    # REAL orders" while TRADING_MODE said PAPER.
    sync = _sync()
    monkeypatch.setattr("config.TRADING_MODE", "PAPER", raising=False)
    assert sync._is_live() is False
    monkeypatch.setattr("config.TRADING_MODE", "LIVE", raising=False)
    assert sync._is_live() is True


def test_a_broken_config_reads_as_not_live(monkeypatch):
    # This runs on the trading loop and must never raise. Failing
    # closed means "not live", which suppresses a warning rather than
    # deleting a book.
    import config
    monkeypatch.delattr(config, "TRADING_MODE", raising=False)
    assert _sync()._is_live() is False


def test_paper_still_refuses_to_drop_a_position(monkeypatch):
    # The other half of the same rule, fixed 21 August: a paper
    # position absent from Dhan must never be deleted either.
    monkeypatch.setattr("config.TRADING_MODE", "PAPER", raising=False)
    assert _sync()._drop_closed_fn() is None
