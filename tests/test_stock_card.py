"""
Tests for core/stock_card.py -- "recall the memory of any stock".

    "dashboard must contain all info from bot. recall the memory of
     any stock on demand"
    "everything that bot knows must shown in dashboard"
                                        -- operator, 29 July 2026

A principle, not a feature. Four times in one session the answer to his
question was "the bot knows, the screen doesn't":

    the results calendar   52 companies reporting, invisible
    entry reasons          why a breakout was refused, invisible
    circuit bands          polled every 3 seconds, invisible
    what a company does    in master_stocks.csv for all 973, invisible

The rules this module is held to:

    1. It GATHERS, it does not compute. A second implementation of a
       number already computed elsewhere would eventually disagree with
       the first, and then the dashboard would be confidently wrong in
       a brand new way.

    2. Every source is optional and every failure is local. A missing
       feed produces a missing SECTION -- never a wrong number, never
       an exception, and never the loss of the other six sections.
"""

import pytest

from core.stock_card import StockCard, _split


class _Master:
    def __init__(self, row=None):
        self.row = row

    def get_by_symbol(self, symbol):
        return self.row if symbol == "KAYNES" else None


KAYNES_ROW = {
    "COMPANY NAME": "KAYNES TECHNOLOGY INDIA LIMITED",
    "SECTOR": "CAPITAL GOODS",
    "INDUSTRY": "ELECTRONICS MANUFACTURING",
    "CORE BUSINESS": "ELECTRONICS MANUFACTURING AND DESIGN SERVICES",
    "BUSINESS_TYPE": "MANUFACTURER",
    "OWNERSHIP": "PRIVATE",
    "COMMODITY_EXPOSURE": "NONE",
    "ECONOMIC_SENSITIVITY": "EXPORT ORIENTED | IMPORT DEPENDENT",
    "THEMES": "EMS | SEMICONDUCTORS | DEFENCE ELECTRONICS",
    "SUBSCRIBE": "YES",
    "SUBSCRIBE_REASON": "",
}


class _Engine:
    def __init__(self, quote=None, position=None):
        self.quote = quote or {}
        self.open_positions = {"KAYNES": position} if position else {}
        self.entry_blocked = {}
        self.breakout_feed = None
        self.candle_engine = None

    def get_circuit_snapshot(self):
        return {"KAYNES": self.quote} if self.quote else {}


QUOTE = {"last_price": 3660.20, "prev_close": 3227.70, "open": 3275.00,
         "high": 3684.70, "low": 3274.70, "volume": 412000,
         "upper_circuit_limit": 3876.00, "lower_circuit_limit": 3172.00}


# ---------------------------------------------------------------
# What the company does -- in the master file, never on screen
# ---------------------------------------------------------------

def test_it_says_what_the_business_actually_is():
    card = StockCard(master_loader=_Master(KAYNES_ROW)).build("KAYNES")
    business = card["business"]
    assert business["name"] == "KAYNES TECHNOLOGY INDIA LIMITED"
    assert "ELECTRONICS" in business["does"]
    assert business["sector"] == "CAPITAL GOODS"


def test_pipe_separated_lists_become_real_lists():
    """The master stores 'A | B | C'. A dashboard should not have to
    know that."""
    card = StockCard(master_loader=_Master(KAYNES_ROW)).build("KAYNES")
    assert card["business"]["themes"] == [
        "EMS", "SEMICONDUCTORS", "DEFENCE ELECTRONICS"]
    assert card["business"]["economic_sensitivity"] == [
        "EXPORT ORIENTED", "IMPORT DEPENDENT"]


def test_a_symbol_that_does_not_exist_is_reported_not_invented():
    card = StockCard(master_loader=_Master(KAYNES_ROW)).build("NOTREAL")
    assert card["found"] is False


def test_an_empty_search_is_survivable():
    assert StockCard().build("")["found"] is False
    assert StockCard().build(None)["found"] is False


def test_the_search_is_case_and_space_insensitive():
    card = StockCard(master_loader=_Master(KAYNES_ROW)).build("  kaynes ")
    assert card["found"] is True


# ---------------------------------------------------------------
# Circuit bands -- polled every 3 seconds, shown nowhere
# ---------------------------------------------------------------

def test_the_circuit_bands_are_on_the_card():
    """SMLMAH was bought at its upper circuit and the operator could
    not see the band anywhere on the dashboard."""
    card = StockCard(engine=_Engine(QUOTE)).build("KAYNES")
    assert card["price"]["upper_circuit"] == 3876.00
    assert card["price"]["lower_circuit"] == 3172.00


def test_how_far_from_each_circuit_is_computed():
    """The number that decides whether the bot may enter, and whether
    a long is at its best or its worst."""
    card = StockCard(engine=_Engine(QUOTE)).build("KAYNES")
    assert card["price"]["pct_to_upper"] == pytest.approx(5.9, abs=0.1)
    assert card["price"]["pct_to_lower"] == pytest.approx(13.3, abs=0.1)


def test_the_percent_change_uses_the_previous_close():
    """NSE's own convention. The operator's standing rule: do not
    invent our own formula."""
    card = StockCard(engine=_Engine(QUOTE)).build("KAYNES")
    assert card["price"]["change_pct"] == pytest.approx(13.4, abs=0.1)


def test_missing_circuit_data_reads_as_missing_not_zero():
    quote = dict(QUOTE, upper_circuit_limit=0, lower_circuit_limit=0)
    card = StockCard(engine=_Engine(quote)).build("KAYNES")
    assert card["price"]["upper_circuit"] is None
    assert "pct_to_upper" not in card["price"]


# ---------------------------------------------------------------
# The position you hold right now
# ---------------------------------------------------------------

def test_a_held_position_shows_with_its_stop():
    engine = _Engine(QUOTE, position={
        "qty": 59, "entry_price": 3338.00, "entry_time": "09:32",
        "entry_reason": "STRUCTURAL_LONG_BREAKOUT",
        "initial_stop": 3254.55, "atr_stop": 3254.55})
    card = StockCard(engine=engine).build("KAYNES")
    assert card["position"]["qty"] == 59
    assert card["position"]["stop"] == 3254.55
    assert card["position"]["yours"] is False


def test_a_manual_position_is_marked_as_yours():
    engine = _Engine(QUOTE, position={
        "qty": 59, "entry_price": 3338.00,
        "entry_reason": "MANUAL_BUY_DASHBOARD", "initial_stop": 3254.55})
    assert StockCard(engine=engine).build("KAYNES")["position"]["yours"] is True


def test_nothing_held_is_None_not_an_empty_shell():
    assert StockCard(engine=_Engine(QUOTE)).build("KAYNES")["position"] is None


# ---------------------------------------------------------------
# One broken source must never cost the other six
# ---------------------------------------------------------------

def test_a_source_that_raises_loses_only_its_own_section():
    class Exploding:
        def get_by_symbol(self, symbol):
            raise RuntimeError("master file corrupt")

    card = StockCard(master_loader=Exploding(),
                     engine=_Engine(QUOTE)).build("KAYNES")
    assert card["business"] is None          # the broken one
    assert card["price"]["last"] == 3660.20  # the others survive


def test_no_sources_at_all_returns_a_shape_not_an_exception():
    card = StockCard().build("KAYNES")
    assert card["found"] is False
    assert set(card) >= {"business", "price", "today", "results",
                         "news", "history", "position"}


def test_junk_numbers_never_reach_the_screen():
    quote = {"last_price": "not a number", "prev_close": None,
             "upper_circuit_limit": "x"}
    card = StockCard(engine=_Engine(quote)).build("KAYNES")
    assert card["price"] is None


# ---------------------------------------------------------------
# It gathers, it does not calculate
# ---------------------------------------------------------------

def test_it_does_not_reimplement_any_grade_or_score():
    """A second implementation of a number computed elsewhere would
    eventually disagree with the first, and the dashboard would be
    confidently wrong in a brand new way."""
    import ast
    tree = ast.parse(open("core/stock_card.py", encoding="utf-8").read())
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    for banned in ("grade", "score", "rank", "classify", "decide"):
        assert not any(banned in name.lower() for name in defined)


def test_split_handles_every_shape_of_junk():
    assert _split(None) == []
    assert _split("") == []
    assert _split("  |  | ") == []
    assert _split("SOLO") == ["SOLO"]


# ---------------------------------------------------------------
# Your own history -- found broken by running the preview
# ---------------------------------------------------------------

class _TradeMemory:
    """The REAL shape: a LIST of rows with a "key" field, not a dict
    keyed by symbol. The first version of _history called .get() on
    this, the try swallowed the AttributeError, and every stock read
    "never traded" -- silently, for every symbol, forever."""

    def by_symbol(self, min_trades=1):
        return [
            {"key": "COFORGE", "trades": 2, "wins": 2, "win_rate": 100.0,
             "total_pnl": 1437.80, "avg_pnl": 718.90},
            {"key": "CUB", "trades": 2, "wins": 0, "win_rate": 0.0,
             "total_pnl": -3011.40, "avg_pnl": -1505.70},
        ]


def test_your_own_history_in_a_stock_is_found():
    card = StockCard(trade_memory=_TradeMemory()).build("COFORGE")
    assert card["history"]["trades"] == 2
    assert card["history"]["wins"] == 2
    assert card["history"]["pnl"] == pytest.approx(1437.80)


def test_a_losing_history_is_shown_as_it_is():
    card = StockCard(trade_memory=_TradeMemory()).build("CUB")
    assert card["history"]["pnl"] == pytest.approx(-3011.40)
    assert card["history"]["win_rate"] == 0.0


def test_a_stock_never_traded_reads_as_never_traded():
    assert StockCard(trade_memory=_TradeMemory()).build("KAYNES")["history"] is None


# ---------------------------------------------------------------
# NaN -- one empty cell, every search broken
# ---------------------------------------------------------------

def test_an_empty_master_cell_never_reaches_the_json_encoder():
    """pandas reads an empty cell as the float NaN. NaN IS TRUTHY, so
    `row.get(...) or None` sails straight past it, and JSON refuses
    NaN outright -- refusing the WHOLE payload, not the one field.
    /api/stock/<symbol> returned 500 for every symbol in the universe
    because SUBSCRIBE_REASON is blank for all of them."""
    import json
    row = dict(KAYNES_ROW, SUBSCRIBE_REASON=float("nan"),
               INDUSTRY=float("nan"), OWNERSHIP=float("nan"))
    card = StockCard(master_loader=_Master(row)).build("KAYNES")
    assert card["business"]["not_tradeable_because"] is None
    assert card["business"]["industry"] is None
    json.dumps(card, allow_nan=False)      # would raise before the fix


def test_the_literal_string_nan_is_also_treated_as_empty():
    """A CSV round-trip turns the float NaN into the text "nan", which
    would otherwise be printed on screen as a company's industry."""
    row = dict(KAYNES_ROW, INDUSTRY="nan", OWNERSHIP="NaN")
    card = StockCard(master_loader=_Master(row)).build("KAYNES")
    assert card["business"]["industry"] is None
    assert card["business"]["ownership"] is None


def test_a_nan_list_field_becomes_an_empty_list_not_the_word_nan():
    row = dict(KAYNES_ROW, THEMES=float("nan"))
    card = StockCard(master_loader=_Master(row)).build("KAYNES")
    assert card["business"]["themes"] == []


def test_a_trade_memory_that_returns_junk_is_survivable():
    class Junk:
        def by_symbol(self, min_trades=1):
            return "not a list"
    StockCard(trade_memory=Junk()).build("COFORGE")
