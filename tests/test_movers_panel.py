"""
Gainers and Losers: fifty a side, with every reason the bot has.

    "Shortlist what moved, and why -- ranked from here we will do as per
     my order (top 50 stocks on each side) ... everything will be
     integrated into this one table neatly"
                                        -- operator, 30 July 2026

WHY THE MERGE MATTERED
----------------------
There were two panels describing the same stocks differently:

  * Shortlist -- 25 rows, scored, with why-chips. It dropped anything
    under MIN_SCORE, so a stock up 14% with nothing filed behind it was
    not on it at all.
  * Top 50 Gainers & Losers -- 50 a side, and no reasons whatsoever.

So the complete list had no reasons and the reasoned list was not
complete. build_movers() is the left join that fixes it, and the
DIRECTION of that join is the whole point: the 50 movers are the spine,
reasons attach where they exist, and a mover with none still appears
with an em dash -- "if no data available simply --".
"""

from dashboard.state import DashboardState


class FakeFeed:
    """core/breakout_feed.attempt_for(symbol, direction)."""
    def __init__(self, table):
        self.table = table
        self.asked = []

    def attempt_for(self, symbol, direction):
        self.asked.append((symbol, direction))
        return self.table.get((symbol, direction))


class FakeEngine:
    open_positions = {}

    def __init__(self, feed=None):
        self.breakout_feed = feed


def _state(rows, shortlist_rows, feed=None):
    st = object.__new__(DashboardState)
    st.engine = FakeEngine(feed)
    st._compute_gl_rows = lambda: rows
    st._build_shortlist = lambda: {"rows": shortlist_rows, "thin": [],
                                   "scanned": len(rows), "built_at": "09:30:00"}
    return st


def _universe(n):
    """n risers and n fallers -- so 2n rows in total.

    Worth being explicit: with fewer than 100 rows the top-50 slices
    OVERLAP, and the same symbol legitimately appears in both tables.
    That is real behaviour on a thin universe, documented in
    _build_stock_gainers_losers(), not a bug -- so tests that want two
    disjoint tables have to ask for more than 50 a side.
    """
    rows = []
    for i in range(n):
        rows.append({"symbol": f"UP{i}", "sector": "X", "ltp": 100.0,
                     "change_pct": round(10.0 - i * 0.01, 2)})
        rows.append({"symbol": f"DN{i}", "sector": "X", "ltp": 100.0,
                     "change_pct": round(-10.0 + i * 0.01, 2)})
    return rows


def test_fifty_a_side_even_when_the_universe_is_far_bigger():
    out = _state(_universe(200), []).build_movers()
    assert len(out["gainers"]) == 50
    assert len(out["losers"]) == 50


def test_gainers_are_the_biggest_risers_and_losers_the_biggest_fallers():
    out = _state(_universe(60), []).build_movers()
    assert out["gainers"][0]["symbol"] == "UP0"
    assert out["losers"][0]["symbol"] == "DN0"
    gains = [r["change_pct"] for r in out["gainers"]]
    assert gains == sorted(gains, reverse=True)
    losses = [r["change_pct"] for r in out["losers"]]
    assert losses == sorted(losses)


def test_a_mover_with_no_reasons_still_appears():
    """THE bug the merge exists to fix. Under the old shortlist this row
    scored nothing, so it was simply not on the reasoned list."""
    rows = [{"symbol": "QUIET", "sector": "X", "ltp": 50.0, "change_pct": 14.0}]
    out = _state(rows, []).build_movers()
    row = out["gainers"][0]
    assert row["symbol"] == "QUIET"
    assert row["score"] is None, "no score invented where none was earned"
    assert row["why"] == [], "no reasons invented either"
    assert row["grade"] is None and row["veto"] == []


def test_reasons_are_joined_on_where_they_exist():
    rows = [{"symbol": "LOUD", "sector": "X", "ltp": 50.0, "change_pct": 9.0}]
    shortlist = [{"symbol": "LOUD", "score": 22.4, "grade": "STRONG",
                  "veto": ["ex-date"], "vol_ratio": 4.9,
                  "why": ["FILED RESULTS 13:51", "REPORTING TODAY"],
                  "news": {"headline": "x"}, "financials": {"period": "Q1"}}]
    row = _state(rows, shortlist).build_movers()["gainers"][0]
    assert row["score"] == 22.4
    assert row["grade"] == "STRONG"
    assert row["veto"] == ["ex-date"]
    assert row["why"] == ["FILED RESULTS 13:51", "REPORTING TODAY"]
    assert row["financials"] == {"period": "Q1"}
    # and the mover's own columns survive the join
    assert row["ltp"] == 50.0 and row["change_pct"] == 9.0


def test_each_side_asks_the_feed_about_its_own_direction():
    """A gainer's attempts are LONG attempts. Asking about SHORT would
    report a level the stock is not testing -- and would silently read
    0 for every riser on a quiet day, which looks like data."""
    feed = FakeFeed({("UP0", "LONG"): 3, ("DN0", "SHORT"): 2,
                     ("UP0", "SHORT"): 99, ("DN0", "LONG"): 99})
    # 60 a side, so the two top-50 slices do not overlap and UP0 is only
    # ever asked about as a gainer.
    out = _state(_universe(60), [], feed).build_movers()
    assert out["gainers"][0]["symbol"] == "UP0"
    assert out["gainers"][0]["attempts"] == 3, "a gainer must be asked about LONG"
    assert out["losers"][0]["symbol"] == "DN0"
    assert out["losers"][0]["attempts"] == 2, "a loser must be asked about SHORT"
    assert ("UP0", "LONG") in feed.asked
    assert ("UP0", "SHORT") not in feed.asked, (
        "the 99 is a trap: reading the wrong side reports a level the "
        "stock is not testing")


def test_direction_is_stamped_so_the_row_picks_its_own_button():
    out = _state(_universe(2), []).build_movers()
    assert {r["direction"] for r in out["gainers"]} == {"LONG"}
    assert {r["direction"] for r in out["losers"]} == {"SHORT"}


def test_no_breakout_feed_means_no_attempts_not_a_crash():
    out = _state(_universe(2), [], feed=None).build_movers()
    assert out["gainers"], "the table must still be built"
    assert all(r["attempts"] is None for r in out["gainers"])


def test_a_broken_feed_costs_the_column_not_the_panel():
    class Angry:
        def attempt_for(self, *a):
            raise RuntimeError("feed died")
    out = _state(_universe(2), [], Angry()).build_movers()
    assert len(out["gainers"]) == 4      # 2 risers + 2 fallers, thin universe
    assert out["gainers"][0]["attempts"] is None


def test_a_broken_shortlist_costs_the_reasons_not_the_movers():
    """The movers are the spine. If the scorer falls over, the operator
    must still see what moved."""
    st = _state(_universe(3), [])
    def boom():
        raise RuntimeError("scorer died")
    st._build_shortlist = boom
    out = st.build_movers()
    assert len(out["gainers"]) == 6      # 3 risers + 3 fallers, thin universe
    assert out["gainers"][0]["symbol"] == "UP0"
    assert out["gainers"][0]["score"] is None


def test_a_broken_universe_returns_empty_tables_not_an_exception():
    """A panel that raises takes the whole snapshot down with it."""
    st = _state([], [])
    def boom():
        raise RuntimeError("no market data")
    st._compute_gl_rows = boom
    out = st.build_movers()
    assert out["gainers"] == [] and out["losers"] == []


def test_rows_are_copies_so_the_two_tables_cannot_corrupt_each_other():
    """On a small universe the same symbol can legitimately land in both
    tables. Sharing the dict would make one table's s_no overwrite the
    other's -- the same bug _build_stock_gainers_losers() documents."""
    rows = [{"symbol": "ONLY", "sector": "X", "ltp": 1.0, "change_pct": 5.0},
            {"symbol": "OTHER", "sector": "X", "ltp": 1.0, "change_pct": 1.0}]
    out = _state(rows, []).build_movers()
    assert out["gainers"][0]["symbol"] == "ONLY"
    assert out["losers"][-1]["symbol"] == "ONLY"
    assert out["gainers"][0]["s_no"] == 1
    assert out["losers"][-1]["s_no"] == 2
    assert out["gainers"][0] is not out["losers"][-1]


def test_serial_numbers_run_from_one_in_each_table():
    out = _state(_universe(5), []).build_movers()          # 10 rows total
    assert [r["s_no"] for r in out["gainers"]] == list(range(1, 11))
    assert [r["s_no"] for r in out["losers"]] == list(range(1, 11))
