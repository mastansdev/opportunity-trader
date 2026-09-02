"""---- I WROTE THE PRODUCER AND NOT THE KEY. 3 September 2026. ----

The tick-feed backfill in dashboard/state.py exists so a stock the
websocket can see is not lost when the REST quote call comes back
short. It wrote the previous close under the key "close". Every
consumer of that snapshot reads "prev_close" -- core/circuit_monitor
has used that name since the day it was written.

So every feed-backfilled row was skipped by _compute_gl_rows as
no_prev_close, and the backfill produced ZERO usable rows from the
day it was added.

It hid because it only runs when REST is short, and REST was mostly
fine. On the night of 2 September it was not, and the log said it in
one line:

    WARNING: [GL] 1328 symbols in the snapshot but ZERO rows
    produced. Skipped: {'no_prev_close': 1328}

An empty board is no trades. The backfill exists for exactly the
moment REST is degraded, which is the one moment it was guaranteed
to fail.

This is the same fault as the `os` NameError, the `adv` shadow and
the shortlist-versus-ranked key: I verify the layer I changed and not
the layer that consumes it. The test below reads the SOURCE, because
the failure is a key name -- a mock would let me spell it wrong twice
and pass.
"""

import ast
import os

STATE = os.path.join("dashboard", "state.py")


def _source():
    with open(STATE, encoding="utf-8") as handle:
        return handle.read()


def test_the_backfill_writes_the_key_the_readers_read():
    """prev_close, not close. The whole bug in one assertion."""
    body = _source()
    start = body.index("Could not backfill from the feed")
    block = body[max(0, start - 2000):start]
    assert '"prev_close": seen.get("close")' in block, (
        "the feed backfill does not write prev_close -- every row it "
        "adds will be skipped as no_prev_close, which is the entire "
        "point of the backfill failing silently")


def test_the_backfill_row_matches_the_rest_row():
    """Nothing downstream should have to know where a row came from.
    core/circuit_monitor._row_from_quote() is the shape of truth."""
    with open(os.path.join("core", "circuit_monitor.py"),
              encoding="utf-8") as handle:
        monitor = handle.read()
    for key in ("last_price", "open", "high", "low", "prev_close", "volume"):
        assert f'"{key}"' in monitor, key
        assert f'"{key}"' in _source(), (
            f"the feed backfill does not carry {key}, which the REST "
            f"row does -- the two shapes must not diverge")


def test_the_reader_still_reads_prev_close():
    """If _compute_gl_rows ever switches key, this file is the place
    that finds out -- not a live morning with an empty board."""
    body = _source()
    assert 'prev_close = quote.get("prev_close")' in body, (
        "the gainers/losers builder no longer reads prev_close; the "
        "backfill above must be changed with it")


def test_the_skip_counters_are_still_reported():
    """The counter is what caught this. 1,328 symbols in and zero out
    is invisible unless something says WHICH exclusion emptied it."""
    body = _source()
    for counter in ("no_quote", "no_prev_close", "no_price"):
        assert f'"{counter}"' in body, counter


def test_state_py_still_parses():
    """A syntax error here takes the whole snapshot with it."""
    ast.parse(_source())
