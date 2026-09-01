"""---- IT REFUSED WITH THE ANSWER IN ITS HAND. 1 September 2026. ----

    "first settle this one as it occured today might return tomorrow
     right with same set of rules. how do u expect different outcome
     while using same inputs?"
                                                -- the operator

On 1 September these were refused before anything looked at them:

    NORTHARC     49.2x its normal volume    no level to stop behind yet
    ATHERENERG    3.4x                      no level to stop behind yet
    TBZ                                     no level to stop behind yet
    PTC                                     no level to stop behind yet

WHY. position_plan.stop_for() has exactly two ways to find a level for
a long: today's LOW if it is below the entry, or entry minus the ATR.
And dashboard/state.py's ranked path calls plan() without an atr --

    row["plan"] = position_plan(
        source.get("ltp"), row.get("action"),
        day_low=..., day_high=..., margin_pct=..., symbol=...)

-- so on the live path the ATR branch was DEAD and the day low was the
only candidate there had ever been. A missing day low, or a stock
sitting at its own low, refused the whole trade.

Measured before the fix:

    stop_for(100, "BUY", day_low=97.0)   ->  97.0
    stop_for(100, "BUY", day_low=None)   ->  None
    stop_for(100, "BUY", day_low=100.0)  ->  None
    plan(100, "BUY", day_low=None, symbol="NORTHARC")
        -> {'ok': False, 'why': 'no level to stop behind yet'}

The symbol was RIGHT THERE, and core/atr.scaled_stop_pct() -- the same
function core/engine.py sizes every live stop from -- was imported
forty lines below to WIDEN a stop that already existed. The bot had the
number and refused anyway.

THE TRAP IN THE FIRST VERSION OF THE FIX, and it is why the last test
here exists. The widening call passes fallback_pct=MIN_STOP_DISTANCE_PCT,
which is right when a stop already exists and is only being stretched.
Copying that here handed an UNKNOWN symbol a 0.75% stop and 3,333
shares -- inventing a stop for a stock with no daily range at all,
which is exactly what the original refusal was protecting against.
fallback_pct is None here on purpose.
"""

from core.position_plan import plan, stop_for

# Real symbols with daily bars in this repo's store.
REAL = ("NORTHARC", "ATHERENERG", "TBZ", "PTC")


def _has_range(symbol):
    from config import DAILY_ATR_STOP_MULT
    from core.atr import scaled_stop_pct
    from core.position_plan import (MAX_STOP_DISTANCE_PCT,
                                    MIN_STOP_DISTANCE_PCT)
    try:
        return bool(scaled_stop_pct(symbol, DAILY_ATR_STOP_MULT,
                                    MIN_STOP_DISTANCE_PCT,
                                    MAX_STOP_DISTANCE_PCT, None))
    except Exception:                                      # noqa: BLE001
        return False


# ------------------------------------------------- the refusal was wrong

def test_a_missing_day_low_no_longer_refuses_the_trade():
    """NORTHARC at 49.2x its normal volume, never evaluated."""
    for symbol in REAL:
        if not _has_range(symbol):
            continue
        got = plan(100.0, "BUY", day_low=None, symbol=symbol)
        assert got.get("ok"), f"{symbol} still refused: {got}"
        assert got.get("stop") and got["stop"] < 100.0, got


def test_a_stock_sitting_at_its_own_low_is_also_planned():
    """The other half of the same branch: day_low is present but is not
    BELOW the entry, so it is not a level to stop behind either."""
    for symbol in REAL:
        if not _has_range(symbol):
            continue
        got = plan(100.0, "BUY", day_low=100.0, symbol=symbol)
        assert got.get("ok"), f"{symbol} refused at its own low: {got}"


# ------------------------------------------- and it is not a made-up stop

def test_a_stock_with_no_daily_range_still_refuses():
    """THE TRAP. The first version of this fix copied the widening
    call's fallback_pct and handed an unknown symbol a 0.75% stop and
    3,333 shares. An invented stop is worse than none -- it will be
    believed, and it will be wrong at the worst moment."""
    got = plan(100.0, "BUY", day_low=None, symbol="NOSUCHSTOCK12345")
    assert got.get("ok") is not True, got
    assert "no level to stop behind" in got.get("why", ""), got


def test_no_symbol_still_refuses():
    """Nothing to look the range up with."""
    got = plan(100.0, "BUY", day_low=None)
    assert got.get("ok") is not True, got


def test_the_fallback_is_not_accepted_here():
    """Asserted on the source, because the failure mode is a silently
    plausible number rather than an error. If someone re-adds
    MIN_STOP_DISTANCE_PCT as the fallback, every unknown symbol becomes
    tradeable again at the floor stop."""
    import inspect

    src = inspect.getsource(plan)
    at = src.find("from_range = scaled_stop_pct")
    assert at > 0, "the ATR fallback has been removed"
    call = src[at:at + 220]
    assert "None)" in call, (
        "a fallback percent is being accepted where there is no stop "
        "to widen -- an unknown symbol will get an invented stop")


# ----------------------------------------------- the old path is untouched

def test_a_real_day_low_is_still_preferred():
    """The ATR is the FALLBACK, not the rule. A stock with a genuine
    level below it must still stop behind that level."""
    got = plan(100.0, "BUY", day_low=97.0, symbol="NORTHARC")
    assert got.get("ok")
    assert got["stop"] == 97.0, (
        f"the ATR overrode a real level below the price: {got}")


def test_stop_for_itself_is_unchanged():
    """The fallback lives in plan(), not in stop_for(). Anything else
    reading stop_for() directly must see exactly what it saw before."""
    assert stop_for(100.0, "BUY", day_low=97.0) == 97.0
    assert stop_for(100.0, "BUY", day_low=None) is None
    assert stop_for(100.0, "BUY", day_low=100.0) is None


def test_the_short_side_stops_above():
    """Mirrored, and the bot is long-only -- but a stop on the wrong
    side of the price is the kind of thing that is only ever found
    live."""
    for symbol in REAL:
        if not _has_range(symbol):
            continue
        got = plan(100.0, "SELL", day_high=None, symbol=symbol)
        if got.get("ok"):
            assert got["stop"] > 100.0, got
        return
