"""The rebuild spent 36 seconds looking for 300 rows.

    "fix the board rebuild speed next. why it is taking that long &
     does the trade is taking on those delayed price?"
                                   -- the operator, 4 September 2026

build_ranked() enriches every row on the board with per-symbol
lookups, and two of them -- the flow panel and the shape panel -- each
read that stock's minutes out of data/order_flow.db through
order_flow.session_series().

MEASURED, 40 real symbols from 4 September:

    session_series   181.93 ms a symbol   ->   18.6 s for a 100-row board
    and it is called twice a row          ->   36.4 s

WHY. The query is

    WHERE date = ? AND symbol = ? ORDER BY minute

and SQLite answered it with the UNIQUE(date, minute, symbol)
auto-index, which can only seek on `date`. Every call scanned all
~460,000 rows of that day to find the ~320 for one stock. The planner
chose it because its second column is `minute`, satisfying the ORDER
BY -- it scanned half a million rows to avoid sorting three hundred.

idx_flow_day_symbol(date, symbol) already existed and did not help:
it seeks correctly but leaves a sort behind, so the planner kept
preferring the auto-index. An index on (date, symbol, minute) seeks
AND orders, so it wins outright.

    one call    48.41 ms  ->  0.66 ms
    one symbol 181.93 ms  ->  6.04 ms
    100 rows      36.4 s  ->   1.2 s

This is a REBUILD cost, not an entry cost. Entries have priced
themselves off the tick since 2 September -- see price_now() and
tests/test_two_lanes.py. What a slow rebuild delays is a stock
APPEARING on the board at all, which is what cost Rs 77,779 across
nine late trades on 4 September.
"""

import sqlite3

from core.order_flow import _SCHEMA


def _db(tmp_path):
    path = str(tmp_path / "flow.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn, path


def test_the_schema_builds_the_index_that_seeks_and_orders(tmp_path):
    conn, _ = _db(tmp_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_flow_day_symbol_minute" in names


def test_the_day_is_no_longer_scanned_to_find_one_stock(tmp_path):
    """THE regression. If the planner goes back to the auto-index,
    every board rebuild pays 36 seconds again and this fails."""
    conn, _ = _db(tmp_path)
    plan = " ".join(str(r[-1]) for r in conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT minute, delta, ltp, ticks, book_ticks FROM flow_minutes "
        "WHERE date = '2026-09-04' AND symbol = 'RESPONIND' "
        "ORDER BY minute"))
    assert "symbol=?" in plan.replace(" ", "").replace("AND", " AND ") \
        or "symbol=?" in plan.replace(" ", ""), (
        f"the query is not seeking on symbol -- it is scanning the "
        f"whole day again. Plan: {plan}")
    assert "SCAN" not in plan, f"a full scan is back. Plan: {plan}"


def test_session_series_still_returns_the_right_minutes(tmp_path):
    """An index that changes the answer is not an optimisation."""
    from core.order_flow import session_series
    conn, path = _db(tmp_path)
    rows = [("2026-09-04", m, s, 1, 1, 0.0, 0.0, 0.0, 0.0, 0.0,
             10.0, None, None, None, 100.0, 100.0)
            for s in ("RESPONIND", "OTHER")
            for m in ("09:16", "09:15", "09:17")]
    conn.executemany(
        "INSERT INTO flow_minutes (date, minute, symbol, ticks, book_ticks, "
        "up_qty, down_qty, flat_qty, delta, ltq_sum, vol_delta, book_buy, "
        "book_sell, skew_pct, ltp, atp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows)
    conn.commit()
    got = session_series("RESPONIND", date="2026-09-04", db_path=path)
    assert [r["minute"] for r in got] == ["09:15", "09:16", "09:17"], (
        "the minutes came back out of order or from the wrong symbol")
