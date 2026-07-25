"""
Decision-correctness tests for TradeController's manual
override flags -- exit, buy (dashboard's BUY button, Top 50
Gainers rows), and short (dashboard's SHORT button, Top 50
Losers rows).
"""

from trading.trade_controller import TradeController


def test_exit_request_is_symbol_scoped():
    tc = TradeController()
    tc.request_exit("TCS")

    assert tc.is_exit_requested("TCS") is True
    assert tc.is_exit_requested("INFY") is False

    tc.clear_exit("TCS")
    assert tc.is_exit_requested("TCS") is False


def test_exit_all_flag_defaults_false_and_is_clearable():
    tc = TradeController()
    assert tc.is_exit_all_requested() is False

    tc.request_exit_all()
    assert tc.is_exit_all_requested() is True

    tc.clear_exit_all()
    assert tc.is_exit_all_requested() is False


def test_buy_request_is_symbol_scoped():
    tc = TradeController()
    tc.request_buy("TCS")

    assert tc.is_buy_requested("TCS") is True
    assert tc.is_buy_requested("INFY") is False

    tc.clear_buy("TCS")
    assert tc.is_buy_requested("TCS") is False


def test_buy_and_exit_requests_are_independent():
    tc = TradeController()
    tc.request_buy("TCS")
    tc.request_exit("TCS")

    assert tc.is_buy_requested("TCS") is True
    assert tc.is_exit_requested("TCS") is True

    tc.clear_buy("TCS")

    assert tc.is_buy_requested("TCS") is False
    assert tc.is_exit_requested("TCS") is True


def test_short_request_is_symbol_scoped():
    tc = TradeController()
    tc.request_short("HFCL")

    assert tc.is_short_requested("HFCL") is True
    assert tc.is_short_requested("IDEA") is False

    tc.clear_short("HFCL")
    assert tc.is_short_requested("HFCL") is False


def test_short_and_buy_requests_are_independent():
    tc = TradeController()
    tc.request_buy("TCS")
    tc.request_short("HFCL")

    assert tc.is_buy_requested("TCS") is True
    assert tc.is_short_requested("HFCL") is True
    assert tc.is_short_requested("TCS") is False
    assert tc.is_buy_requested("HFCL") is False

    tc.clear_short("HFCL")

    assert tc.is_short_requested("HFCL") is False
    assert tc.is_buy_requested("TCS") is True


def test_new_entries_pause_defaults_false_and_toggles():
    tc = TradeController()
    assert tc.is_new_entries_paused() is False

    tc.request_pause_new_entries()
    assert tc.is_new_entries_paused() is True

    tc.resume_new_entries()
    assert tc.is_new_entries_paused() is False
