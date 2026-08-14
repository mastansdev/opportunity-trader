"""
The rest of the pending list, 30 July 2026.

    "complete all pending works start now"

Four separate pieces, each one a thing the bot already had and was not
using:

  closed_positions   built every session, kept in memory only, wiped by
                     every restart -- and there were four on 30 July.
  broker_sync        live_execution.positions() has existed since it was
                     written and has never once been called, so the bot's
                     book and Dhan's have never been compared.
  FII / DII          a config placeholder since day one. News Pulse has
                     been posting the real figure all along.
  pre-open imbalance collected since core/preopen.py was written, shown
                     on the panel today, never scored.
"""

import pytest

from core import state_store
from core.broker_sync import BrokerSync, compare
from core.market_flows import parse_flow_message
from core.shortlist import ShortlistBuilder


# ---------------------------------------------------------------
# TODAY'S CLOSED TRADES SURVIVE A RESTART
# ---------------------------------------------------------------

def test_closed_trades_round_trip(tmp_path):
    import datetime
    path = str(tmp_path / "s.json")
    closed = [{"symbol": "KAYNES", "qty": 10, "entry_price": 100.0,
               "entry_time": datetime.datetime(2026, 7, 30, 9, 45),
               "exit_price": 110.0, "net_pnl": 95.5}]
    state_store.save({}, {}, closed_positions=closed, path=path)
    back = state_store.load_closed_positions(path=path)
    assert len(back) == 1
    assert back[0]["net_pnl"] == 95.5


def test_a_datetime_does_not_fail_the_whole_save(tmp_path):
    """One un-encodable value would take the ORB ranges and the open
    positions down with it, which is a far worse outcome than losing a
    timestamp."""
    import datetime
    path = str(tmp_path / "s.json")
    state_store.save(
        {"TCS": {"high": 1.0}}, {"TCS": {"qty": 1}},
        closed_positions=[{"exit_time": datetime.datetime(2026, 7, 30, 15, 4)}],
        path=path)
    assert state_store.load_closed_positions(path=path)[0]["exit_time"] \
        == "2026-07-30T15:04:00"
    # and the rest of the file is intact
    import json
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["orb_ranges"] == {"TCS": {"high": 1.0}}


def test_yesterdays_trades_are_not_todays_performance(tmp_path):
    path = str(tmp_path / "s.json")
    state_store.save({}, {}, closed_positions=[{"symbol": "OLD"}], path=path)
    assert state_store.load_closed_positions(path=path, today="2099-01-01") == []


# ---------------------------------------------------------------
# THE BOT'S BOOK vs DHAN'S
# ---------------------------------------------------------------

def test_a_matching_book_is_in_sync():
    got = compare({"KAYNES": {"qty": 10, "direction": "LONG"}},
                  [{"tradingSymbol": "KAYNES", "netQty": 10}])
    assert got["in_sync"] is True


def test_a_position_the_broker_does_not_have_is_reported():
    got = compare({"KAYNES": {"qty": 10, "direction": "LONG"}}, [])
    assert got["only_in_bot"] == [{"symbol": "KAYNES", "bot_qty": 10.0}]
    assert got["in_sync"] is False


def test_a_position_the_bot_does_not_know_about_is_reported():
    """A manual trade in the Dhan app, or a fill the bot never saw.

    Asserts the FACTS, not the exact dict. This originally compared the
    whole row for equality:

        assert got["only_at_broker"] == [{"symbol": "INFY",
                                          "broker_qty": 15.0}]

    and went red on 31 July for a change that broke nothing -- adding
    entry price, live price and P&L to the same row, so a hand-placed
    position could be tracked rather than merely noticed.

    A test that pins a payload shape fails on every enrichment and
    passes on none of the failures worth catching. What matters here is
    that the position is found, attributed to the broker, and carries
    the right quantity.
    """
    got = compare({}, [{"tradingSymbol": "INFY", "netQty": 15}])
    assert len(got["only_at_broker"]) == 1
    row = got["only_at_broker"][0]
    assert row["symbol"] == "INFY"
    assert row["broker_qty"] == 15.0
    assert got["in_sync"] is False
    assert got["only_in_bot"] == []


def test_a_partial_fill_shows_as_a_quantity_difference():
    got = compare({"TATASTEEL": {"qty": 50, "direction": "LONG"}},
                  [{"tradingSymbol": "TATASTEEL", "netQty": 30}])
    assert got["quantity_differs"] == [
        {"symbol": "TATASTEEL", "bot_qty": 50.0, "broker_qty": 30.0}]


def test_a_short_is_compared_as_a_negative_quantity():
    """Otherwise a 20-share short and a 20-share long look identical,
    which is the most expensive possible way to agree."""
    got = compare({"SBIN": {"qty": 20, "direction": "SHORT"}},
                  [{"tradingSymbol": "SBIN", "netQty": -20}])
    assert got["in_sync"] is True


def test_buy_and_sell_legs_are_netted():
    got = compare({"TCS": {"qty": 10, "direction": "LONG"}},
                  [{"tradingSymbol": "TCS", "buyQty": 30, "sellQty": 20}])
    assert got["in_sync"] is True


def test_paper_mode_says_nothing_was_checked():
    """A green tick that only means "we did not look" is worse than no
    tick at all."""
    got = BrokerSync(execution=object()).check({})
    assert got["available"] is False
    assert got["in_sync"] is None
    assert "not a clean bill of health" in got["note"]


def test_a_broker_that_does_not_answer_is_not_a_clean_book():
    class Silent:
        def positions(self):
            return None
    got = BrokerSync(execution=Silent()).check({})
    assert got["in_sync"] is None
    assert "unverified" in got["note"]


def test_the_sync_never_corrects_anything():
    """Rewriting the bot's book hides the event worth knowing about;
    sending orders to make the broker match could double a position.
    Both are the kind of automatic fix that turns a discrepancy into a
    loss, so this module reports and does nothing else.

    Checked on CODE, not prose -- the docstrings explain exactly these
    dangers and a naive substring search matches its own warnings.
    """
    import io, tokenize
    src = open("core/broker_sync.py", encoding="utf-8").read()
    code = " ".join(
        tok.string for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING))
    for forbidden in ("execution.buy", "execution.sell", "place_order",
                      "kill_switch", "open_positions ["):
        assert forbidden not in code, (
            f"broker_sync must not act, only report -- found {forbidden!r}")


# ---------------------------------------------------------------
# FII / DII, FROM THE CHANNEL THAT POSTS IT
# ---------------------------------------------------------------

def test_the_real_message_parses():
    text = ("FII / DII FLOWS | FIIs were net buyers of Rs 3,623.51 Cr in "
            "equities today, while DIIs were net sellers of Rs 1,864.03 Cr.")
    assert parse_flow_message(text) == {"fii_cr": 3623.51, "dii_cr": -1864.03}


def test_selling_is_negative():
    """The whole point. Both stored as magnitudes would make a day of
    heavy institutional selling read exactly like heavy buying."""
    out = parse_flow_message("FIIs were net sellers of Rs 900 Cr")
    assert out["fii_cr"] == -900.0


def test_a_line_with_no_flows_returns_none():
    """Distinct from "flows were zero" -- nobody has seen that day."""
    assert parse_flow_message("Nifty closed above 24,300") is None
    assert parse_flow_message("") is None


# ---------------------------------------------------------------
# WHO WAS STILL WAITING AT THE OPEN
# ---------------------------------------------------------------

class _Book:
    def __init__(self, rows):
        self.rows = rows

    def snapshot(self):
        return {"groups": {"mine": {"gap_up": self.rows}}}


def _rank_with(book, change_pct=7.0, symbol="X"):
    builder = ShortlistBuilder(preopen=book)
    out = builder.rank([{"symbol": symbol, "sector": "S", "ltp": 100.0,
                         "change_pct": change_pct, "volume": 1000}], top=5)
    return out["rows"][0] if out["rows"] else None


def test_buyers_waiting_support_a_riser():
    got = _rank_with(_Book([{"symbol": "X", "imbalance": 0.628}]))
    assert any("BUYERS still waiting" in w for w in got["why"])
    assert got["score"] > 7.0


def test_buyers_waiting_count_against_a_faller():
    """A stock down 5% with a queue of unfilled BUY orders behind it is
    a different animal from one falling with sellers still queued."""
    got = _rank_with(_Book([{"symbol": "X", "imbalance": 0.628}]),
                     change_pct=-5.0)
    assert any("against the move" in w for w in got["why"])
    assert got["score"] < 5.0


def test_a_balanced_book_says_nothing():
    """52/48 is balanced. Calling that "buyers waiting" makes the signal
    noise."""
    got = _rank_with(_Book([{"symbol": "X", "imbalance": 0.04}]))
    assert not any("waiting" in w for w in got["why"])


def test_no_preopen_data_is_not_a_crash():
    assert _rank_with(None) is not None


def test_a_broken_book_costs_the_chip_not_the_shortlist():
    class Angry:
        def snapshot(self):
            raise RuntimeError("file gone")
    assert _rank_with(Angry()) is not None
