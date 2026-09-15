"""---- ONE SEAT AT A TIME, TO THE BEST MOVER. 15 September 2026. ----

    "why can't bot take the best moving stock instead of racing to fill
     with shit stocks with shit reasons"            -- the operator

15 Sep: all ten seats went by 09:18 to the first names on the board,
while the day's #1 (EMUDHRA, score 74) was first seen at 09:18 and #5
(FSL) at 09:21. The loop gave a seat to every row that passed, in the
same second.
"""

from datetime import datetime, timedelta

import pytest

from core import auto_entry
from tests.test_a_broken_check_refuses_the_trade import _Engine


@pytest.fixture(autouse=True)
def _discipline_on(monkeypatch):
    import config
    monkeypatch.setattr(config, "ENTRY_NOT_BEFORE", None)
    monkeypatch.setattr(config, "ENTRY_ONLY_ALIVE", True)
    monkeypatch.setattr(config, "ENTRY_MIN_GAP_SECONDS", 60)


def _row(symbol, state="alive", recent=1.0):
    return {"symbol": symbol, "action": "BUY", "ltp": 100.0,
            "day_high": 100.0, "state": state, "recent_pct": recent,
            "plan": {"ok": True, "qty": 10, "stop": 95.0, "target": 110.0},
            "why": "a reason"}


def _take(engine, rows, now):
    sent = []
    auto_entry.take(rows, engine, now=now, security_id_of=lambda s: "1",
                    held=set(engine.open_positions), max_positions=10,
                    alert=None,
                    enter=lambda *a, **k: (sent.append(a[0]),
                                           engine.open_positions.__setitem__(a[0], {})))
    return sent


def test_there_is_no_fixed_clock_start():
    """15 Sep evening: he never set 09:20 -- "the seat filling must happen
    after all checks not a race". The checks hold the seat, not a clock."""
    import pathlib
    import re
    text = (pathlib.Path(__file__).resolve().parents[1] / "config.py").read_text(
        encoding="utf-8")
    assert re.search(r"^ENTRY_NOT_BEFORE = None\b", text, re.M)


def test_ten_candidates_do_not_take_ten_seats_in_one_second():
    """THE BUG: seven seats went in the same second at 09:16:33."""
    engine = _Engine()
    rows = [_row(s) for s in ("KEC", "MPHASIS", "SWSOLAR", "TMPV",
                              "AFCONS", "BSOFT", "RAYMONDREL")]
    sent = _take(engine, rows, datetime(2026, 9, 15, 9, 20, 0))
    assert len(sent) == 1


def test_the_seat_goes_to_the_one_moving_most():
    engine = _Engine()
    rows = [_row("SLOW", recent=0.2), _row("EMUDHRA", recent=2.5)]
    assert _take(engine, rows, datetime(2026, 9, 15, 9, 21)) == ["EMUDHRA"]


def test_a_stock_not_moving_now_gets_no_seat():
    engine = _Engine()
    rows = [_row("FADED", state="fading"), _row("UNKNOWN", state=None)]
    assert _take(engine, rows, datetime(2026, 9, 15, 10, 0)) == []


def test_the_next_seat_waits_for_a_fresh_ranking_then_goes():
    engine = _Engine()
    t = datetime(2026, 9, 15, 9, 21)
    assert _take(engine, [_row("EMUDHRA")], t) == ["EMUDHRA"]
    assert _take(engine, [_row("FSL")], t + timedelta(seconds=30)) == []
    assert _take(engine, [_row("FSL")], t + timedelta(seconds=61)) == ["FSL"]
