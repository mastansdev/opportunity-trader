"""
==========================================================
One book. Every position. Wherever you placed it.
==========================================================

    "why bot is concerned on user trading - thats his choice - make all
     work towards one goal thats it. i told u all trades must show in
     dashboard , it does not concern from where user is trading - he
     had multiple options , dhan - app, website, direct charts, Dext3
     terminal & dashboard."

    "no . i said make all even . user can trade from any place- same
     rules applicable - ONLY MTF ORDERS, 1 LAKH MAX POSITION , WHAT
     EVER QTY BELOW THE 1 LAKH USER CHOICE. if the user wants he can
     place more qty order from dhan platforms thats his choice. BUT
     DASHBOARD MUST SHOW ALL the positions irrespective of traded
     mechanism (dhan platforms / dashboard)"
                                    -- operator, 3 August 2026

WHAT WAS WRONG
--------------
Two panels. POSITIONS held what the bot had opened. AT THE BROKER held
everything else and shouted MISMATCH in red about it, every sixty
seconds, because he had used his own broker.

On the first live day that split hid two real positions in plain
sight -- YASHO 24 and ABCAPITAL 1000 were both on the page and neither
was findable, because they were in the panel that looked like an error
report rather than the one labelled POSITIONS.

Where the click happened is not a property of the trade.

THE RULE THIS FILE PINS
-----------------------
Dhan is the list. One row per holding, same columns for all. The bot's
own knowledge is attached where it exists and blank where it does not,
like any other missing field.

MEASURED, NOT ENFORCED. The house rules -- MTF only, Rs 1 lakh of
margin -- are marked on every row and block nothing. He said outright
that a bigger position from the Dhan app is his call, so the panel
reports and does not argue.

`bot_managed` survives as the one flag, and it is not a judgement about
where he traded. It answers: will anything happen to this without me?
The bot may only stop and exit what it opened.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


class Market:
    PRICES = {"YASHO": 4077.0, "URBANCO": 148.0, "SHADOWFAX": 240.0}

    def get_price(self, symbol):
        return self.PRICES.get(symbol)


def state(broker_rows):
    class Executor:
        def positions(self):
            if isinstance(broker_rows, Exception):
                raise broker_rows
            return broker_rows

    st = DashboardState.__new__(DashboardState)
    st.engine = type("E", (), {"execution": Executor()})()
    st.market_data = Market()
    return st


def at_dhan(symbol, qty, avg, product="MTF"):
    return {"tradingSymbol": symbol, "netQty": str(qty),
            "costPrice": str(avg), "productType": product}


BOT_POSITION = {"URBANCO": {"qty": 100, "entry_price": 145.52,
                            "direction": "LONG", "initial_stop": 142.12,
                            "entry_reason": "MANUAL_BUY_DASHBOARD"}}


# ---------------------------------------------------------------
# 1. EVERYTHING IS IN ONE LIST
# ---------------------------------------------------------------
def test_a_position_placed_in_the_dhan_app_is_in_the_book():
    """YASHO 24. It was on the page all day and he could not find it."""
    book = state([at_dhan("YASHO", 24, 4114.10)]).build_book({})
    assert [r["symbol"] for r in book["rows"]] == ["YASHO"]
    assert book["rows"][0]["qty"] == 24


def test_bot_placed_and_hand_placed_sit_in_the_same_table():
    book = state([at_dhan("YASHO", 24, 4114.10),
                  at_dhan("URBANCO", 100, 145.52)]).build_book(BOT_POSITION)
    assert {r["symbol"] for r in book["rows"]} == {"YASHO", "URBANCO"}
    assert all("qty" in r and "pnl" in r for r in book["rows"])


def test_the_only_difference_is_whether_the_bot_may_act():
    """Not where he traded -- whether anything happens without him."""
    book = state([at_dhan("YASHO", 24, 4114.10),
                  at_dhan("URBANCO", 100, 145.52)]).build_book(BOT_POSITION)
    by = {r["symbol"]: r for r in book["rows"]}
    assert by["URBANCO"]["bot_managed"] is True
    assert by["YASHO"]["bot_managed"] is False


def test_the_watched_ones_come_first():
    book = state([at_dhan("ZZZZ", 5, 10.0),
                  at_dhan("URBANCO", 100, 145.52)]).build_book(BOT_POSITION)
    assert book["rows"][0]["symbol"] == "URBANCO"


# ---------------------------------------------------------------
# 2. A SHORT IS A SHORT
# ---------------------------------------------------------------
def test_a_negative_quantity_survives_as_a_short():
    """SHADOWFAX -1. A row that quietly became 0 because "-1" arrived
    as a string would report an open short as flat."""
    book = state([at_dhan("SHADOWFAX", -1, 250.94)]).build_book({})
    assert book["rows"][0]["qty"] == -1


def test_a_short_in_profit_reads_as_profit():
    """Sold at 250.94, trading at 240. That is money made."""
    book = state([at_dhan("SHADOWFAX", -1, 250.94)]).build_book({})
    assert book["rows"][0]["pnl"] > 0


# ---------------------------------------------------------------
# 3. THE RULES ARE MEASURED, NEVER ENFORCED
# ---------------------------------------------------------------
def test_a_non_mtf_position_is_marked_not_refused():
    """ABCAPITAL 1000 on CNC. Flagged; still in the book, still his."""
    book = state([at_dhan("ABCAPITAL", 1000, 250.0, "CNC")]).build_book({})
    row = book["rows"][0]
    assert row["not_mtf"] is True
    assert row["qty"] == 1000, "marking it must never drop it"


def test_an_mtf_position_is_not_flagged():
    book = state([at_dhan("YASHO", 24, 4114.10, "MTF")]).build_book({})
    assert book["rows"][0]["not_mtf"] is False


def test_a_position_bigger_than_the_margin_rule_is_marked_not_blocked():
    """     "if the user wants he can place more qty order from dhan
             platforms thats his choice."   """
    book = state([at_dhan("BIG", 100000, 500.0)]).build_book({})
    row = book["rows"][0]
    assert row["over_cap"] is True
    assert row["qty"] == 100000


def test_a_normal_sized_position_is_not_marked():
    """---- "NORMAL" IS A FRACTION OF THE SLOT. 3 September 2026. ----

    This bought 24 YASHO at 4114.10 -- Rs 98,738, which was normal
    while a slot was Rs 30,000 controlling Rs 1.2 lakh at 4x. The slot
    halved to Rs 15,000 that day, so the cap is Rs 60,000 and the same
    fixture is now genuinely over it. The test was right; its fixture
    had a slot size baked into it.

    Sized off the constants now, at half the cap, so it stays "normal"
    whatever the slot becomes.
    """
    from config import MTF_LEVERAGE, MTF_MARGIN_PER_POSITION_RS
    price = 4114.10
    qty = int(MTF_MARGIN_PER_POSITION_RS * MTF_LEVERAGE / 2 / price)
    book = state([at_dhan("YASHO", qty, price)]).build_book({})
    assert book["rows"][0]["over_cap"] is False


# ---------------------------------------------------------------
# 4. WHAT MUST NEVER BE HIDDEN
# ---------------------------------------------------------------
def test_a_position_closed_elsewhere_is_shown_not_vanished():
    """The bot holds it, Dhan does not. A row that disappears with no
    explanation is how he stops trusting the table."""
    book = state([]).build_book(BOT_POSITION)
    row = book["rows"][0]
    assert row["symbol"] == "URBANCO"
    assert row["stale"] is True and row["qty"] == 0


def test_an_unreachable_broker_is_not_an_empty_book():
    """"could not ask" and "you hold nothing" are different sentences,
    and only one of them lets him walk away from the screen."""
    book = state(RuntimeError("connection reset")).build_book(BOT_POSITION)
    assert book["source"] == "bot only"
    assert "could not read Dhan" in book["note"]
    assert len(book["rows"]) == 1


def test_paper_mode_shows_the_bot_book_and_says_so():
    st = DashboardState.__new__(DashboardState)
    st.engine = type("E", (), {"execution": object()})()
    st.market_data = Market()
    book = st.build_book(BOT_POSITION)
    assert book["source"] == "bot only"


def test_a_missing_price_gives_no_pnl_rather_than_zero():
    """A position reported flat when it is down 3% is worse than one
    reported unknown -- the first is believed."""
    book = state([at_dhan("NOPRICE", 10, 100.0)]).build_book({})
    assert book["rows"][0]["pnl"] is None
    assert book["rows"][0]["pnl_pct"] is None


# ---------------------------------------------------------------
# 5. IT REACHES THE PAGE, AND THE SCOLDING IS GONE
# ---------------------------------------------------------------
def test_the_log_no_longer_calls_a_hand_placed_trade_a_fault():
    """It warned every sixty seconds that the books "DO NOT MATCH"
    because he had bought something from the Dhan app."""
    src = open("core/broker_sync.py", encoding="utf-8").read()
    # The phrase survives in the comment that records why it went. Match
    # the CALL, not the history of it -- the same distinction that
    # tripped tests/test_single_instance.py.
    assert 'warn("[SYNC] The bot\'s book and Dhan DO NOT MATCH.")' not in src
    block = src[src.find("A TRADE HE PLACED IS NOT A FAULT"):]
    assert "diagnostic(" in block, (
        "a position opened outside the bot is noted quietly, not warned "
        "about")
    assert "The bot's own book is behind Dhan" in block, (
        "the bot's OWN book being stale is still worth a warning -- that "
        "one is the bot's problem, not his")
