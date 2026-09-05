"""A free seat is not a queue ticket for the stock that led an hour ago.

    "whenever a free seat is available that is not meant to fill any
     eligible candidate at 09:30 to fill at 12:45 time (bot can check
     the liveness = whether buyers are still pushing highs or dried up
     & also when ever free seat available; bot needs to search for the
     best candidate right that time not 1 hour back best candidate)"
                                   -- the operator, 5 September 2026

He was right, and the code did exactly what he described. take()
sorted by volume_x and score -- both read off the board, both
describing a move that had already happened -- and only then walked
the list re-checking liveness row by row. Liveness was a FILTER; the
stale ratio was the SORT. A stock surging this second but ranked
eighth by cumulative volume got the seat only if the seven above it
were all dead.

WHAT IT COST, 4 September, from his own book:

    the book filled 10 of 10 by 09:16:38 -- the day's whole capital
    in 83 seconds

    first 83 seconds   11 trades   8 won   3 lost   +Rs 13,157
    everything after   16 trades   6 won  10 lost   -Rs  1,363

RESPONIND ignited at 10:07 and was bought at 13:26, 48 paise below the
top of its whole move, for -Rs 4,833. Replayed at the ignition:
+Rs 8,170. The stock was right and the hour was wrong.

Nothing about liveness itself changed -- core/ranker.liveness() still
decides alive/fading/None on the same three readings. What changed is
that every row is re-priced off the tick BEFORE the sort, so the
ordering can see the live reading instead of ranking on the board and
filtering afterwards.
"""

import pytest

from core.auto_entry import take


class _Engine:
    """Only what take() reaches for."""
    alert_only = False
    open_positions = {}
    signal_journal = None
    execution = None

    def symbols_traded_today(self):
        return set()


def _row(symbol, **kw):
    row = {"symbol": symbol, "action": "BUY", "ltp": 100.0,
           "day_high": 100.0, "day_low": 90.0, "change_pct": 5.0,
           "recent_pct": 0.5, "volume_x": 3.0, "score": 1.0,
           "state": "alive",
           "plan": {"ok": True, "qty": 10, "stop": 97.0, "target": 106.0,
                    "value_rs": 1000.0}}
    row.update(kw)
    return row


def _order(rows):
    """The order take() actually considers them in."""
    seen = []

    def _enter(symbol, *a, **k):
        seen.append(symbol)

    take(rows, _Engine(), security_id_of=lambda s: "1",
         enter=_enter, max_positions=len(rows), price_of=None)
    return seen


def test_the_livest_stock_is_considered_first():
    """THE fix. A stock at its high and moving now outranks one with
    twice the cumulative volume that has stopped."""
    stale_giant = _row("STALE", volume_x=40.0, recent_pct=0.0,
                       day_high=110.0, ltp=100.0, state="fading")
    live_small = _row("LIVE", volume_x=3.0, recent_pct=1.2,
                      day_high=100.0, ltp=100.0, state="alive")
    assert _order([stale_giant, live_small])[0] == "LIVE"


def test_volume_still_breaks_a_tie_between_two_live_stocks():
    """Nothing measured was thrown away -- it was demoted below the
    question he asked."""
    quiet = _row("QUIET", volume_x=3.0, recent_pct=0.8)
    heavy = _row("HEAVY", volume_x=30.0, recent_pct=0.8)
    assert _order([quiet, heavy])[0] == "HEAVY"


def test_a_stock_the_feed_cannot_speak_for_is_not_treated_as_dead():
    """None means CANNOT SAY. It sorts between alive and fading, never
    last -- the same posture every other gate in this bot takes."""
    unknown = _row("UNKNOWN", state=None, recent_pct=0.0)
    fading = _row("FADING", state="fading", recent_pct=0.0,
                  day_high=110.0, ltp=100.0)
    assert _order([unknown, fading])[0] == "UNKNOWN"


def test_closest_to_its_own_high_wins_when_both_move_the_same():
    near = _row("NEAR", day_high=100.5, ltp=100.0, recent_pct=0.5)
    far = _row("FAR", day_high=102.5, ltp=100.0, recent_pct=0.5)
    assert _order([near, far])[0] == "NEAR"


def test_the_whole_field_is_priced_before_anything_is_sorted():
    """The ordering cannot rank on a live reading it has not taken.
    price_now() used to run INSIDE the loop, which is why it could
    never inform the sort."""
    priced = []

    def _price_of(symbol):
        priced.append(symbol)
        return {"LTP": 100.0, "high": 100.0, "low": 90.0, "close": 95.0}

    rows = [_row("A"), _row("B"), _row("C")]
    take(rows, _Engine(), security_id_of=lambda s: "1",
         enter=lambda *a, **k: None, max_positions=1, price_of=_price_of)
    assert set(priced) == {"A", "B", "C"}, (
        "only some rows were priced -- the sort ranked stale readings")
