"""
==========================================================
A hand-placed position must be TRACKED, not just noticed
==========================================================

31 July 2026. SEBI's static-IP rule blocked API order placement, so
the operator placed a trade by hand in the Dhan app. The new panel
found it:

    AT THE BROKER                        MISMATCH
    ABCAPITAL   1   --   You placed this yourself.

His reply was the whole point in four words:

    "?? no tracking of the position"

Right. Knowing a position EXISTS is not knowing how it is doing. Dhan
sends the average cost on every position row and compare() was
throwing it away, so the panel could say "you own this" and nothing
else -- no entry, no live price, no P&L.

WHAT THIS FILE PROTECTS
-----------------------
Mostly one rule, stated three ways: UNKNOWN IS NEVER ZERO.

A missing entry price, a dead feed, a symbol the bot never subscribed
to -- each of those must produce None, which the dashboard renders as
a dash. Not 0.0, which renders as a confident, wrong, flat P&L. The
first is ignored; the second is believed.

Author : H&M Opportunity Trader
==========================================================
"""

from core.broker_sync import compare


def _dhan(symbol="ABCAPITAL", qty=1, cost=268.0, product="MTF",
          key="costPrice"):
    return [{"tradingSymbol": symbol, "netQty": qty, key: cost,
             "productType": product}]


# ---------------------------------------------------------------
# 1. THE POSITION IS MARKED TO MARKET
# ---------------------------------------------------------------
def test_a_hand_placed_long_shows_entry_price_and_pnl():
    result = compare({}, _dhan(qty=1, cost=268.0),
                     price_lookup=lambda s: 271.0)
    row = result["only_at_broker"][0]
    assert row["symbol"] == "ABCAPITAL"
    assert row["avg_price"] == 268.0
    assert row["cmp"] == 271.0
    assert round(row["pnl"], 2) == 3.00
    assert round(row["pnl_pct"], 4) == round((3.0 / 268.0) * 100, 4)


def test_pnl_scales_with_quantity():
    """One share and a hundred shares of the same move are not the same
    number, and the panel is read as rupees."""
    result = compare({}, _dhan(qty=100, cost=268.0),
                     price_lookup=lambda s: 271.0)
    assert round(result["only_at_broker"][0]["pnl"], 2) == 300.00


def test_a_losing_position_is_negative():
    result = compare({}, _dhan(cost=268.0), price_lookup=lambda s: 260.0)
    row = result["only_at_broker"][0]
    assert row["pnl"] < 0
    assert row["pnl_pct"] < 0


def test_a_short_profits_when_the_price_falls():
    """Dhan reports a short as a negative net quantity. (260-268) * -1
    is +8: the P&L falls out correctly on its own, but the PERCENTAGE
    would read -2.99% without the sign flip, which is exactly backwards
    on a winning trade."""
    result = compare({}, _dhan(qty=-1, cost=268.0),
                     price_lookup=lambda s: 260.0)
    row = result["only_at_broker"][0]
    assert row["pnl"] > 0
    assert row["pnl_pct"] > 0


def test_the_product_is_reported():
    """MTF carries interest and is squared off under different rules
    than delivery. Worth a column."""
    assert compare({}, _dhan(product="MTF"))["only_at_broker"][0][
        "product"] == "MTF"


# ---------------------------------------------------------------
# 2. UNKNOWN IS NEVER ZERO
# ---------------------------------------------------------------
def test_no_price_feed_means_no_pnl_not_a_flat_pnl():
    """The single most important assertion here. A position quietly
    reported as flat when it is down 3% is worse than one reported as
    unknown, because the first one is believed."""
    row = compare({}, _dhan())["only_at_broker"][0]
    assert row["cmp"] is None
    assert row["pnl"] is None
    assert row["pnl_pct"] is None


def test_a_symbol_the_feed_does_not_know_gives_none():
    row = compare({}, _dhan(), price_lookup=lambda s: None
                  )["only_at_broker"][0]
    assert row["pnl"] is None


def test_a_broken_price_lookup_does_not_break_the_panel():
    """This runs inside the dashboard refresh. An exception here would
    blank the whole page over one unknown symbol."""

    def explode(symbol):
        raise RuntimeError("feed is down")

    row = compare({}, _dhan(), price_lookup=explode)["only_at_broker"][0]
    assert row["pnl"] is None
    assert row["broker_qty"] == 1


def test_a_missing_cost_price_gives_none_not_infinity():
    """Without an entry price there is no percentage to compute, and
    dividing by a zero cost would raise inside the refresh."""
    rows = [{"tradingSymbol": "ABCAPITAL", "netQty": 1, "costPrice": 0}]
    row = compare({}, rows, price_lookup=lambda s: 271.0)["only_at_broker"][0]
    assert row["avg_price"] is None
    assert row["pnl"] is None


# ---------------------------------------------------------------
# 3. DHAN'S FIELD NAMES VARY
# ---------------------------------------------------------------
def test_every_spelling_of_the_cost_field_is_read():
    """Field name differs by account and product. A miss here shows as
    a dash where a real number exists -- silent, and wrong."""
    for key in ("costPrice", "buyAvg", "buyAvgPrice", "averagePrice",
                "avgPrice", "netAvgPrice"):
        row = compare({}, _dhan(cost=268.0, key=key))["only_at_broker"][0]
        assert row["avg_price"] == 268.0, f"{key} was not read"


# ---------------------------------------------------------------
# 4. NOTHING ELSE CHANGED
# ---------------------------------------------------------------
def test_the_bot_is_never_told_it_owns_a_hand_placed_position():
    """The panel reports. It must not quietly adopt the position into
    the bot's book -- that book drives stops, exits and sizing."""
    bot = {}
    compare(bot, _dhan(), price_lookup=lambda s: 271.0)
    assert bot == {}


def test_a_matching_book_is_still_in_sync():
    result = compare({"ABCAPITAL": {"qty": 1, "direction": "LONG"}},
                     _dhan(qty=1))
    assert result["in_sync"] is True
    assert result["only_at_broker"] == []


def test_bot_holds_what_dhan_does_not_is_still_an_alarm():
    result = compare({"SPORTKING": {"qty": 5, "direction": "LONG"}}, [])
    assert result["in_sync"] is False
    assert result["only_in_bot"][0]["symbol"] == "SPORTKING"


def test_quantity_mismatch_is_still_reported():
    result = compare({"ABCAPITAL": {"qty": 5, "direction": "LONG"}},
                     _dhan(qty=1))
    assert result["quantity_differs"][0]["broker_qty"] == 1
    assert result["quantity_differs"][0]["bot_qty"] == 5
