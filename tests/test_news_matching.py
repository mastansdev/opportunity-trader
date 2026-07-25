"""
Decision-correctness tests for News Bot Stage 2 (matching).

Runs against the REAL, fully-verified master_stocks.csv (not a
fixture) -- the whole point of Stage 2 is that it matches
against the actual 750-stock universe, so the test should prove
it does that correctly, not against a toy substitute.
"""

import pytest

from core.master_loader import MasterLoader
from news_bot.matching import NewsMatcher
from news_bot.models import NewsItem


@pytest.fixture(scope="module")
def matcher():
    loader = MasterLoader()
    loader.load()
    return NewsMatcher(loader)


def _item(title, summary="", known_symbol=""):
    return NewsItem(
        source="TEST",
        title=title,
        summary=summary,
        link="https://example.com/x",
        published_raw="",
        guid="g1",
        known_symbol=known_symbol,
    )


def test_symbol_mention_matches_company_tier(matcher):
    result = matcher.match(_item("RELIANCE shares rally after Q1 results"))

    assert not result.is_dummy
    assert "RELIANCE" in result.matched_symbols
    reliance_hits = [m for m in result.matches if m.symbol == "RELIANCE"]
    assert any(m.tier == "COMPANY" for m in reliance_hits)


def test_full_company_name_matches_company_tier(matcher):
    result = matcher.match(
        _item("Reliance Industries announces new retail expansion plan")
    )

    assert "RELIANCE" in result.matched_symbols
    hit = next(m for m in result.matches if m.symbol == "RELIANCE")
    assert hit.tier == "COMPANY"
    assert hit.field == "COMPANY_NAME"


def test_commodity_term_matches_broad_tier_across_many_stocks(matcher):
    result = matcher.match(
        _item("Crude oil prices surge on Middle East supply concerns")
    )

    assert not result.is_dummy
    assert "RELIANCE" in result.matched_symbols
    # Crude oil exposure is shared by many companies in the
    # universe (refiners, paints, chemicals) -- this must be a
    # broad, multi-stock match, not a single-company one.
    assert len(result.matched_symbols) >= 5
    reliance_hit = next(m for m in result.matches if m.symbol == "RELIANCE")
    assert reliance_hit.tier == "BROAD"
    assert reliance_hit.field == "COMMODITY_EXPOSURE"


def test_irrelevant_headline_is_dummy(matcher):
    result = matcher.match(
        _item(
            "Local weather bureau forecasts heavy monsoon rainfall "
            "across coastal districts this weekend"
        )
    )

    assert result.is_dummy
    assert result.matched_symbols == []


def test_sector_term_matches_it_services_companies(matcher):
    result = matcher.match(
        _item("IT services sector sees strong hiring demand this quarter")
    )

    assert "TCS" in result.matched_symbols


def test_matched_symbols_are_deduped_and_sorted(matcher):
    # A headline that hits both the SYMBOL and full COMPANY NAME
    # for the same stock must not produce duplicate symbols in
    # matched_symbols.
    result = matcher.match(
        _item("Reliance Industries Ltd (RELIANCE) posts record quarterly revenue")
    )

    symbols = [m.symbol for m in result.matches if m.symbol == "RELIANCE"]
    assert len(symbols) >= 2  # matched via both SYMBOL and COMPANY_NAME fields
    assert result.matched_symbols.count("RELIANCE") == 1  # but deduped in the property
    assert result.matched_symbols == sorted(result.matched_symbols)


def test_known_symbol_from_exchange_filing_is_trusted_directly(matcher):
    # An NSE announcement item where the headline text alone
    # wouldn't obviously name the company -- known_symbol must
    # still produce a confirmed COMPANY-tier match, because it's
    # ground truth from the exchange, not a text guess.
    result = matcher.match(
        _item(
            "Intimation under Regulation 30 of SEBI LODR Regulations",
            summary="Updates",
            known_symbol="TCS",
        )
    )

    assert not result.is_dummy
    assert result.matched_symbols == ["TCS"]
    hit = result.matches[0]
    assert hit.tier == "COMPANY"
    assert hit.field == "EXCHANGE_FILING"


def test_known_symbol_not_in_universe_is_ignored_not_trusted_blindly(matcher):
    # A bad/unknown symbol from a feed must not create a fake
    # match -- it's validated against the real master DB first.
    result = matcher.match(
        _item("Some filing text", known_symbol="NOTAREALSYMBOL")
    )

    assert result.matched_symbols == []
