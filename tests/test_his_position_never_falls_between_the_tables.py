"""---- HIS 50 VANISHED FROM HIS OWN TABLE. 1 September 2026. ----

    "where are those trades? i want to see them in separate tables
     under TRADE TAB / in OFF = PAPER MODE table = paper trades / my
     own dhan trades table both separate"

    "thats why i asked to create a separate table in each mode"
                                                -- the operator

The two tables were built. Then this happened:

    14:58:56  SELL  MARINE      108 @  433.73   BUYING_DRIED_UP
    14:59:03  BUY   CAPLIPOINT   34 @ 2723.86   RANKED_SETUP

He already held 50 CAPLIPOINT at Dhan. The bot opened its own 34 into
the seat MARINE had just freed, so from that second both of them held
the same symbol -- and his 50 DISAPPEARED off the screen.

WHY. core/broker_sync.py sorts every symbol into three buckets:

    only_in_bot         the bot has it, he does not
    only_at_broker      he has it, the bot does not
    quantity_differs    BOTH have it, in different sizes

and dashboard/static/board.html built his table from only_at_broker
alone. The moment the bot bought the same stock the symbol moved to
quantity_differs, which nothing rendered. Two separate tables and his
position fell through the crack between them.

    broker_sync at 15:10:58, live:
        only_in_bot       INTELLECT, RAINBOW, VTL
        only_at_broker    AARTIPHARM, CORONA, DEEPAKFERT, JNPR,
                          NEOGEN, PANAMAPET, SBIN
        quantity_differs  CAPLIPOINT          <- shown nowhere

"i do not want to miss / loose any info even by mistake."

The rows also carried a bare quantity and no price, so nothing could
have drawn them as a position even once it read them.
"""

from core import broker_sync


HIS_BOOK = [{"tradingSymbol": "CAPLIPOINT", "netQty": 50,
             "costPrice": 2739.27, "productType": "MTF"},
            {"tradingSymbol": "SBIN", "netQty": 500,
             "costPrice": 800.0, "productType": "MTF"}]

# The bot's own book at the same moment: 34 CAPLIPOINT, and INTELLECT
# which he does not hold at all.
BOT_BOOK = {"CAPLIPOINT": {"qty": 34, "entry_price": 2723.86},
            "INTELLECT": {"qty": 120, "entry_price": 709.65}}


def _check():
    """The pure comparison, not the throttled REST wrapper -- the
    bucketing is what is under test."""
    return broker_sync.compare(BOT_BOOK, HIS_BOOK,
                               price_lookup=lambda s: 2700.0)


def _bucket(got, name):
    return {r["symbol"]: r for r in (got.get(name) or [])}


def test_a_stock_they_both_hold_lands_in_quantity_differs():
    """The premise. If this ever changes the table fix below is aimed
    at the wrong bucket and his position goes missing again."""
    got = _check()
    if not got.get("available"):
        return                       # no broker reader on this box
    assert "CAPLIPOINT" in _bucket(got, "quantity_differs")
    assert "CAPLIPOINT" not in _bucket(got, "only_at_broker")
    assert "CAPLIPOINT" not in _bucket(got, "only_in_bot")


def test_the_row_carries_what_a_position_row_needs():
    """It held a bare quantity. A table cannot draw a position from
    that -- no entry price, no current price, no P&L -- so even after
    the page started reading the bucket the row would have been a
    symbol and a number and nothing else."""
    got = _check()
    if not got.get("available"):
        return
    row = _bucket(got, "quantity_differs").get("CAPLIPOINT") or {}
    assert row.get("broker_qty") == 50, row
    assert row.get("avg_price"), "no entry price -- cannot be drawn"
    assert "pnl" in row and "cmp" in row, row


def test_it_reports_HIS_size_not_the_bots():
    """His table must show 50. The bot's 34 is the other table's row --
    that is the entire point of them being separate."""
    got = _check()
    if not got.get("available"):
        return
    row = _bucket(got, "quantity_differs")["CAPLIPOINT"]
    assert row["broker_qty"] == 50
    assert row["bot_qty"] == 34


def test_the_book_is_not_called_in_sync_when_they_differ():
    got = _check()
    if not got.get("available"):
        return
    assert got.get("in_sync") is False


# ------------------------------------------------- and the page reads it

def test_the_trade_tab_renders_that_bucket():
    """The half that was missing. The bucket has always been in the
    payload; nothing drew it."""
    from pathlib import Path

    src = Path("dashboard/static/board.html").read_text(encoding="utf-8")
    at = src.find("function drawTrade")
    assert at > 0
    block = src[at:at + 3000]
    assert "quantity_differs" in block, (
        "his half of a shared symbol is still shown nowhere")
    assert "only_at_broker" in block, (
        "the stocks only he holds have stopped being shown")


def test_his_row_goes_to_HIS_table():
    """Pushed into `mine`, never `bot`. A row of his in the bot's table
    is the MARINE complaint from earlier the same day, backwards."""
    from pathlib import Path

    src = Path("dashboard/static/board.html").read_text(encoding="utf-8")
    # The FIRST "quantity_differs" in the file is the note explaining
    # this fault. The loop is the one hanging off broker_sync.
    at = src.find("broker_sync || {}).quantity_differs")
    assert at > 0, "nothing reads the bucket off the payload"
    block = src[at:at + 300]
    assert "mine.push" in block, block
    assert "bot.push" not in block, block
