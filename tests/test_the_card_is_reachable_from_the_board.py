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


def test_the_board_calls_the_endpoint_at_all(page):
    """THE ONE THAT WAS FALSE FOR THREE DAYS."""
    assert "/api/stock/" in page, (
        "board.html never asks for the stock card. core/stock_card.py "
        "and GET /api/stock/{symbol} both work -- and nothing on the "
        "page he opens has ever called them.")


def test_every_table_makes_its_symbols_clickable(page):
    """Movers, gaps, closed trades and the watchlist. A card reachable
    from one table only is a card he will not find."""
    assert page.count("data-card=") >= 4, (
        f"only {page.count('data-card=')} table(s) open the card")


def test_the_click_handler_opens_it(page):
    assert 'closest("[data-card]")' in page
    assert "openCard(" in page


def test_the_card_wins_over_the_row_it_sits_in(page):
    """A symbol inside a watchlist row is also inside an element
    carrying data-wl. If the watchlist handler ran first, clicking the
    name would try to add a stock already on the list instead of
    opening its card."""
    handler = page[page.find("document.addEventListener(\"click\""):]
    card_at = handler.find('closest("[data-card]")')
    wl_at = handler.find('closest("[data-wl]")')
    assert card_at != -1 and wl_at != -1
    assert card_at < wl_at, (
        "the watchlist handler is checked before the card, so clicking "
        "a symbol in the Watch tab does the wrong thing")


def test_an_empty_section_is_omitted_not_drawn_blank(page):
    """A heading with nothing under it reads as "the bot knows
    nothing", when the truth is usually "this stock has no results
    yet". Two different statements."""
    body = page[page.find("function cardSection("):page.find("async function openCard")]
    assert "filter" in body and "if (!real.length) return \"\"" in body


def test_it_shows_the_stored_events_and_their_kind(page):
    """"whats being used" -- the typed events are the link between
    "the bot stored something" and "the bot called it an order win"."""
    card = page[page.find("async function openCard"):page.find("function drawBrain")]
    assert "Stored events" in card
    assert "e.kind" in card, "the events are listed without their type"


def test_an_unknown_symbol_says_so_rather_than_hanging(page):
    card = page[page.find("async function openCard"):page.find("function drawBrain")]
    assert "found === false" in card
    assert "not in the master database" in card


def test_a_dead_fetch_never_leaves_it_loading(page):
    card = page[page.find("async function openCard"):page.find("function drawBrain")]
    assert "could not reach the bot" in card


def test_the_endpoint_is_still_served():
    """The link is worth nothing if the route was renamed."""
    src = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '@app.get("/api/stock/{symbol}")' in src
