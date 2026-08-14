"""
==========================================================
Reconciling must never place an order
==========================================================

31 July 2026. The operator closed a bot-opened SHADOWFAX from the Dhan
app on purpose, to see whether the mismatch would be caught. It was,
within a minute. But repairing it took a raw one-liner typed into a
terminal, editing a JSON file by hand.

Then:

    "on monday mostly i use both for buying & selling - no 100% on
     single i can tell u"

Two books, both being written to by a human, five days a week. A
divergence stops being an incident and becomes routine -- so the
repair has to be a tool, and the tool has to be safe.

THE ONE RULE
------------
IT NEVER TRADES. The tempting "fix" for a position the bot thinks it
holds is to sell it. That stock is not there. On MTF the sell opens a
SHORT, and a bookkeeping discrepancy becomes a real position nobody
chose.

Author : H&M Opportunity Trader
==========================================================
"""

import json

import pytest

import tools.reconcile as reconcile


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "session_state.json"
    path.write_text(json.dumps({
        "date": "2026-07-31",
        "open_positions": {
            "SHADOWFAX": {"qty": 1, "direction": "LONG",
                          "entry_price": 250.94,
                          "entry_reason": "MANUAL_BUY_DASHBOARD"},
        },
        "closed_positions": [],
    }), encoding="utf-8")
    monkeypatch.setattr(reconcile, "STATE", str(path))
    monkeypatch.setattr(reconcile, "TRADING_MODE", "LIVE")
    monkeypatch.setattr(reconcile, "_bot_is_running", lambda: False)
    return path


def _book(path):
    return json.loads(path.read_text(encoding="utf-8"))["open_positions"]


class Broker:
    """Records any order it is asked to place. It must never be."""

    def __init__(self, rows):
        self.rows = rows
        self.orders = []

    def place_order(self, **kwargs):                       # pragma: no cover
        self.orders.append(kwargs)
        raise AssertionError("reconcile placed an order -- it must not")


# ---------------------------------------------------------------
# 1. THE RULE ABOVE ALL OTHERS
# ---------------------------------------------------------------
def test_it_never_places_an_order(state_file, monkeypatch):
    """THE reason this file exists.

    The bot thinks it holds SHADOWFAX; Dhan holds nothing. Selling to
    'fix' that would sell stock that is not there -- on MTF, a SHORT.
    """
    broker = Broker([])
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: broker.rows)
    reconcile.main(apply=True)
    assert broker.orders == []
    assert _book(state_file) == {}


# ---------------------------------------------------------------
# 2. IT REFUSES WHEN CHANGES WOULD BE UNDONE
# ---------------------------------------------------------------
def test_it_refuses_while_the_bot_is_running(state_file, monkeypatch):
    """main.py holds the book in memory and writes it on shutdown. A
    change made underneath it vanishes -- and the operator would see
    'cleared', then find it back, which is worse than refusing."""
    monkeypatch.setattr(reconcile, "_bot_is_running", lambda: True)
    monkeypatch.setattr(reconcile, "_broker_positions",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("must not even ask the broker")))
    reconcile.main(apply=True)
    assert "SHADOWFAX" in _book(state_file)


def test_it_refuses_in_paper_mode(state_file, monkeypatch):
    monkeypatch.setattr(reconcile, "TRADING_MODE", "PAPER")
    reconcile.main(apply=True)
    assert "SHADOWFAX" in _book(state_file)


def test_a_broker_that_will_not_answer_changes_nothing(state_file,
                                                       monkeypatch):
    """Never edit a book against a comparison that failed. An empty
    reply is not 'you hold nothing' -- it is 'we do not know'."""
    def explode():
        raise RuntimeError("network down")

    monkeypatch.setattr(reconcile, "_broker_positions", explode)
    reconcile.main(apply=True)
    assert "SHADOWFAX" in _book(state_file)


# ---------------------------------------------------------------
# 3. DRY RUN IS THE DEFAULT
# ---------------------------------------------------------------
def test_without_apply_nothing_is_written(state_file, monkeypatch):
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [])
    reconcile.main(apply=False)
    assert "SHADOWFAX" in _book(state_file)


# ---------------------------------------------------------------
# 4. DHAN IS RIGHT, IN ALL THREE DIRECTIONS
# ---------------------------------------------------------------
def test_a_position_the_bot_imagines_is_removed(state_file, monkeypatch):
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [])
    reconcile.main(apply=True)
    assert _book(state_file) == {}


def test_a_hand_placed_position_is_adopted(state_file, monkeypatch):
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [
        {"tradingSymbol": "SHADOWFAX", "netQty": 1, "costPrice": 250.94},
        {"tradingSymbol": "ABCAPITAL", "netQty": 1, "costPrice": 409.10},
    ])
    reconcile.main(apply=True)
    book = _book(state_file)
    assert set(book) == {"SHADOWFAX", "ABCAPITAL"}
    assert book["ABCAPITAL"]["qty"] == 1
    assert book["ABCAPITAL"]["entry_price"] == 409.10


def test_an_adopted_position_is_marked_as_not_the_bots(state_file,
                                                       monkeypatch):
    """The bot did not open it, has no stop for it and no idea what it
    was for. It must not start managing it."""
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [
        {"tradingSymbol": "ABCAPITAL", "netQty": 1, "costPrice": 409.10},
    ])
    reconcile.main(apply=True)
    assert _book(state_file)["ABCAPITAL"]["entry_reason"] == \
        reconcile.ADOPTED_REASON


def test_a_short_at_the_broker_is_adopted_as_a_short(state_file,
                                                     monkeypatch):
    """Dhan reports a short as a negative quantity. Adopting it as a
    LONG would invert every P&L the dashboard shows for it."""
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [
        {"tradingSymbol": "IDEA", "netQty": -5, "costPrice": 9.5},
    ])
    reconcile.main(apply=True)
    row = _book(state_file)["IDEA"]
    assert row["direction"] == "SHORT"
    assert row["qty"] == 5


def test_a_partial_fill_is_set_to_the_brokers_number(state_file,
                                                     monkeypatch):
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [
        {"tradingSymbol": "SHADOWFAX", "netQty": 3, "costPrice": 250.94},
    ])
    reconcile.main(apply=True)
    assert _book(state_file)["SHADOWFAX"]["qty"] == 3


def test_an_agreeing_book_is_left_untouched(state_file, monkeypatch):
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [
        {"tradingSymbol": "SHADOWFAX", "netQty": 1, "costPrice": 250.94},
    ])
    before = _book(state_file)
    reconcile.main(apply=True)
    assert _book(state_file) == before


# ---------------------------------------------------------------
# 5. THE OLD BOOK IS ALWAYS RECOVERABLE
# ---------------------------------------------------------------
def test_a_backup_is_written_before_any_change(state_file, monkeypatch):
    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [])
    reconcile.main(apply=True)
    backups = list(state_file.parent.glob("session_state.json.*.bak"))
    assert len(backups) == 1
    saved = json.loads(backups[0].read_text(encoding="utf-8"))
    assert "SHADOWFAX" in saved["open_positions"]


# ---------------------------------------------------------------
# 6. POSITIONS ALONE IS HALF THE BOOK -- THE 5 AUGUST BUG, AT THE SOURCE
# ---------------------------------------------------------------
def test_broker_positions_reads_holdings_not_just_intraday(monkeypatch):
    """_broker_positions() used to build its own raw dhanhq client and
    call client.get_positions() directly -- Dhan's INTRADAY book only.
    An MTF/delivery position moves to /holdings on T+1, so the morning
    after every overnight trade this read "Dhan holds nothing" for a
    real position, and `reconcile.py --apply` would have deleted it
    (trading/live_execution.py's LiveExecution.holdings() docstring has
    the incident). Fixed to route through LiveExecution.broker_book(),
    the same positions+holdings union core/broker_sync.py's own live
    BrokerSync already used. This proves the fix at the one place that
    was still wrong: every other test in this file mocks
    _broker_positions() itself and so never exercised this function's
    own body at all.
    """
    constructed = []

    class _FakeExecution:
        def __init__(self, dhan_client):
            constructed.append(dhan_client)

        def broker_book(self):
            # The exact T+1 shape: absent from /positions, present only
            # in /holdings, with /holdings' own field names.
            return [{"tradingSymbol": "OVERNIGHTCO", "totalQty": 10,
                     "avgCostPrice": 100.0}]

    monkeypatch.setattr("dhanhq.DhanContext", lambda *a, **k: object())
    monkeypatch.setattr("dhanhq.dhanhq", lambda *a, **k: object())
    monkeypatch.setattr(reconcile, "route_orders_through",
                        lambda *a, **k: None)
    monkeypatch.setattr("trading.live_execution.LiveExecution",
                        _FakeExecution)

    rows = reconcile._broker_positions()

    assert constructed, "LiveExecution was never constructed"
    assert rows == [{"tradingSymbol": "OVERNIGHTCO", "totalQty": 10,
                     "avgCostPrice": 100.0}], (
        "an overnight holdings-only position must reach the caller, "
        "not read as an empty book")


def test_broker_positions_refuses_a_half_read_book(monkeypatch):
    """broker_book() returns None when EITHER positions() or
    holdings() failed to answer -- a half-read book is not a book.
    _broker_positions() must refuse loudly rather than pass None
    through, which compare() would otherwise read as 'Dhan holds
    nothing at all' and delete every open position."""

    class _FakeExecution:
        def __init__(self, dhan_client):
            pass

        def broker_book(self):
            return None

    monkeypatch.setattr("dhanhq.DhanContext", lambda *a, **k: object())
    monkeypatch.setattr("dhanhq.dhanhq", lambda *a, **k: object())
    monkeypatch.setattr(reconcile, "route_orders_through",
                        lambda *a, **k: None)
    monkeypatch.setattr("trading.live_execution.LiveExecution",
                        _FakeExecution)

    with pytest.raises(RuntimeError):
        reconcile._broker_positions()


def test_everything_else_in_the_file_survives(state_file, monkeypatch):
    """ORB ranges, closed trades and the date live in the same file.
    Reconciling positions must not cost the day's opening ranges."""
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["orb_ranges"] = {"KAYNES": {"high": 1, "low": 0}}
    data["closed_positions"] = [{"symbol": "NAZARA"}]
    state_file.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(reconcile, "_broker_positions", lambda: [])
    reconcile.main(apply=True)

    after = json.loads(state_file.read_text(encoding="utf-8"))
    assert after["orb_ranges"] == {"KAYNES": {"high": 1, "low": 0}}
    assert after["closed_positions"] == [{"symbol": "NAZARA"}]
    assert after["date"] == "2026-07-31"
