"""---- MOVING DOWN IS STILL MOVING. 3 September 2026. ----

    "i need to see the stocks which are actively moving not already
     moved stocks and struck at upper levels"
    "my real goal is to get max profits not maximize the number of
     trades"                                       -- the operator

liveness() decides whether a move is still happening. The gate that
acts on it already existed -- core/auto_entry.refuse_reason() has
refused state == "fading" all along, and I nearly re-added it. The
wiring was never the problem. The TEST inside liveness() was:

    if recent is not None and abs(recent) < MIN_RECENT_PCT:
        dead = True

abs(). So a stock sliding 0.28% in the recent window counted as
moving, because it was moving -- downwards. Live on his board at
15:20 today, every one of these reading ALIVE while drifting down:

    RAYMOND    off_high 0.84   recent -0.28
    RBLBANK    off_high 0.60   recent -0.36
    JYOTICNC   off_high 1.58   recent -0.65
    KIRIINDUS  off_high 2.22   recent -0.45

He is long only. A long whose recent window is negative is not a move
he is joining, it is one he is catching. Flat is still dead -- that
part the old test had right and this keeps.
"""

from core.ranker import MIN_RECENT_PCT, liveness


def _row(change_pct, recent_pct, ltp=100.0, day_high=101.0, **kw):
    row = {"change_pct": change_pct, "recent_pct": recent_pct,
           "ltp": ltp, "day_high": day_high, "day_low": 95.0}
    row.update(kw)
    return row


def test_a_long_drifting_down_is_fading():
    """THE BUG. RAYMOND: 0.84% off its high, recent -0.28%, and the
    bot called it alive and was free to buy it."""
    state, _ = liveness(_row(change_pct=14.5, recent_pct=-0.28,
                             ltp=100.0, day_high=100.85))
    assert state == "fading", (
        "a stock going DOWN in the recent window reads as moving -- "
        "abs() cannot tell a rally from a slide")


def test_a_long_still_rising_is_alive():
    """The rule must not refuse everything. This is the shape he wants
    to buy: near the high, still going up."""
    state, _ = liveness(_row(change_pct=8.0, recent_pct=1.46,
                             ltp=100.0, day_high=100.08))
    assert state == "alive"


def test_flat_is_still_dead():
    """What the old test caught, and it was right. A stock going
    nowhere is not an opportunity."""
    state, _ = liveness(_row(change_pct=6.0,
                             recent_pct=MIN_RECENT_PCT / 2))
    assert state == "fading"


def test_far_off_the_high_is_still_dead():
    """Unchanged: more than MAX_OFF_EXTREME_PCT off the high is a move
    that has given itself back."""
    state, _ = liveness(_row(change_pct=6.0, recent_pct=2.0,
                             ltp=90.0, day_high=100.0))
    assert state == "fading"


def test_it_still_says_nothing_when_it_cannot_tell():
    """None means cannot say, and must never read as fading. A guess
    must not refuse a trade."""
    state, _ = liveness({"change_pct": 5.0})
    assert state is None


def test_the_entry_gate_acts_on_it():
    """The gate was always there -- this is what makes the fix reach
    an order. Asserted on the source because an absent call is the
    failure, and no mock can catch that."""
    import os
    with open(os.path.join("core", "auto_entry.py"), encoding="utf-8") as fh:
        body = fh.read()
    assert 'row.get("state") == "fading"' in body
    assert "the move has already stopped working" in body
