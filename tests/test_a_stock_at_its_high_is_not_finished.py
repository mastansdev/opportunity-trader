"""---- THE WINNERS WERE SOLD AT THE TOP TICK. 3 September 2026. ----

    "why we need to focus on only loosing part ? and leaving the
     gaining stocks completely"                     -- the operator

He is right, and the day proves it. All THIRTEEN winning trades on
3 September exited BUYING_DRIED_UP. Not one reached the 2.5% peak
trail that exists for exactly this purpose. Eleven were sold while
price was still climbing. Two were sold at a new high -- the sale
price was the highest print of the day so far:

    stock       sold at  held    made   the day's peak, later
    BRIGADE      689.66   84m   3,406   732.30 at 15:25
    HIKAL        224.95   15m     648   239.45 at 14:48
    KIRIINDUS    564.47   15m      99   589.55 at 13:19
    ANANTRAJ     623.79   15m   1,587   640.00 at 12:16
    RAYMOND      746.83   15m     412   764.00 at 15:25

Rs 23,310 left in one session. The whole day's charges were Rs 2,000.

WHY IT FIRED. still_buying() is

    bool(now["cum"] > 0 and now["cum"] > then["cum"])

on CUMULATIVE delta, so it asks only whether the last fifteen minutes
had net buying in ANY amount. One share of net selling flips it, one
tick acts on it, and it never looks at price at all.

His rule is "exit once the momentum gone". Price making new highs is
momentum. So this pins the one thing that must be true: a winner
sitting at its own high is not closed on a flow reading. The peak
trail owns that exit.
"""

import pytest

from config import BUYING_DRIED_UP_MIN_OFF_PEAK_PCT


class _Trail:
    def __init__(self, peak):
        self._peak = peak

    def get_peak(self, symbol):
        return self._peak


def _engine(peak, still_buying=False):
    """A stub carrying only what _buying_dried_up() reads."""
    from core.engine import Engine
    eng = object.__new__(Engine)
    eng.buying_check = lambda sym: {"still_buying": still_buying,
                                    "delta": -10, "was": 100}
    eng.open_positions = {"HIKAL": {"entry_price": 223.02, "qty": 336,
                                    "entry_time": None}}
    eng.trailing_stop = _Trail(peak)
    eng._held_minutes = lambda pos, t: 15.0
    eng.exits = []
    eng._exit = lambda sym, px, why, t: eng.exits.append((sym, px, why))
    return eng


def test_it_does_not_sell_a_winner_sitting_at_its_high():
    """THE BUG. HIKAL at 224.95 was its own high, the flow read
    'stopped', and the bot sold. It closed the day at 239.45."""
    eng = _engine(peak=224.95)
    assert eng._buying_dried_up("HIKAL", 224.95, None) is False
    assert eng.exits == []


def test_it_does_not_sell_just_below_the_high_either():
    """A rally breathes. Inside the band the trail owns the exit."""
    peak = 224.95
    just_off = peak * (1 - BUYING_DRIED_UP_MIN_OFF_PEAK_PCT / 100.0 / 2)
    eng = _engine(peak=peak)
    assert eng._buying_dried_up("HIKAL", just_off, None) is False


def test_it_still_sells_once_the_move_has_actually_stalled():
    """The rule must not become 'never sell on flow'. Reading order
    flow is the point; this only stops it selling the top tick.

    The peak here is HIKAL's real day high of 239.45 rather than the
    224.95 the bot sold at, so that a price 1.2% off the peak is still
    comfortably ABOVE the 223.02 entry -- _buying_dried_up() is a
    winners-only rule and refuses below entry before this gate is
    even reached."""
    peak = 239.45
    stalled = peak * (1 - BUYING_DRIED_UP_MIN_OFF_PEAK_PCT / 100.0 - 0.002)
    eng = _engine(peak=peak)
    assert eng._buying_dried_up("HIKAL", stalled, None) is True
    assert eng.exits and eng.exits[0][2] == "BUYING_DRIED_UP"


def test_no_peak_is_not_a_reason_to_sell():
    """A missing reading means nothing, never 'sell' -- the same rule
    the flow check itself already follows."""
    eng = _engine(peak=None)
    assert eng._buying_dried_up("HIKAL", 224.95, None) is True


def test_the_band_is_inside_the_peak_trail():
    """If this were >= PEAK_TRAIL_PCT the trail would always fire
    first and the flow reading could never act at all."""
    from config import PEAK_TRAIL_PCT
    assert BUYING_DRIED_UP_MIN_OFF_PEAK_PCT / 100.0 < PEAK_TRAIL_PCT
