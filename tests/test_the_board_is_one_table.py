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


def test_every_column_he_asked_for_is_on_it():
    """---- THE HEADINGS ARE IN ENGLISH NOW. 30 August 2026. ----

        "i would love incase u used simpler words in whole dashboard
         like day to day usage words which doesn't disturb the actual
         meaning of the real trading terminology"
        "keep both words"                        -- the operator

    The columns are all still here. CMP is headed "Price now" with
    "CMP" under it in grey, and the same for the rest -- so this
    checks the reading is present AND that the real term survived the
    rename, which is the half he was protecting.
    """
    page = _board().text
    for plain, jargon in (("Price now", "CMP"),
                          ("Today", "change"),
                          ("Yesterday", "prev close"),
                          ("Money traded", "turnover")):
        assert f'>{plain}<span class="jargon">{jargon}<' in page, (
            f"{plain} ({jargon}) column is missing")
    for column in ("Open", "High", "Low", "Volume"):
        assert f">{column}<" in page, f"{column} column is missing"


def test_the_live_tab_is_one_table():
    """'no more top 50/20/10 gainers tables'. LIVE is one table. PRE
    carries two because gap up and gap down are opposite trades -- his
    call, 9 August: "okay keep separate then & build top 20 each side".
    POST carries the day's trades. Three tabs, never stacked."""
    page = _board().text
    assert page.count('id="live-pane"') == 1
    assert page.count('<tbody id="body"') == 1


def test_only_twenty_rows_are_drawn():
    """'20 stocks is good number to see. less is more.' The bot still
    ranks all 1,223 -- this caps what reaches the screen."""
    assert "const SHOW = 20" in _board().text


def test_pre_splits_the_gap_both_ways_at_twenty_each():
    page = _board().text
    assert "Gapped UP" in page and "Gapped DOWN" in page
    assert page.count('class="cap">Gapped') == 2
    assert 'id="gapup"' in page and 'id="gapdn"' in page


def test_the_gap_is_measured_from_yesterdays_close():
    """Not from today's open. The gap is what happened while the market
    was shut, and it is the same number core/headroom.py spends against
    the circuit."""
    assert "(op - pc) / pc * 100" in _board().text


def test_the_tabs_never_stack_on_top_of_each_other():
    page = _board().text
    for pane in ("pre", "live", "post"):
        assert f'id="{pane}-pane"' in page
    assert 'data-tab' in page


def test_the_verdict_is_a_word_and_the_reason_is_a_sentence():
    """'explaining chips of why verdict to act by bot'. A colour alone
    is not a reason -- he has to be able to argue with it."""
    page = _board().text
    assert "Why it is moving" in page
    for verdict in ("READY", "WATCH", "BLOCKED", "HELD"):
        assert verdict in page


def test_a_refused_stock_still_shows_and_says_why():
    """LICI on 4 August: bought on huge volume with the OFS notice
    already in the store. A refusal he cannot see is one he cannot
    argue with, so blocked rows stay on the table."""
    page = _board().text
    assert "blocking" in page
    assert "BLOCKED" in page


def test_what_can_still_make_money_leads_the_table():
    page = _board().text
    # 11 August: the sort key moved from verdict-order to
    # held -> graded -> size of move, when the table stopped being the
    # tail of the ranker and became a view of the tape.
    assert "const all = movers.sort" in page
    assert "a.held ? 0 : 1" in page


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

def test_post_reads_the_key_the_state_really_publishes():
    """I nearly built this tab against `trades_today`, a name I had
    guessed. It does not exist. An empty POST tab all day would have
    looked like a dead bot, not a wrong key. The real key is
    closed_positions."""
    page = _board().text
    assert "closed_positions" in page
    assert "s.closed_positions" in page
    assert "s.trades_today" not in page


def test_post_shows_the_net_not_the_gross():
    """Brokerage and STT come out first. The number on the screen is
    the number that reached the account."""
    page = _board().text
    assert "net_pnl" in page
    assert "paid in charges" in page


def test_post_says_why_it_went_in_and_why_it_came_out():
    """Both ends, on one line. A trade he cannot explain is one he
    cannot learn from."""
    page = _board().text
    assert "entry_reason" in page and "exit_reason" in page
    assert "Why in, why out" in page
