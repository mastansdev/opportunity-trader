"""
==========================================================
The same story, carried by two channels
==========================================================

    "Duplicates of data is not acceptable at all"
                                            -- the operator

The message store is clean: channel + post id is the primary key and
nothing is stored twice. The duplicates were downstream, where a
message becomes a REASON.

_already_have() had two rules. The headline must match word for word
after normalising, or the two must name the same rupee figure. Two
channels carrying one announcement do neither:

    RedboxGlobal India  "ACME SOLAR: CO RECEIVES LOI FOR 300 MW, AT A
                         TARIFF OF RS. 6.00 PER KWH..."
    Day Trader Telugu   "ACME SOLAR: CO RECEIVES LOI FOR 300 MW, AT A
                         TARIFF OF RS. 6.00 PER KWH..."

One event, transcribed twice, no crore figure in either. Counted on
data/stock_events.db, 25 July to 5 September: 349 events are one
announcement stored more than once, and 146 of them came from a
DIFFERENT channel.

    NEWS            96      MARKET_ANSWER   65
    AI_VERDICT      72      RESULT          24
    CONCALL         65      ORDER           17

_same_story() was written for exactly this on 29 August and was only
ever used to tidy the DISPLAY. That is the fault this codebase keeps
producing -- machinery built, and never called on the path that
matters. trading_gate, surge(), MOVE_DIED, refused_symbols, and now
this. It is called on the write path now.

WHAT MUST NOT HAPPEN: two REAL stories about one stock on one day
being merged into one. That would cost an event, and a missing event
costs a trade while a duplicate costs a row. The guard against it is
already inside _same_story(): when BOTH headlines name money it
requires the SAME money.

    26 August   Ather, Rs 960 cr
    28 August   Ather, Rs 1,758 cr

Two figures, two stories, and a text rule that merged them would be
worse than counting repeats. Verified across every event since 25
July: of the 349 suppressed, not one is a second real story.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import tempfile

import pytest

from core.stock_events import StockEvents


@pytest.fixture()
def store():
    return StockEvents(db_path=os.path.join(tempfile.mkdtemp(),
                                            "stock_events.db"))


AT = "2026-08-28T09:30:00"


# ------------------------------------------------------------------
# the duplicate that was getting through
# ------------------------------------------------------------------

def test_the_same_story_from_two_channels_is_stored_once(store):
    """ACME SOLAR, 28 August. Verbatim from the store."""
    head = ("ACME SOLAR: CO RECEIVES LOI FOR 300 MW, AT A TARIFF OF "
            "RS. 6.00 PER KWH FOR ENTIRE PPA TENURE")
    assert store.remember(symbol="ACMESOLAR", at=AT, kind="NEWS",
                          headline=head, source="RedboxGlobal India")
    assert not store.remember(symbol="ACMESOLAR", at=AT, kind="NEWS",
                              headline=head,
                              source="Day Trader Telugu")
    assert len(store.for_symbol("ACMESOLAR")) == 1


def test_the_same_story_in_different_words_is_stored_once(store):
    """One block deal, two transcriptions, neither naming a crore
    figure the other names."""
    a = ("BLOCK DEAL IN ASTER DM HEALTHCARE Centella Mauritius Holdings "
         "TPG Likely To Sell 7.2 percent stake")
    b = ("Aster DM Centella Mauritius Holdings Ltd to sell a 7.2 percent "
         "stake in a block deal")
    assert store.remember(symbol="ASTERDM", at=AT, kind="NEWS",
                          headline=a, source="Day Trader Telugu")
    assert not store.remember(symbol="ASTERDM", at=AT, kind="NEWS",
                              headline=b, source="RedboxGlobal India")


# ------------------------------------------------------------------
# and what must still get through
# ------------------------------------------------------------------

def test_two_different_orders_on_one_day_both_survive(store):
    """The Ather case, which is why _same_story compares the MONEY
    before it compares the words."""
    assert store.remember(
        symbol="ATHERENERG", at="2026-08-26T10:00:00", kind="ORDER",
        headline="To buy additional stake in Ather Energy for 960 cr",
        source="Day Trader Telugu", value_cr=960.0)
    assert store.remember(
        symbol="ATHERENERG", at="2026-08-26T14:00:00", kind="ORDER",
        headline="To buy additional stake in Ather Energy for 1,758 cr",
        source="Day Trader Telugu", value_cr=1758.0)
    assert len(store.for_symbol("ATHERENERG")) == 2


def test_a_different_story_about_the_same_stock_survives(store):
    assert store.remember(
        symbol="HAL", at=AT, kind="ORDER",
        headline="HAL wins order worth 2,205 crore from Ministry of Defence",
        source="x")
    assert store.remember(
        symbol="HAL", at=AT, kind="NEWS",
        headline="HAL appoints a new Chief Financial Officer with effect "
                 "from October",
        source="x")
    assert len(store.for_symbol("HAL")) == 2


def test_the_same_headline_on_a_different_day_survives(store):
    """A recurring announcement is a new event each time it happens.
    _already_have only looks at the same DAY."""
    head = "Monthly business update: total sales 1,175 units"
    assert store.remember(symbol="SMLMAH", at="2026-08-01T10:00:00",
                          kind="NEWS", headline=head, source="x")
    assert store.remember(symbol="SMLMAH", at="2026-09-01T10:00:00",
                          kind="NEWS", headline=head, source="x")
    assert len(store.for_symbol("SMLMAH")) == 2


# ------------------------------------------------------------------
# the wiring -- machinery that is actually called
# ------------------------------------------------------------------

def test_the_write_path_calls_the_story_matcher():
    """_same_story() spent a fortnight tidying the display while the
    duplicates went into the store."""
    import io
    src = io.open("core/stock_events.py", encoding="utf-8").read()
    guard = src[src.find("def _already_have"):
                src.find("def _query")]
    assert "self._same_story(" in guard, \
        "the duplicate guard does not use the story matcher"
