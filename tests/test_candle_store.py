"""
Tests for backtest/candle_store.py -- the replay corpus.

This file exists because the store had NO tests, despite sitting on the
live path (core/candle_recorder.py writes to it every closed candle of
every session). The 2026-07-26 add_many() rewrite is the trigger: it
went from one execute() per row to chunked executemany, and the thing
that must not break is dedup on (date, symbol, minute).
"""

import pytest

from backtest.candle_store import CandleStore


@pytest.fixture
def store(tmp_path):
    return CandleStore(url=f"sqlite:///{tmp_path}/candles.db")


def row(symbol="PARAS", minute="2026-07-24T09:16:00", o=100.0, h=101.0,
        l=99.0, c=100.5, v=1000.0, date="2026-07-24"):
    return dict(date=date, symbol=symbol, minute=minute, o=o, h=h, l=l,
                c=c, v=v)


# ----------------------------------------------------------
# add() -- single row
# ----------------------------------------------------------

def test_add_then_read_back(store):
    store.add(**row())
    got = store.candles_for("2026-07-24", "PARAS")
    assert len(got) == 1
    assert got[0]["o"] == 100.0
    assert got[0]["v"] == 1000.0


def test_add_is_idempotent_on_the_same_minute(store):
    """A restart re-logging the same bar must not create a duplicate."""
    store.add(**row())
    store.add(**row(c=999.0))
    got = store.candles_for("2026-07-24", "PARAS")
    assert len(got) == 1
    assert got[0]["c"] == 999.0          # last write wins


def test_volume_may_be_absent(store):
    store.add(date="2026-07-24", symbol="X", minute="2026-07-24T09:16:00",
              o=1, h=1, l=1, c=1)
    assert store.candles_for("2026-07-24", "X")[0]["v"] is None


# ----------------------------------------------------------
# add_many() -- the bulk path the historical pull depends on
# ----------------------------------------------------------

def test_add_many_inserts_every_row(store):
    rows = [row(symbol="A", minute=f"2026-07-24T09:{m:02d}:00")
            for m in range(15, 45)]
    assert store.add_many(rows) == 30
    assert store.count("2026-07-24") == 30


def test_add_many_is_empty_safe(store):
    assert store.add_many([]) == 0
    assert store.add_many(iter([])) == 0


def test_add_many_accepts_a_generator(store):
    assert store.add_many(row(minute=f"2026-07-24T10:{m:02d}:00")
                          for m in range(5)) == 5


def test_add_many_dedups_within_one_batch(store):
    """Two rows for the same (date, symbol, minute) in ONE call -- the
    last one must win, and only one row may survive."""
    store.add_many([row(c=1.0), row(c=2.0)])
    got = store.candles_for("2026-07-24", "PARAS")
    assert len(got) == 1
    assert got[0]["c"] == 2.0


def test_add_many_dedups_across_calls(store):
    """Re-running the historical fetcher over an overlapping window must
    not duplicate a single bar."""
    store.add_many([row(minute=f"2026-07-24T09:{m:02d}:00")
                    for m in range(15, 30)])
    store.add_many([row(minute=f"2026-07-24T09:{m:02d}:00", c=7.0)
                    for m in range(20, 35)])
    got = store.candles_for("2026-07-24", "PARAS")
    assert len(got) == 20                       # 09:15..09:34, no dupes
    updated = [g for g in got if g["c"] == 7.0]
    assert len(updated) == 15                   # the overlap was updated


def test_add_many_normalises_missing_keys(store):
    """A row without volume must not blow up a batch that has it -- one
    compiled statement is reused across the chunk, so every row is
    padded to the full column set first."""
    store.add_many([
        row(symbol="WITHVOL"),
        dict(date="2026-07-24", symbol="NOVOL",
             minute="2026-07-24T09:16:00", o=1, h=1, l=1, c=1),
    ])
    assert store.candles_for("2026-07-24", "WITHVOL")[0]["v"] == 1000.0
    assert store.candles_for("2026-07-24", "NOVOL")[0]["v"] is None


def test_add_many_spans_multiple_chunks(store):
    """chunk boundary must not drop or duplicate rows."""
    rows = [row(symbol="A", date="2026-07-24",
                minute=f"2026-07-24T{9 + i // 60:02d}:{i % 60:02d}:00")
            for i in range(250)]
    assert store.add_many(rows, chunk=37) == 250
    assert store.count("2026-07-24") == 250


def test_add_many_chunk_size_zero_does_not_hang(store):
    assert store.add_many([row()], chunk=0) == 1


# ----------------------------------------------------------
# reads
# ----------------------------------------------------------

def test_dates_and_symbols_are_distinct_and_sorted(store):
    store.add_many([
        row(date="2026-07-24", symbol="B"),
        row(date="2026-07-24", symbol="A"),
        row(date="2026-07-23", symbol="A"),
    ])
    assert store.dates() == ["2026-07-23", "2026-07-24"]
    assert store.symbols_for("2026-07-24") == ["A", "B"]


def test_candles_for_walks_chronologically(store):
    store.add_many([
        row(symbol="B", minute="2026-07-24T09:16:00"),
        row(symbol="A", minute="2026-07-24T09:17:00"),
        row(symbol="A", minute="2026-07-24T09:16:00"),
    ])
    got = store.candles_for("2026-07-24")
    assert [(g["minute"][-8:], g["symbol"]) for g in got] == [
        ("09:16:00", "A"), ("09:16:00", "B"), ("09:17:00", "A"),
    ]


def test_count_and_clear_date(store):
    store.add_many([row(date="2026-07-23"), row(date="2026-07-24")])
    assert store.count() == 2
    store.clear_date("2026-07-23")
    assert store.count() == 1
    assert store.dates() == ["2026-07-24"]
