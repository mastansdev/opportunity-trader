"""Two minute stores, and nobody had ever compared them.

    "after trading closed main.py is duplicating the min candle &
     creating mess inside bot"        -- operator, 29 August 2026

He was half right, and the half he was right about is the worse half.

NOTHING IS DUPLICATED. data/history_candles.db carries
CONSTRAINT uq_candle UNIQUE (date, symbol, minute), and across all
32.6 million rows there are zero extra rows.

BUT THE SAME MINUTE IS HELD TWICE, WITH DIFFERENT NUMBERS:

    history_candles.db    fetched from Dhan -- read by core/atr.py,
                          core/liquidity.py, core/volume_pace.py,
                          which is the LIVE decision path
    backtest_candles.db   recorded from this machine's own ticks --
                          read by core/session_replay.py and the tools

Measured on 27 August across the 156,125 minutes both hold:

    close price   median 0.000%   p90 0.02%    worst 1.5%
    volume        median 10.4%    p90 78.3%    worst 29,300%

Prices agree. VOLUME DOES NOT, and volume is a hard gate -- a stock
needs 2.5x its own normal to be a candidate at all. So a replay does
not reproduce the volume decisions the live bot made, and until this
tool existed there was no way to know that.

A gap is not corruption. It is a minute this machine did not see the
whole of, and the recorded volume carries what it missed into the
minute after. That is a FEED GAP, and worth knowing on the morning it
happens rather than never.
"""

import sqlite3

import pytest

from tools import candle_agreement


def _store(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE candles (date TEXT, symbol TEXT, minute TEXT,"
                 " o REAL, h REAL, l REAL, c REAL, v REAL)")
    conn.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


@pytest.fixture
def stores(tmp_path):
    """Two stores that agree on price and disagree on volume -- which
    is the shape the real ones are in."""
    left = _store(str(tmp_path / "h.db"), [
        ("2026-08-27", "RELIANCE", "2026-08-27T09:15:00", 1305.0, 1305.7,
         1302.3, 1305.5, 87208.0),
        ("2026-08-27", "RELIANCE", "2026-08-27T09:16:00", 1305.5, 1308.4,
         1305.5, 1307.6, 139462.0),
        ("2026-08-27", "TCS", "2026-08-27T09:15:00", 3000.0, 3002.0,
         2999.0, 3001.0, 5000.0),
    ])
    # note: no seconds on the minute, as the recorder writes it
    right = _store(str(tmp_path / "b.db"), [
        ("2026-08-27", "RELIANCE", "2026-08-27T09:15", 1304.7, 1305.6,
         1303.1, 1305.2, 97407.0),
        # a gap wide enough to clear VOLUME_GAP_PCT -- the shape of
        # the real ones, where the recorder carries missed ticks into
        # the following minute
        ("2026-08-27", "RELIANCE", "2026-08-27T09:16", 1305.5, 1308.4,
         1305.5, 1307.7, 320000.0),
    ])
    return left, right


def test_the_minute_matches_across_two_different_formats(stores):
    """One store writes seconds and the other does not. Comparing the
    raw strings would report every single minute as missing."""
    got = candle_agreement.compare("2026-08-27", *stores)
    assert got["shared"] == 2, got
    assert got["history_only"] == 1      # TCS, which the recorder missed


def test_it_reports_price_and_volume_separately(stores):
    """The whole finding is that one agrees and the other does not.
    Rolling them into one number would have hidden it."""
    got = candle_agreement.compare("2026-08-27", *stores)
    assert got["price"]["median"] < 0.1, got["price"]
    assert got["volume"]["median"] > 0.3, got["volume"]


def test_a_wide_volume_gap_is_named_not_just_counted(stores):
    """A number nobody can act on is a number nobody looks at. The
    stock and the minute are what make it actionable."""
    got = candle_agreement.compare("2026-08-27", *stores)
    assert got["loud"], "a 130% volume gap on RELIANCE was not surfaced"
    gap, symbol, minute, ours, theirs = got["loud"][0]
    assert symbol == "RELIANCE"
    assert minute.endswith("09:16")
    assert gap > candle_agreement.VOLUME_GAP_PCT
    # the 11.7% gap on 09:15 is real but under the threshold -- naming
    # every small difference would bury the ones that matter
    assert len(got["loud"]) == 1


def test_the_threshold_is_tied_to_the_gate_it_feeds():
    """core/rules.MIN_VOLUME_RATIO is 2.5. A reading a quarter out can
    move a stock across that, which is why the threshold is 25% and
    not a round number somebody liked."""
    from core.rules import MIN_VOLUME_RATIO

    assert MIN_VOLUME_RATIO > 1
    assert 10.0 <= candle_agreement.VOLUME_GAP_PCT <= 50.0


def test_a_missing_store_is_not_an_error(tmp_path):
    """A machine that has never recorded a session has nothing to
    compare, and that is a fact, not a failure."""
    assert candle_agreement._open(str(tmp_path / "nope.db")) is None
    got = candle_agreement.compare("2026-08-27", None, None)
    assert got["shared"] == 0
    assert got["price"] == {} and got["volume"] == {}


def test_it_never_raises_on_a_day_with_nothing_in_it(stores):
    got = candle_agreement.compare("1999-01-01", *stores)
    assert got["shared"] == 0
    assert got["loud"] == []


def test_the_live_path_reads_the_exchange_store_not_the_recording():
    """The thing that makes this a diagnostic rather than a bug.

    If ATR, liquidity or volume pace ever start reading the recorded
    store, the bot's decisions inherit this machine's feed gaps -- and
    the volume gate is the one that would move first.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("core/atr.py", "core/liquidity.py", "core/volume_pace.py"):
        text = (root / name).read_text(encoding="utf-8", errors="ignore")
        assert "backtest_candles" not in text, (
            f"{name} reads the recorded store -- live decisions would "
            f"inherit this machine's feed gaps")
