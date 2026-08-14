"""
==========================================================
The band says how far. It does not say who to trust.
==========================================================

    "10% is not issue why block? explain this"
    "we will trade NSE STOCKS, without issues in their management =
     trusted companies will be tradable"
                                    -- operator, 2 August 2026

He was right and the comment in the code was the assumption doing the
work. It read:

    "Anything banded at or below this cannot produce a tradeable ORB
     breakout -- it just locks. Surveillance (ASM/GSM) names show up
     here."

Both halves were wrong for the 10% band.

1. THE BAND IS NOT A SURVEILLANCE FLAG
   Counted on NSE's own 30 July securities list:

       band 20    2,202 scrips     18 with a GSM remark
       band  5      655            32
       band 10      201             6
       band  2       51             9

   Of the 57 names in OUR master on a 10% band, ONE carried any GSM
   remark. The band is NSE's ordinary band for a livelier non-F&O
   scrip. Surveillance lives in the REMARKS column, and nothing was
   reading it.

2. A 10% BAND DOES NOT LOCK
   Ten sessions of real bhavcopy, day range as a percentage of the
   previous close, and how often the stock actually hit its limit:

       band       median range   days locked   days with >=5% range
       No Band        2.13%          0.0%           4.4%
       20             2.95%          0.2%          17.8%
       10             3.92%          4.0%          32.3%
       5              3.59%         25.6%          32.4%
       2              2.57%         90.0%           0.0%

   A 10%-band stock is MORE volatile than the average listed name and
   gives an ORB more room, not less. It locks one day in twenty-five.

   The 5% band is the one that earns its block: ONE DAY IN FOUR it
   locks, and a locked stock held overnight on MTF is a position that
   cannot be closed.

WHAT IT WAS COSTING
-------------------
41 liquid names, including INDOMIM at Rs 2,120 crore of median daily
turnover, JSWINFRA 108, PARAS 84, ACMESOLAR 73, JUSTDIAL 66,
ICICIAMC 62. Calling those "too narrow for an ORB breakout" was
indefensible.

SO THE GOVERNANCE QUESTION IS NOW ASKED DIRECTLY
------------------------------------------------
GSM -- the exchange's Graded Surveillance Measure -- is read from the
Remarks column and blocks on its own, ahead of the band. STAGE 0
counts: it is the "shortlisted, no restriction yet" rung, and on a
book running 4X MTF overnight, being on that list at all answers "is
this a company I trust".

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.subscribe_list import MIN_PRICE_BAND_PCT, decide

LIQUID = {"series": "EQ", "close": 500.0, "turnover": 20_00_00_000,
          "turnover_days": 10}


def call(symbol, band=None, remark=None):
    return decide(symbol, bhav=dict(LIQUID), sector="CAPITAL GOODS",
                  bands={symbol: band} if band is not None else None,
                  remarks={symbol: remark} if remark else None)


# ---------------------------------------------------------------
# 1. THE BAND
# ---------------------------------------------------------------
def test_a_ten_percent_band_is_tradeable():
    """THE ONE HE ASKED ABOUT. 41 liquid names, INDOMIM among them at
    Rs 2,120 crore a day, were blocked by this."""
    ok, why = call("INDOMIM", band=10.0)
    assert ok, why


def test_a_twenty_percent_band_is_tradeable():
    assert call("RELIANCE", band=20.0)[0]


def test_no_band_at_all_is_tradeable():
    """F&O names carry no band in the securities list."""
    assert call("SBIN", band=None)[0]


def test_a_five_percent_band_is_still_blocked():
    """Not a style choice. Measured: a 5%-band stock closes locked at
    its limit ONE DAY IN FOUR, and a locked stock cannot be exited --
    which on MTF held overnight is the whole risk."""
    ok, why = call("CPPLUS", band=5.0)
    assert not ok
    assert "locks before the move finishes" in why


def test_a_two_percent_band_is_still_blocked():
    ok, why = call("SOMETHING", band=2.0)
    assert not ok and "2% price band" in why


def test_the_threshold_is_where_the_measurement_put_it():
    """If this constant moves back to 10, INDOMIM goes out again."""
    assert MIN_PRICE_BAND_PCT == 5.0


def test_the_reason_no_longer_claims_the_band_means_surveillance():
    """The old text said "(surveillance/ASM)" on every banded stock.
    On the 30 July list, 623 of the 655 five-percent names carried no
    remark at all. Saying it made the operator distrust the company
    rather than the width."""
    _, why = call("X", band=5.0)
    assert "surveillance" not in why.lower()
    assert "ASM" not in why


# ---------------------------------------------------------------
# 2. THE GOVERNANCE QUESTION, ASKED DIRECTLY
# ---------------------------------------------------------------
@pytest.mark.parametrize("stage", [
    "GSM STAGE - 0", "GSM STAGE - I", "GSM STAGE - II", "GSM STAGE - IV",
])
def test_any_gsm_stage_blocks(stage):
    """Stage 0 counts. It is "shortlisted, no restriction yet" -- and
    on a book that runs 4X MTF overnight, being on the exchange's list
    at all is the answer to "is this a company I trust"."""
    ok, why = call("SOMENAME", band=20.0, remark=stage)
    assert not ok
    assert stage in why
    assert "surveillance" in why


def test_surveillance_outranks_the_band():
    """A GSM name on a perfectly wide band is still refused, and the
    reason names the governance flag rather than the width."""
    _, why = call("SOMENAME", band=20.0, remark="GSM STAGE - II")
    assert "price band" not in why


def test_an_ordinary_stock_is_not_caught_by_the_remark_check():
    """NSE writes "-" for the 3,246 scrips with nothing against them.
    Reading that as a flag would empty the universe."""
    assert call("CLEAN", band=20.0, remark="-")[0]
    assert call("CLEAN", band=20.0, remark="")[0]
    assert call("CLEAN", band=20.0, remark=None)[0]


def test_a_missing_remarks_column_fails_open():
    """An older securities list, or a failed download, must not blank
    the universe -- the same rule the band check already follows."""
    ok, _ = decide("ANY", bhav=dict(LIQUID), sector="IT", remarks=None)
    assert ok
    ok, _ = decide("ANY", bhav=dict(LIQUID), sector="IT", remarks={})
    assert ok


# ---------------------------------------------------------------
# 3. THE MORNING TOOL CARRIES BOTH
# ---------------------------------------------------------------
def test_the_morning_tool_reads_the_remarks_column():
    src = open("tools/morning_universe.py", encoding="utf-8").read()
    assert "bands, remarks = fetch_price_bands(bhav_date)" in src
    assert "remarks=remarks" in src
    block = src[src.find("def fetch_price_bands"):]
    block = block[:block.find("def fetch_corporate_actions")]
    assert 'row.get("REMARKS")' in block
    assert "return {}, {}" in block, "it must still fail open"


def test_the_band_and_the_flag_are_two_separate_checks():
    """Reading one through the other is exactly what went wrong. If
    these ever merge again, the 10% block comes back with it."""
    src = open("core/subscribe_list.py", encoding="utf-8").read()
    block = src[src.find("def decide("):]
    block = block[:block.find("def read_master")]
    assert block.find("_SURVEILLANCE.search") < block.find("band = bands.get"), \
        "governance must be asked BEFORE the band, and separately"
