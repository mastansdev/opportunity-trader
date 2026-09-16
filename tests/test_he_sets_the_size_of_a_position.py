"""---- ONE NUMBER, AND HE SETS IT. 16 September 2026. ----

    "reduce per position to 25000 so i get 3 seats on my current capital
     & why do not u gave option to select capital allocation on
     dashboard."                                    -- the operator

His Rs 75,463 at Dhan bought ONE seat at Rs 50,000 a position. The
figure lived in two constants in two source files. core/position_size.py
is the one place now, the dashboard writes it, and every sizing path
reads it.
"""

import json

import pytest

from core import capital, mtf_margin, position_size


@pytest.fixture(autouse=True)
def _own_file(tmp_path, monkeypatch):
    monkeypatch.setattr(position_size, "PATH", str(tmp_path / "size.json"))
    monkeypatch.setattr(position_size, "_cache",
                        {"value": None, "mtime": None})
    yield


def test_his_capital_buys_three_seats_at_25k():
    ok, _ = position_size.set_per_position_rs(25_000)
    assert ok
    got = capital.slots(75_462.66, held=0)
    assert got["slots"] == 3


def test_fifty_thousand_gave_him_one():
    position_size.set_per_position_rs(50_000)
    assert capital.slots(75_462.66, held=0)["slots"] == 1


def test_the_order_size_follows_the_same_number():
    """Seats and share count must never disagree -- they were two
    constants before."""
    position_size.set_per_position_rs(25_000)
    # Rs 25,000 of margin at 100 rupees a share, 25% margin -> 1,000 shares
    assert mtf_margin.shares_for(100.0, 0.25) == 1_000
    position_size.set_per_position_rs(50_000)
    assert mtf_margin.shares_for(100.0, 0.25) == 2_000


def test_a_typed_mistake_is_refused():
    for bad in (0, -1, 100, 5_00_000, "abc", None):
        ok, why = position_size.set_per_position_rs(bad)
        assert not ok and why


def test_it_survives_a_restart():
    position_size.set_per_position_rs(25_000)
    with open(position_size.PATH, encoding="utf-8") as handle:
        assert json.load(handle)["per_position_rs"] == 25_000
    position_size._cache.update({"value": None, "mtime": None})
    assert position_size.per_position_rs() == 25_000


def test_nothing_set_falls_back_to_config():
    from config import MTF_MARGIN_PER_POSITION_RS
    assert position_size.per_position_rs() == float(MTF_MARGIN_PER_POSITION_RS)


def test_a_corrupt_file_does_not_stop_trading():
    with open(position_size.PATH, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert position_size.per_position_rs() > 0
