"""
==========================================================
NaN is truthy, and it stopped the bot from starting
==========================================================

    Traceback (most recent call last):
      File "main.py", line 1661, in main
        dashboard_state.refresh()
      File "dashboard/state.py", line 5956, in _build_market_intelligence
        name = (row.get("sector") or "").upper()
    AttributeError: 'float' object has no attribute 'upper'
                                -- operator, 17 August 2026

main.py did not start. Not a panel failing quietly -- the whole
process, on the first refresh, before the market opened.

WHY `or ""` CANNOT WORK HERE
---------------------------
pandas reads an empty cell as float('nan'), and NaN IS TRUTHY:

    bool(float('nan'))  ->  True
    nan or ""           ->  nan
    (nan or "").upper() ->  AttributeError

So both guards in dashboard/state.py were writing cheques NaN would
not honour. The first let it through:

    sector = row["sector"]
    if not sector: continue        <- NaN is truthy: passed

and it became a dict key, went into the sector row, and crashed 1,100
lines later where the second one lives.

213 rows in data/master_stocks.csv have no SECTOR. Every one of them
is SUBSCRIBE=NO -- ETFs and InvITs: MONIFTY500, GOLDETF, EMBASSY,
CUBEINVIT. Only one had to reach the gainers list.

THE SAME TRAP, TWO DAYS RUNNING. core/master_loader.py's series gate
read `str(x or "")` as the string "nan" and BLOCKED a row it should
have waved through -- the opposite symptom, the identical cause. The
only safe test for NaN is value != value.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from dashboard.state import _text

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAN = float("nan")


def test_the_exact_line_that_crashed_no_longer_can():
    """(nan or "").upper() -- the line from the traceback."""
    with pytest.raises(AttributeError):
        (NAN or "").upper()          # the old form, still broken
    assert _text(NAN) == ""          # the new one


def test_nan_is_falsy_once_cleaned():
    """The FIRST guard is the one that matters: a NaN sector must not
    become a dict key. It only crashed later."""
    assert bool(NAN) is True, "if this ever changes, so does the bug"
    assert not _text(NAN)


@pytest.mark.parametrize("value,want", [
    (None, ""), (NAN, ""), ("", ""), ("   ", ""),
    ("nan", ""), ("NaN", ""), ("NAN", ""),
    ("Banking", "BANKING"), (" finance ", "FINANCE"),
])
def test_it_cleans_every_shape_a_blank_cell_arrives_as(value, want):
    assert _text(value) == want


def test_a_real_value_is_never_lost():
    """Over-cleaning would be its own bug: an empty sector heatmap
    reads as 'no sectors moved' rather than 'the column broke'."""
    assert _text("METALS & MINING") == "METALS & MINING"
    assert _text("Oil to Chemicals") == "OIL TO CHEMICALS"


def test_neither_guard_uses_the_broken_form_any_more():
    # EVERYTHING AFTER _text(). Its docstring QUOTES the crashing line
    # to explain it, so searching the whole file matches the
    # explanation and reports the bug as un-fixed. Ninth time in this
    # session a test here has matched prose rather than code -- the
    # cure is always the same: read the code.
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    code = src.split("def _num(value):", 1)[1]
    assert '(row.get("sector") or "").upper()' not in code, (
        "the crashing form is back")
    assert 'sector = row["sector"]\n            if not sector:' not in code, (
        "the guard that let a NaN sector through is back")


def test_the_live_master_still_has_rows_that_would_trip_it():
    """If this ever returns 0 the tests above are still right but are
    no longer guarding anything real -- worth knowing."""
    import pandas as pd
    df = pd.read_csv(ROOT / "data" / "master_stocks.csv",
                     dtype={"SECURITY ID": str})
    blank = df[df["SECTOR"].isna()]
    assert len(blank) > 0
    tradeable = blank[blank["SUBSCRIBE"].astype(str).str.upper() == "YES"]
    assert len(tradeable) == 0, (
        f"{len(tradeable)} TRADEABLE row(s) have no sector -- the "
        f"sector-strength gate cannot see them: "
        f"{list(tradeable['SYMBOL'].head(5))}")
