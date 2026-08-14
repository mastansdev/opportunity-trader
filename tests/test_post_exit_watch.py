"""
Tests for the post-exit watcher -- core/engine.py's _watch_after_exit()
and dashboard/state.py's _after_exit().

    "ltp is not place in closed positions so can't identify the move
     after exit in stocks - this requested by me as wanted but not
     done - pls note"              -- operator, 29 July 2026

The bot forgot a stock the instant it sold it. On 29 July it exited
KAYNES at 3,398 and KAYNES reached 3,684.70; PCBL was sold at 331.05
and reached 373.75. The operator found every one of those on his
broker screen, because the bot had no idea and the dashboard had
nothing to show.

THE RULE THIS IS HELD TO: observation only. It records where a price
went after we left. It must never re-enter, widen a stop, or influence
any decision -- the moment "it went up after we sold" becomes an input,
the bot is trading its own regret.
"""

from datetime import datetime

from core.engine import Engine


def _t(hour, minute, second=0):
    return datetime(2026, 7, 29, hour, minute, second)


class _Md:
    def __init__(self, prices=None):
        self.prices = prices or {}

    def get_latest_price(self, symbol):
        return self.prices.get(symbol)


# ---------------------------------------------------------------
# the engine side
# ---------------------------------------------------------------

def test_a_sold_stock_is_followed_for_the_rest_of_the_day():
    engine = Engine()
    engine._watch_after_exit("KAYNES", 3398.0, _t(10, 14))

    for price in (3400.0, 3520.0, 3684.70, 3660.20):
        engine._update_after_exit("KAYNES", price, _t(13, 4))

    watch = engine.get_post_exit("KAYNES")
    assert watch["exit_price"] == 3398.0
    assert watch["peak"] == 3684.70
    assert watch["last"] == 3660.20


def test_the_trough_is_kept_too_because_a_short_cares_about_the_low():
    engine = Engine()
    engine._watch_after_exit("X", 100.0, _t(10, 0))
    for price in (99.0, 94.0, 97.0):
        engine._update_after_exit("X", price, _t(11, 0))
    assert engine.get_post_exit("X")["trough"] == 94.0
    assert engine.get_post_exit("X")["peak"] == 100.0


def test_the_time_of_the_peak_is_recorded():
    engine = Engine()
    engine._watch_after_exit("KAYNES", 3398.0, _t(10, 14))
    engine._update_after_exit("KAYNES", 3684.70, _t(13, 4))
    engine._update_after_exit("KAYNES", 3660.20, _t(15, 20))
    assert engine.get_post_exit("KAYNES")["peak_at"] == _t(13, 4)


def test_a_second_exit_restarts_the_clock():
    """Now that one-trade-per-day is off a stock can be traded twice.
    The question is always "since the LAST exit", not since the first."""
    engine = Engine()
    engine._watch_after_exit("KAYNES", 3398.0, _t(10, 14))
    engine._update_after_exit("KAYNES", 3684.70, _t(13, 4))
    engine._watch_after_exit("KAYNES", 3600.0, _t(14, 0))
    watch = engine.get_post_exit("KAYNES")
    assert watch["exit_price"] == 3600.0
    assert watch["peak"] == 3600.0        # not the old 3,684.70


def test_a_stock_never_sold_is_not_watched():
    assert Engine().get_post_exit("INFY") is None


def test_updating_an_unwatched_symbol_costs_nothing_and_raises_nothing():
    engine = Engine()
    engine._update_after_exit("INFY", 1500.0, _t(10, 0))
    assert engine.post_exit == {}


def test_a_junk_exit_price_is_refused_rather_than_stored():
    engine = Engine()
    engine._watch_after_exit("X", None, _t(10, 0))
    engine._watch_after_exit("Y", "not a number", _t(10, 0))
    assert engine.get_post_exit("X") is None
    assert engine.get_post_exit("Y") is None


def test_the_watcher_never_reopens_a_position():
    """The whole safety of this feature. It observes; it must not act."""
    engine = Engine()
    engine._watch_after_exit("KAYNES", 3398.0, _t(10, 14))
    engine._update_after_exit("KAYNES", 4000.0, _t(11, 0))
    assert "KAYNES" not in engine.open_positions


# ---------------------------------------------------------------
# the dashboard side
# ---------------------------------------------------------------

def _state(engine, prices=None):
    from dashboard.state import DashboardState

    class _Loader:
        def all_symbols(self):
            return []

        def get_by_symbol(self, symbol):
            return {"SECTOR": "IT"}

    return DashboardState(engine, _Md(prices), _Loader())


KAYNES = {"symbol": "KAYNES", "direction": "LONG", "qty": 59,
          "entry_price": 3338.0, "exit_price": 3398.0,
          "entry_time": _t(9, 32), "exit_time": _t(10, 14),
          "exit_reason": "TRAILING_STOP", "pnl": 3540.0,
          "initial_stop": None}


def test_the_closed_row_carries_the_move_after_exit():
    engine = Engine()
    engine._watch_after_exit("KAYNES", 3398.0, _t(10, 14))
    engine._update_after_exit("KAYNES", 3684.70, _t(13, 4))
    engine._update_after_exit("KAYNES", 3660.20, _t(15, 20))

    row = _state(engine, {"KAYNES": 3660.20})._after_exit(KAYNES)
    assert row["ltp"] == 3660.20
    assert row["since_exit_pct"] == 7.72      # 3398 -> 3660.20
    assert row["peak_since_exit"] == 3684.70
    assert row["peak_pct"] == 8.44            # the one he had to find himself
    assert row["peak_at"] == "13:04:00"


def test_a_short_reports_the_LOW_it_reached_not_the_high():
    """Showing the high on a short would read as "it went against you"
    when it did the opposite."""
    engine = Engine()
    engine._watch_after_exit("X", 100.0, _t(10, 0))
    engine._update_after_exit("X", 94.0, _t(11, 0))
    engine._update_after_exit("X", 108.0, _t(12, 0))

    row = _state(engine, {"X": 108.0})._after_exit(
        dict(KAYNES, symbol="X", direction="SHORT", exit_price=100.0))
    assert row["peak_since_exit"] == 94.0
    assert row["peak_pct"] == -6.0


def test_no_price_anywhere_reads_as_unknown_not_as_zero_move():
    """A dash means "we do not know". A 0.0% would be a claim that the
    stock did not move, which is a different and false statement."""
    row = _state(Engine())._after_exit(KAYNES)
    assert row["ltp"] is None
    assert row["since_exit_pct"] is None
    assert row["peak_pct"] is None


def test_it_reports_the_move_and_passes_no_judgement():
    """No "should have held" flag, no missed-profit total. A number the
    bot could not have known at the time does not belong in a
    scorecard -- what it means is the operator's call."""
    engine = Engine()
    engine._watch_after_exit("KAYNES", 3398.0, _t(10, 14))
    engine._update_after_exit("KAYNES", 3684.70, _t(13, 4))
    row = _state(engine, {"KAYNES": 3684.70})._after_exit(KAYNES)
    for banned in ("missed", "should", "regret", "mistake", "lost_profit"):
        assert not any(banned in key for key in row)


# ---------------------------------------------------------------
# QTY -- reported blank twice, and the key was simply not there
# ---------------------------------------------------------------

def test_a_closed_row_carries_its_quantity():
    """"qty not updated in closed position" -- 29 July, and the second
    time he reported it. The key was never in the dict at all, so the
    column had nothing to read. It is used to compute pnl and charges
    a few lines later, so the number was there the whole time."""
    engine = Engine()
    engine.closed_positions.append(dict(KAYNES))
    rows = _state(engine)._build_closed_positions(engine.closed_positions)
    assert rows[0]["qty"] == 59


def test_every_closed_row_has_the_columns_the_page_reads():
    """The page reads these by name. A missing key renders as blank
    with no error anywhere -- exactly how qty stayed invisible."""
    engine = Engine()
    engine.closed_positions.append(dict(KAYNES))
    row = _state(engine)._build_closed_positions(engine.closed_positions)[0]
    for column in ("symbol", "qty", "entry_price", "exit_price", "pnl",
                   "exit_reason", "ltp", "since_exit_pct", "peak_pct"):
        assert column in row, f"the page reads {column} and it is not there"
