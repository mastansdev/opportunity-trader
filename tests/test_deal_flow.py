"""
Tests for core/deal_flow.py -- bulk / block deals and short selling.

NSE's field names differ between endpoints and drift over time, so
normalise() has to be forgiving. These tests pin both the documented
shapes and the fallback behaviour.
"""

from core import deal_flow
from core.deal_flow import BLOCK, BULK, normalise, summarise_by_symbol


def test_normalise_reads_the_live_endpoint_shape():
    row = {"symbol": "PARAS", "clientName": "SOME FUND", "buySell": "BUY",
           "quantity": "1,00,000", "tradePrice": "850.50",
           "date": "24-Jul-2026"}
    rec = normalise(row, BLOCK)
    assert rec["symbol"] == "PARAS"
    assert rec["side"] == "BUY"
    # Indian digit grouping must survive
    assert rec["qty"] == 100000
    assert rec["price"] == 850.50
    assert rec["value"] == 100000 * 850.50
    assert rec["kind"] == BLOCK


def test_normalise_reads_the_archive_BD_shape():
    row = {"BD_SYMBOL": "KALYANKJIL", "BD_CLIENT_NAME": "AN INVESTOR",
           "BD_BUY_SELL": "SELL", "BD_QTY_TRD": "50000",
           "BD_TP_WATP": "600", "BD_DT_DATE": "24-Jul-2026"}
    rec = normalise(row, BULK)
    assert rec["symbol"] == "KALYANKJIL"
    assert rec["side"] == "SELL"
    assert rec["value"] == 50000 * 600


def test_normalise_survives_unknown_columns():
    rec = normalise({"Symbol": "X"}, BULK)
    assert rec["symbol"] == "X"
    assert rec["qty"] is None
    assert rec["value"] is None


def test_side_is_normalised_to_BUY_or_SELL():
    assert normalise({"symbol": "X", "buySell": "b"}, BULK)["side"] == "BUY"
    assert normalise({"symbol": "X", "buySell": "Sell"}, BULK)["side"] == "SELL"


def test_summarise_nets_buys_against_sells():
    deals = [
        dict(symbol="PARAS", side="BUY", value=1e7, client="FUND A"),
        dict(symbol="PARAS", side="BUY", value=2e7, client="FUND B"),
        dict(symbol="PARAS", side="SELL", value=5e6, client="FUND A"),
        dict(symbol="OTHER", side="SELL", value=1e7, client="FUND C"),
    ]
    out = summarise_by_symbol(deals)
    assert out["PARAS"]["buy_value"] == 3e7
    assert out["PARAS"]["sell_value"] == 5e6
    assert out["PARAS"]["net_value"] == 2.5e7
    assert out["PARAS"]["deals"] == 3
    assert out["PARAS"]["clients"] == ["FUND A", "FUND B"]
    assert out["OTHER"]["net_value"] == -1e7


def test_summarise_handles_missing_values():
    out = summarise_by_symbol([dict(symbol="X", side="BUY", value=None,
                                    client="")])
    assert out["X"]["buy_value"] == 0.0
    assert out["X"]["clients"] == []


def test_fetch_fails_open_when_nse_is_unreachable(monkeypatch):
    """Nothing depends on deal data -- a network failure must return []
    and never raise."""
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(deal_flow, "warn", lambda *a, **k: None)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nse":
            raise ImportError("nse missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert deal_flow.fetch(BULK) == []
    assert deal_flow.fetch_todays_blocks() == []


def test_rows_without_a_symbol_are_dropped():
    deals = [normalise({"clientName": "X"}, BULK)]
    assert deals[0]["symbol"] == ""
    assert summarise_by_symbol([d for d in deals if d["symbol"]]) == {}
