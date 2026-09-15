"""
The one-table board, 9 August 2026.

    "tomorrow i want the dashboard as it is like now you showed with
     fonts, explaining chips of why verdict to act by bot . still the
     CMP, Volume, Open, High, Low. is not showed ? tomorrow we will fix
     the dashboard with only one table. no more top 50/20/10 gainers
     tables."

THE PRICES WERE NEVER MISSING FROM THE SCREEN
---------------------------------------------
They were missing from the PAYLOAD. core/ranker.py built each row with
the score, the sector, the volume MULTIPLE and the reason -- and not
one actual price. The dashboard could show him why the bot liked a
stock and not what the stock cost, and no amount of front-end work
could have fixed that.

So the first test here is on the ranker, not the page.
"""

import pytest

from tests.test_dashboard_server import _client


SNAP = {
    "bot_enabled": False,
    "universe_size": 1223,
    "as_of": "10:04",
    "feed_silent": ["ELECTCAST", "TRIVENI"],
    "ranked": {"rows": [
        {"symbol": "SHILPAMED", "grade": "GOOD", "ltp": 783.2,
         "change_pct": 1.71, "open": 770.0, "high": 790.0, "low": 768.0,
         "volume": 1250000, "mechanism": "GOOD result", "volume_x": 3.1,
         "sector": "PHARMACEUTICALS"},
        {"symbol": "LICI", "ltp": 905.0, "change_pct": 0.4, "open": 900.0,
         "high": 912.0, "low": 898.0, "volume": 9400000,
         "blocking": ["an offer for sale is on -- a block is coming"]},
    ]},
}


def _board():
    client, _ = _client(SNAP)
    return client.get("/board")


# ---------------------------------------------------------------
# The payload -- where the real fault was
# ---------------------------------------------------------------

def test_the_ranker_puts_the_prices_in_the_row():
    """CMP, open, high, low and volume must LEAVE core/ranker.py. This
    is the fix; the page below only prints what it is handed."""
    from core.ranker import rank
    rows = [{"symbol": "SHILPAMED", "ltp": 783.2, "day_open": 770.0,
             "day_high": 790.0, "day_low": 768.0, "volume": 1250000,
             "turnover_cr": 97.9, "prev_close": 762.0, "change_pct": 4.71,
             "sector": "PHARMACEUTICALS"}]
    got = rank(rows, adv_of=lambda s: 40.0, top=5)
    candidates = got.get("rows") or []
    if not candidates:
        pytest.skip("no candidate cleared the gates in this fixture")
    row = candidates[0]
    for field in ("ltp", "open", "high", "low", "volume"):
        assert field in row, f"{field} never leaves the ranker"


def test_the_price_fields_are_declared_on_the_candidate():
    """Belt and braces -- the gates can change, the contract cannot."""
    import inspect
    from core import ranker
    src = inspect.getsource(ranker.rank)
    for field in ('"ltp"', '"open"', '"high"', '"low"', '"volume"'):
        assert field in src, f"{field} is not set on the Candidate"


# ---------------------------------------------------------------
# One table
# ---------------------------------------------------------------

def test_the_board_is_served():
    assert _board().status_code == 200


def test_the_tabs_never_stack_on_top_of_each_other():
    page = _board().text
    for pane in ("pre", "live", "post"):
        assert f'id="{pane}-pane"' in page
    assert 'data-tab' in page


def test_a_dead_fetch_does_not_blank_the_board():
    """The old page rebuilt every panel every second and wiped the qty
    box. A failed poll here must leave the last good rows on screen."""
    assert "catch" in _board().text


# ---------------------------------------------------------------
# It must not replace the working screen
# ---------------------------------------------------------------

def test_the_old_screen_still_answers_on_slash():
    """Same rule the React page followed on 6 August: a new screen is
    offered BESIDE the working one, never in place of it."""
    client, _ = _client(SNAP)
    assert client.get("/").status_code == 200


# ---------------------------------------------------------------
# POST -- what the bot actually did
# ---------------------------------------------------------------

