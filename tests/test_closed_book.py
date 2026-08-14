"""
==========================================================
The closed book carries both -- his trades and the bot's
==========================================================

    "post tab will be my closing positions . and pnl"
    "yes book needs to carry both right?"
                                    -- operator, 4 August 2026

On 4 August he made about Rs 10,000 trading entirely from the Dhan
platform. The bot placed zero orders. The POST tab said "no closed
trades today" -- honest about the bot's day, and useless about his.

That also broke his own standing rule: open positions already show
whoever placed them, because they come from Dhan. Closed ones did not.

WHY NOT THE TRADE BOOK
----------------------
GET /trades returns that DAY's fills. A position opened yesterday and
closed today arrives as a lone SELL with no buy to pair against, and on
MTF that is most of his trades. Pairing them would mean inventing the
entry price. GET /positions carries positionType CLOSED with buyAvg,
sellAvg and realizedProfit already computed across however many days
the position was open -- the broker's own arithmetic on the broker's
own fills.

Author : H&M Opportunity Trader
==========================================================
"""

from core.closed_book import BOT, DHAN, from_dhan, is_closed, merge, totals


def dhan_row(symbol="TCS", buy=3000.0, sell=3050.0, qty=10,
             pnl=500.0, closed=True, **kw):
    row = {"tradingSymbol": symbol, "buyAvg": buy, "sellAvg": sell,
           "buyQty": qty, "sellQty": qty if closed else 0,
           "netQty": 0 if closed else qty,
           "positionType": "CLOSED" if closed else "LONG",
           "realizedProfit": pnl, "productType": "MTF"}
    row.update(kw)
    return row


# ---------------------------------------------------------------
# 1. WHAT COUNTS AS CLOSED
# ---------------------------------------------------------------
def test_dhan_saying_closed_is_enough():
    assert is_closed(dhan_row()) is True


def test_a_net_zero_row_is_closed_even_without_the_label():
    """Requiring both the label AND netQty 0 would drop a trade the
    moment one of them is missing. A missing closed trade is the exact
    failure being fixed."""
    row = dhan_row()
    row.pop("positionType")
    assert is_closed(row) is True


def test_an_open_position_is_not_closed():
    assert is_closed(dhan_row(closed=False)) is False


def test_an_empty_row_is_not_a_flat_trade():
    """netQty 0 with nothing ever traded is an empty row, not a trade
    that made nothing. Counting it would inflate his trade count with
    trades that never happened."""
    assert is_closed({"tradingSymbol": "X", "netQty": 0,
                      "buyQty": 0, "sellQty": 0}) is False


def test_junk_is_refused_quietly():
    for junk in (None, "CLOSED", 7, []):
        assert is_closed(junk) is False


# ---------------------------------------------------------------
# 2. THE BROKER'S NUMBER IS THE NUMBER
# ---------------------------------------------------------------
def test_realized_profit_is_taken_from_dhan_not_recomputed():
    """It is his money and their contract note. Where our arithmetic
    disagrees with Dhan's, Dhan is right."""
    # Deliberately inconsistent: 50 x 10 would be 500, Dhan says 487.30
    # (it knows about the odd lot we do not). Ours must not "correct" it.
    got = from_dhan([dhan_row(pnl=487.30)])
    assert got[0]["pnl"] == 487.30


def test_the_prices_and_size_come_across():
    got = from_dhan([dhan_row()])[0]
    assert got["symbol"] == "TCS"
    assert got["entry_price"] == 3000.0
    assert got["exit_price"] == 3050.0
    assert got["qty"] == 10
    assert got["product"] == "MTF"
    assert got["origin"] == DHAN


def test_open_positions_are_left_out():
    got = from_dhan([dhan_row("TCS"), dhan_row("INFY", closed=False)])
    assert [r["symbol"] for r in got] == ["TCS"]


def test_a_short_reads_its_entry_from_the_sell_side():
    """Sold first, bought back after. The sell is the entry -- shown
    the other way round it reads as a losing trade that won."""
    row = dhan_row("GAIL", buy=196.0, sell=200.0, pnl=200.0,
                   carryForwardSellQty=50, carryForwardBuyQty=0)
    got = from_dhan([row])[0]
    assert got["direction"] == "SHORT"
    assert got["entry_price"] == 200.0
    assert got["exit_price"] == 196.0


def test_no_rows_is_an_empty_list_not_a_crash():
    assert from_dhan(None) == []
    assert from_dhan([]) == []
    assert from_dhan([None, "x", {}]) == []


def test_a_row_with_no_symbol_is_dropped():
    assert from_dhan([dhan_row(symbol="")]) == []


# ---------------------------------------------------------------
# 3. BOTH BOOKS, ONE LIST
# ---------------------------------------------------------------
def test_a_trade_only_dhan_knows_about_is_added():
    """The 4 August case: the bot's book is empty, his is not."""
    got = merge([], from_dhan([dhan_row()]))
    assert [r["symbol"] for r in got] == ["TCS"]
    assert got[0]["origin"] == DHAN


def test_a_trade_only_the_bot_knows_about_survives():
    bot = [{"symbol": "AAA", "qty": 5, "entry_price": 10.0,
            "exit_price": 12.0, "pnl": 10.0}]
    got = merge(bot, [])
    assert got[0]["origin"] == BOT


def test_the_same_trade_is_not_counted_twice():
    bot = [{"symbol": "TCS", "qty": 10, "entry_price": 2999.0,
            "exit_price": 3050.0, "pnl": 510.0, "exit_reason": "stop hit"}]
    got = merge(bot, from_dhan([dhan_row()]))
    assert len(got) == 1


def test_dhan_wins_on_the_numbers_and_the_bot_keeps_the_reason():
    """The engine's copy drifts after a restart or a fill it never saw,
    so the settled record wins on price and P&L. But 'why it closed' is
    the one thing Dhan cannot tell him, so that is kept."""
    bot = [{"symbol": "TCS", "qty": 10, "entry_price": 2999.0,
            "exit_price": 3050.0, "pnl": 510.0,
            "exit_reason": "momentum gone"}]
    got = merge(bot, from_dhan([dhan_row(pnl=500.0)]))[0]
    assert got["pnl"] == 500.0
    assert got["entry_price"] == 3000.0
    assert got["exit_reason"] == "momentum gone"
    assert got["origin"] == BOT       # the bot did open it


# ---------------------------------------------------------------
# 4. THE HEADER LINE
# ---------------------------------------------------------------
def test_totals_count_wins_losses_and_who():
    rows = merge(
        [{"symbol": "AAA", "pnl": 300.0}],
        from_dhan([dhan_row("TCS", pnl=500.0),
                   dhan_row("GAIL", pnl=-200.0)]))
    got = totals(rows)
    assert got["trades"] == 3
    assert got["won"] == 2 and got["lost"] == 1
    assert got["gross_pnl"] == 600.0
    assert got["best"] == 500.0 and got["worst"] == -200.0
    assert got["bot_trades"] == 1 and got["dhan_trades"] == 2


def test_a_flat_day_does_not_divide_by_anything():
    assert totals([])["trades"] == 0
    assert totals([])["best"] == 0.0
    assert totals(None)["gross_pnl"] == 0


def test_a_row_with_no_pnl_is_not_counted_as_a_scratch():
    """None means unknown. Counting it as zero would report a trade
    that broke even when we simply could not price it."""
    assert totals([{"symbol": "X", "pnl": None}])["trades"] == 0


# ---------------------------------------------------------------
# 5. IT IS WIRED IN, AND IT CANNOT TAKE THE PAGE DOWN
# ---------------------------------------------------------------
def test_the_dashboard_merges_both_books():
    src = open("dashboard/state.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "closed_book.merge(" in code
    assert "closed_book.from_dhan(" in code


def test_it_makes_no_extra_broker_call():
    """positions() already carries the open rows AND the closed ones.
    A second REST call per refresh, for a tab he reads after the close,
    would be latency spent on nothing."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "get_trade_book" not in src


def test_the_post_screen_says_whose_trade_it_was():
    """---- THE PAGE THAT SAID SO IS GONE. 13 August 2026. ----

    This read dashboard/static/screen.html for `r.origin === "DHAN"`
    -- the marker separating a trade the BOT took from one adopted
    from the broker. screen.html was deleted when four dashboards
    became two, and neither /board nor /full carries the marker.

    The DISTINCTION still matters and is still in the data: closed
    rows carry `origin`, and data/trade_memory.db shows why it matters
    -- ADOPTED_FROM_BROKER lost Rs 69,766 on n=19 while the bot's own
    ORB entries were roughly flat. Reading those two as one number is
    how the bot got blamed for the account.

    ---- AND IT IS BACK, later the same day. ----

    The gap marker written that morning failed the moment /board drew
    the marker, saying "remove this test and assert the display
    directly". Done.

    The board now shows an `adopted` chip on the row, and -- the part
    that matters -- splits the day summary, so a book carrying
    positions the bot never chose is never summed with the entries it
    did choose.
    """
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"origin"' in src, (
        "closed rows no longer carry `origin`, so a broker-adopted "
        "position and a bot entry are indistinguishable")

    board = open("dashboard/static/board.html", encoding="utf-8").read()
    assert "t.origin" in board, (
        "the trading screen does not read `origin` -- an adopted "
        "position and a bot entry look identical on the day he reviews")
    assert "adopted" in board


def test_the_day_summary_separates_the_two():
    """THE REASON THE MARKER EXISTS. From data/trade_memory.db:

        STRUCTURAL_LONG_BREAKOUT   n=62   +Rs  2,982
        ADOPTED_FROM_BROKER        n=19   -Rs 69,766
        MANUAL_BUY_DASHBOARD       n=52   -Rs 15,786

    Summed, that is a bot losing Rs 81,530. Split, it is a bot roughly
    flat and a book carrying positions it never chose. Those two
    readings call for opposite decisions.
    """
    board = open("dashboard/static/board.html", encoding="utf-8").read()
    assert "adoptedNet" in board and "botNet" in board, (
        "the day summary sums adopted and bot trades into one number")
