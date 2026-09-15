"""
==========================================================
Everything the bot knows about one stock, from the screen he uses
==========================================================

    "dashboard must contain all info from bot. recall the memory of any
     stock on demand"                    -- operator, 29 July 2026

    "how the data is being stored corresponding to stock? i cannot see
     them even now ... only place is dashboard to check any specific
     data about how its being tagged & whats being used"
                                         -- operator, 16 August 2026

Three weeks separate those two sentences and the second one is the
same request. It was answered on 11 August: core/stock_card.py, whose
docstring states the principle plainly -- "if the bot holds a fact and
acts on it, hiding that fact is a bug by definition" -- and
GET /api/stock/{symbol} has served it ever since.

board.html called it ZERO times. The card was reachable only from
/full, the page he moved away from on 13 August, so the honest answer
to "where is it" was "on a screen you stopped opening".

Sixth time in two days that something built, tested and working
reached nobody: delivery %, the run-up reading, the watchlist panel,
the AI spend, the opportunity memory, and this.

These tests hold the LINK, not the card. The card had tests already
and they all passed while it was invisible.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOARD = ROOT / "dashboard" / "static" / "board.html"


@pytest.fixture(scope="module")
def page():
    return BOARD.read_text(encoding="utf-8")


def test_the_endpoint_is_still_served():
    """The link is worth nothing if the route was renamed."""
    src = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '@app.get("/api/stock/{symbol}")' in src
