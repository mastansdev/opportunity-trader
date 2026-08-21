"""
==========================================================
"this is 10th time i'm telling u that stock was rejected"
==========================================================

    "EVEN TODAY NILKAMAL IS ON DAHBOARD. WHY? this is 10 th time i'm
     telling u that stock was rejected & not sell/buy happened."
                                -- operator, 21 August 2026

He was right every one of those times, and the bot had no way to be
told.

NILKAMAL entered on 19 August as MANUAL_BUY_DASHBOARD with
TRADING_MODE PAPER. The buy was simulated. The protective sell that
followed was sent for real and REJECTED by Dhan -- there was no MTF
position to sell, because there was no position at all.

It then sat on his dashboard for three days holding one of three
seats, because:

  * FORCE_SQUARE_OFF_AT_CLOSE is False, so MTF positions carry
    overnight -- correct for the product,
  * and the engine refuses to sell a position it reads as HIS:
        09:18  [YOUR TRADE] NILKAMAL has fallen back to 2013.00
               ... NOT sold -- it is your position, not the bot's.

Both rules are right. Together they made a phantom immortal.

WHY exit_all WAS NOT THE ANSWER

It would have booked a fake trade -- an entry that never happened
closed at a price it never traded -- into the record he measures the
bot against. The book has to be able to say "this never happened"
without inventing a trade to say it with.

Author : H&M Opportunity Trader
==========================================================
"""

import json

import pytest

from tools.forget_position import forget


@pytest.fixture
def state(tmp_path):
    p = tmp_path / "session_state.json"
    p.write_text(json.dumps({
        "date": "2026-08-21",
        "open_positions": {
            "NILKAMAL": {"qty": 28, "entry_price": 2075.64},
            "SBIN": {"qty": 500, "entry_price": 1117.0},
        },
        "trailing_stops": {"NILKAMAL": 2022.735, "SBIN": 1100.0},
        "orb_ranges": {"NILKAMAL": {"high": 2105.0}, "SBIN": {"high": 1120.0}},
        "closed_positions": [],
    }), encoding="utf-8")
    return p


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------
# THE PHANTOM GOES
# ---------------------------------------------------------------

def test_the_position_is_gone_from_every_book(state):
    """THE CASE. Three places remembered it and all three must forget."""
    removed = forget("NILKAMAL", state_path=state, backup=False)
    got = _read(state)
    assert "NILKAMAL" not in got["open_positions"]
    assert "NILKAMAL" not in got["trailing_stops"]
    assert "NILKAMAL" not in got["orb_ranges"]
    assert set(removed) == {"open_positions", "trailing_stops", "orb_ranges"}


def test_the_seat_is_released(state):
    """The whole point. It was holding one of three seats while the
    ranker refused good setups for want of one."""
    forget("NILKAMAL", state_path=state, backup=False)
    assert len(_read(state)["open_positions"]) == 1


def test_no_trade_is_invented(state):
    """exit_all would have written a fake close into the record he
    measures the bot against. This writes nothing."""
    before = _read(state)["closed_positions"]
    forget("NILKAMAL", state_path=state, backup=False)
    assert _read(state)["closed_positions"] == before == []


def test_a_real_position_is_untouched(state):
    """The control. A tool that clears the book is worse than the bug."""
    forget("NILKAMAL", state_path=state, backup=False)
    got = _read(state)
    assert got["open_positions"]["SBIN"]["qty"] == 500
    assert got["trailing_stops"]["SBIN"] == 1100.0
    assert got["orb_ranges"]["SBIN"]["high"] == 1120.0


# ---------------------------------------------------------------
# IT IS SAFE TO GET WRONG
# ---------------------------------------------------------------

def test_a_symbol_that_is_not_there_changes_nothing(state):
    before = state.read_text(encoding="utf-8")
    assert forget("RELIANCE", state_path=state, backup=False) == {}
    assert state.read_text(encoding="utf-8") == before


def test_case_does_not_matter(state):
    assert forget("nilkamal", state_path=state, backup=False)
    assert "NILKAMAL" not in _read(state)["open_positions"]


def test_it_backs_the_state_up_before_writing(state):
    forget("NILKAMAL", state_path=state, backup=True)
    backups = list(state.parent.glob("session_state.*.bak"))
    assert backups, "the previous book was overwritten with no copy"
    assert "NILKAMAL" in backups[0].read_text(encoding="utf-8")


def test_an_empty_symbol_is_refused(state):
    with pytest.raises(ValueError):
        forget("", state_path=state)


def test_a_missing_state_file_is_reported_not_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        forget("NILKAMAL", state_path=tmp_path / "nope.json")


def test_the_state_stays_valid_json(state):
    forget("NILKAMAL", state_path=state, backup=False)
    assert _read(state)["date"] == "2026-08-21"


def test_a_list_shaped_book_is_handled_too(tmp_path):
    """portfolio is a list of rows in some saves, a dict in others.
    Handling only one shape would silently half-forget."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"portfolio": [
        {"symbol": "NILKAMAL", "qty": 28}, {"symbol": "SBIN", "qty": 500}]}),
        encoding="utf-8")
    forget("NILKAMAL", state_path=p, backup=False)
    rows = _read(p)["portfolio"]
    assert [r["symbol"] for r in rows] == ["SBIN"]
