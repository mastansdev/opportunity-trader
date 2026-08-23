"""
==========================================================
The score was worse than random at ordering its own list.
==========================================================

    "this mere 100 +/- 150 rs per trade is not at all feasible right.
     you & me , we both have one common goal to make bot a better
     trader which didn't happened till now"
                                -- operator, 22 August 2026

He was right, and the reason was one sort key.

The bot narrows 1,299 signals to about 23 a day, and that part works
-- those 23 averaged +Rs 73 against -Rs 122 for a random stock. Then
it filled three seats from a list spanning +4.78% to -3.05% and
collected the AVERAGE of it.

MEASURED: 15 sessions, every ordering the bot could compute at alert
time, three seats, entry at the alert minute, exit at the close, on a
Rs 1 lakh position after charges.

    highest volume x      +Rs 565/trade   62.2% up
    best grade first      +Rs 225         55.6%
    most confirmations    +Rs  15         55.6%
    first to fire         -Rs  36         44.4%
    HIGHEST SCORE         -Rs  68         42.2%
    random draw           -Rs 226
    LOWEST volume x       -Rs 823         26.7%

The ranker's own score is WORSE THAN RANDOM at ordering its own list.
Volume against the stock's own normal beats everything, and the mirror
at the bottom -- lowest volume, -Rs 823, 26.7% up -- is what makes it
signal rather than a lucky cut. A random pattern does not invert.

WHAT THIS IS NOT

Rank 1 (+Rs 228) is weaker than the top 3 (+Rs 565), so it is a COARSE
sort, not a precise one. And 7 August alone was Rs 10,107 of the
Rs 25,411 total, so the SIZE of the edge is far less certain than its
direction. It held in both halves (+21,323 then +4,088) and at 3, 5
and 10 seats, which is the test that killed three other rules the same
day.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core import auto_entry

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _row(symbol, volume_x=None, score=0.0, **kw):
    row = {"symbol": symbol, "score": score, "action": "BUY"}
    if volume_x is not None:
        row["volume_x"] = volume_x
    row.update(kw)
    return row


def _order(rows):
    """The sort take() applies before it fills a seat."""
    return [r["symbol"] for r in sorted(
        [r for r in rows if isinstance(r, dict)],
        key=lambda r: (-(auto_entry._num(r.get("volume_x"))
                         or auto_entry._num(r.get("volume_ratio")) or 0.0),
                       -(auto_entry._num(r.get("score")) or 0.0)))]


# ---------------------------------------------------------------
# THE HEAVIEST VOLUME GETS THE SEAT
# ---------------------------------------------------------------

def test_volume_outranks_score():
    """THE CHANGE. The high score used to win and it measured worse
    than a coin flip."""
    got = _order([_row("LOWVOL", volume_x=1.2, score=90.0),
                  _row("HEAVY", volume_x=18.9, score=10.0)])
    assert got == ["HEAVY", "LOWVOL"]


def test_the_20_august_list_orders_correctly():
    """Real names off his board. SUDARSCHEM at 18.9x gave +3.05%,
    NAM-INDIA at 0.3x lost 1.63%."""
    got = _order([_row("NAM-INDIA", volume_x=0.3),
                  _row("SUDARSCHEM", volume_x=18.9),
                  _row("BELRISE", volume_x=13.1),
                  _row("DIXON", volume_x=0.6)])
    assert got[:2] == ["SUDARSCHEM", "BELRISE"]


def test_the_score_still_breaks_ties():
    """It carries the reason weight and the sector work, which volume
    knows nothing about. Dropping it entirely would throw that away."""
    got = _order([_row("WEAK", volume_x=5.0, score=10.0),
                  _row("STRONG", volume_x=5.0, score=80.0)])
    assert got == ["STRONG", "WEAK"]


def test_volume_ratio_is_read_when_volume_x_is_absent():
    """core/ranker.py publishes volume_x; other callers use
    volume_ratio. Reading only one would silently sort by score again
    on half the paths -- which is exactly the bug being fixed."""
    got = _order([_row("A", score=99.0),
                  dict(symbol="B", score=0.0, volume_ratio=9.9)])
    assert got == ["B", "A"]


def test_a_row_with_no_volume_sorts_last_not_first():
    """Missing volume must not read as infinite. A row the ranker
    could not measure is the LEAST evidenced, not the most."""
    got = _order([_row("KNOWN", volume_x=3.0, score=1.0),
                  _row("UNKNOWN", score=99.0)])
    assert got == ["KNOWN", "UNKNOWN"]


def test_junk_does_not_raise():
    """The sort runs on the entry path. A bad row must not stop the
    book from filling."""
    rows = [_row("OK", volume_x=5.0), {"symbol": "X", "volume_x": None},
            {"symbol": "Y", "volume_x": "abc"}, {"symbol": "Z"}]
    assert _order(rows)[0] == "OK"


# ---------------------------------------------------------------
# AND IT IS WIRED WHERE THE SEATS ARE FILLED
# ---------------------------------------------------------------

def test_take_sorts_by_volume_before_filling_a_seat():
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    body = src[src.find("def take("):]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'r.get("volume_x")' in code, (
        "seats are being filled by something other than volume again")
    assert 'r.get("score")' in code, "the score tie-break was dropped"


def test_the_measurement_is_written_down():
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    body = src[src.find("def take("):]
    assert "565" in body and "-Rs 823" in body, (
        "the numbers behind the change are not recorded where it was made")
