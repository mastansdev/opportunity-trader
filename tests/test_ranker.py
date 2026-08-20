"""
==========================================================
The best stock of the day, not the first to trigger
==========================================================

    "it must not follow old logic of first come = first buy"
    "it must take the best stock pick of the day"
    "any specific stock is out winning others; why ? whats the
     supporting factor to the rally in stock?"
                                    -- operator, 4 August 2026

THREE BUGS THE FIRST REAL RUN EXPOSED
-------------------------------------
Run against the operator's actual snapshot -- 100 movers -- the first
version produced a ranked list that LOOKED right and was not:

  1. Every row said "sector unknown". sector_gainers is not always in
     the payload, so `excess` was None, and the gate written as

         if excess is not None and excess < MIN_EXCESS_PCT: refuse

     never fired once. The entire point of the module -- is this stock
     beating its own sector -- was silently skipped and the ranking ran
     on volume and mechanism alone.

  2. MUTHOOTFIN ranked FIRST as a SELL, carrying the reason "Strong Q1
     FY27 AUM and PAT growth signals...". A bullish mechanism
     justifying a short. The direction of the reason was never checked
     against the direction of the trade.

  3. INDGN ranked sixth on the mechanism "matched on: INDGN" -- the
     matcher reporting its own lookup, not a reason anything happened.

None of the three would have failed a test that only asked "does it
return rows".

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core import ranker
from core.ranker import rank, sector_moves, should_swap, volume_ratio


# 3,000,000 shares at Rs 100 is Rs 30 crore traded, against a default
# ADV of Rs 10 crore -- 3.0x its normal day, which clears
# MIN_VOLUME_RATIO.
#
# It has been wrong twice, the same way. The first version used Rs 10
# crore against Rs 200 crore -- 0.05x -- and every candidate was
# refused for "no volume behind it". The second used 2,000,000 shares
# for 2.0x, which cleared the gate at 1.5 and stopped clearing it on
# 20 August when MIN_VOLUME_RATIO was raised to 2.5 on measurement.
#
# Both times the FIXTURE was wrong and the gate was right, and both
# times the failure looked like the ranker had broken. A fixture that
# sits a hair above a threshold will fail every time that threshold
# moves; 3.0x leaves room.
def mover(symbol, pct, sector="IT", volume=3_000_000, ltp=100.0,
          recent=None):
    return {"symbol": symbol, "change_pct": pct, "sector": sector,
            "volume": volume, "ltp": ltp, "recent_pct": recent}


def reason(text="Order win of Rs 500 cr lifts the order book",
           weight=0.7, direction=None):
    return {"text": text, "weight": weight, "direction": direction}


def run(movers, mech=None, adv=10.0, **kw):
    return rank(movers,
                mechanism_of=(mech if mech is not None
                              else (lambda s: reason())),
                adv_of=(lambda s: adv), **kw)


# ---------------------------------------------------------------
# 1. IT RANKS. IT DOES NOT TAKE THE FIRST ONE.
# ---------------------------------------------------------------
def test_the_best_wins_regardless_of_order():
    """     "it must not follow old logic of first come = first buy"

    The weaker candidate is FIRST in the list, as it would be if it
    ticked first."""
    rows = [mover("WEAK", 1.6, "IT"), mover("BEST", 9.0, "IT"),
            mover("MID", 3.0, "IT")]
    got = run(rows)
    assert [c["symbol"] for c in got["rows"]][0] == "BEST"


def test_every_candidate_carries_a_score_and_a_sentence():
    got = run([mover("A", 6.0), mover("B", 2.0), mover("C", 3.0)])
    for c in got["rows"]:
        assert isinstance(c["score"], float)
        assert c["why"] and len(c["why"]) > 10


# ---------------------------------------------------------------
# 2. BEATING THE SECTOR IS THE CORE TEST -- AND IT MUST FIRE
# ---------------------------------------------------------------
def test_a_stock_moving_with_its_sector_is_not_a_candidate():
    """Up 3% in a sector up 3% has done nothing."""
    rows = [mover(f"S{i}", 3.0, "IT") for i in range(5)]
    assert run(rows)["rows"] == []


def test_the_sector_average_is_computed_when_the_block_is_missing():
    """THE BUG. Without this every row read "sector unknown", excess
    was None, and the gate never fired -- on the real snapshot, all 100
    of them."""
    rows = [mover("LEAD", 9.0, "IT")] + [mover(f"P{i}", 1.5, "IT")
                                         for i in range(4)]
    got = sector_moves(None, rows)
    assert "IT" in got
    # THE MEDIAN, not the mean. 4 August 2026 -- the mean here is 3.0,
    # dragged up by LEAD itself, so LEAD was measured against a bar it
    # had built. The median is 1.5: what an IT stock with no news of
    # its own did. See ranker._baseline().
    assert got["IT"] == 1.5


def test_a_results_day_cluster_is_not_hidden_by_its_own_sector():
    """     "MOREPEN LAB HIT CIRCUIT , BASF , STYRENIX, ALKYLAMINE ,
             got good results none of them were shown by bot"

    BASF, STYRENIX and ALKYLAMINE are all CHEMICALS. On 4 August all
    three rose hard on their own results, the sector MEAN became 8.5%,
    and every one of them failed "not beating its sector" -- the
    ranker returned an empty list on the best day of the week.

    Most of a sector does not report on any given day. The baseline has
    to be those quiet names, not the reporters."""
    loud = [mover(s, p, "CHEMICALS") for s, p in
            [("BASF", 9.0), ("STYRENIX", 12.0), ("ALKYLAMINE", 7.0)]]
    quiet = [mover(f"Q{i}", 0.3, "CHEMICALS") for i in range(8)]
    assert sector_moves(None, loud + quiet)["CHEMICALS"] == 0.3

    got = run(loud + quiet, adv=10.0,
              mech=lambda s: reason("Q1 results beat", direction="POSITIVE"))
    named = [c["symbol"] for c in got["rows"]]
    for symbol in ("BASF", "STYRENIX", "ALKYLAMINE"):
        assert symbol in named, f"{symbol} was hidden again"
    # And the biggest mover leads.
    assert named[0] == "STYRENIX"


def test_one_stock_is_not_a_sector():
    """A sector average built from one name compares a stock to
    itself, and the excess is zero by construction."""
    assert sector_moves(None, [mover("ONLY", 9.0, "NICHE")]) == {}
    assert ranker.MIN_SECTOR_PEERS >= 3


def test_falling_while_the_sector_rises_is_outperformance_too():
    """LATENTVIEW: down 5.7% while IT was up 4.3%. No first-come rule
    would ever find that."""
    rows = [mover("FALLER", -5.7, "IT")] + [mover(f"P{i}", 4.3, "IT")
                                            for i in range(4)]
    got = run(rows)
    top = got["rows"][0]
    assert top["symbol"] == "FALLER"
    assert top["action"] == "SELL"
    assert top["excess_pct"] > 5


def test_the_supplied_sector_block_wins_when_it_is_there():
    rows = [mover("A", 5.0, "IT")] + [mover(f"P{i}", 5.0, "IT")
                                      for i in range(4)]
    gl = {"sector_gainers": [{"sector": "IT", "avg_change_pct": 0.2}]}
    got = run(rows, gainers_losers=gl)
    assert got["rows"][0]["sector_pct"] == 0.2


# ---------------------------------------------------------------
# 3. THE REASON MUST POINT THE SAME WAY AS THE TRADE
# ---------------------------------------------------------------
def test_a_bullish_reason_cannot_justify_a_short():
    """MUTHOOTFIN ranked FIRST as a SELL on "Strong Q1 FY27 AUM and PAT
    growth". The bot was handing him a reason that argued against its
    own trade."""
    rows = [mover("FALLER", -6.0, "IT")] + [mover(f"P{i}", 3.0, "IT")
                                            for i in range(4)]
    got = run(rows, mech=lambda s: reason("Strong Q1 AUM and PAT growth",
                                          direction="POSITIVE"))
    # The peers legitimately qualify -- up 3% against a sector dragged
    # to 1.2% by the faller. What must NOT appear is the short itself.
    assert "FALLER" not in [c["symbol"] for c in got["rows"]]


def test_a_bearish_reason_cannot_justify_a_buy():
    rows = [mover("RISER", 8.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                          for i in range(4)]
    got = run(rows, mech=lambda s: reason("Plant shutdown after fire",
                                          direction="NEGATIVE"))
    assert "RISER" not in [c["symbol"] for c in got["rows"]]


def test_a_matching_reason_is_kept():
    rows = [mover("RISER", 8.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                          for i in range(4)]
    got = run(rows, mech=lambda s: reason(direction="POSITIVE"))
    assert got["rows"][0]["symbol"] == "RISER"


def test_a_reason_with_no_direction_is_allowed_through():
    """Most stored mechanisms carry no explicit sign. Refusing them all
    would empty the list; the tape and the sector still have to agree."""
    rows = [mover("RISER", 8.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                          for i in range(4)]
    assert run(rows, mech=lambda s: reason(direction=None))["rows"]


# ---------------------------------------------------------------
# 4. A LOOKUP IS NOT A MECHANISM
# ---------------------------------------------------------------
def test_matched_on_is_refused():
    """core/news_impact.py writes "matched on: INDGN" when a story
    named a company and reasoned nothing. It ranked sixth."""
    rows = [mover("INDGN", 8.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                          for i in range(4)]
    assert run(rows, mech=lambda s: reason("matched on: INDGN"))["rows"] == []


def test_no_reason_at_all_is_refused():
    """     "without any thing stock doesn't move, that something is we
             need to find out" """
    rows = [mover("A", 9.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                      for i in range(4)]
    assert run(rows, mech=lambda s: None)["rows"] == []
    assert run(rows, mech=lambda s: reason(""))["rows"] == []


def test_a_one_word_reason_is_refused():
    rows = [mover("A", 9.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                      for i in range(4)]
    assert run(rows, mech=lambda s: reason("up"))["rows"] == []


# ---------------------------------------------------------------
# 5. THE GATES THAT REFUSE RATHER THAN SUBTRACT
# ---------------------------------------------------------------
def test_a_stock_with_no_measurement_is_never_a_candidate():
    """CORRECTED 4 August 2026. This was called "the YASHO gate" and
    justified by claiming the bot had never seen YASHO trade. That was
    a broken data source, not a fact: against NSE's bhavcopy YASHO does
    Rs 61 crore a day. The gate is a SIZE filter -- at Rs 1.2 lakh of
    buying power, a stock doing Rs 3 crore a day makes the operator the
    volume."""
    rows = [mover("YASHO", 12.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                           for i in range(4)]
    assert run(rows, adv=0.0)["rows"] == []


def test_a_genuinely_thin_stock_is_refused_even_on_a_perfect_setup():
    rows = [mover("THIN", 12.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                          for i in range(4)]
    assert run(rows, adv=2.0)["rows"] == []
    assert ranker.MIN_LIQUIDITY_CR >= 5


def test_a_blocked_symbol_is_refused():
    rows = [mover("BLOCKED", 9.0, "IT")] + [mover(f"P{i}", 1.0, "IT")
                                            for i in range(4)]
    assert run(rows, blocked=["BLOCKED"])["rows"] == []


def test_no_volume_behind_it_is_refused():
    """     "volumes supports the data" -- his rule, as arithmetic."""
    rows = [mover("QUIET", 9.0, "IT", volume=1000, ltp=10.0)] \
        + [mover(f"P{i}", 1.0, "IT") for i in range(4)]
    assert run(rows, adv=500.0)["rows"] == []


def test_volume_ratio_is_against_the_stocks_own_normal_day():
    got = volume_ratio({"volume": 2_000_000, "ltp": 500.0}, 50.0)
    assert got == 2.0                       # Rs 100 cr traded vs 50 normal
    assert volume_ratio({"volume": None, "ltp": 1}, 10) is None


# ---------------------------------------------------------------
# 6. IT DOES NOT CHURN
# ---------------------------------------------------------------
def test_a_marginally_better_challenger_does_not_trigger_a_swap():
    """Two candidates a rounding error apart would trade places on
    every clock tick, and the account pays brokerage to stand still."""
    assert should_swap({"score": 20.0}, {"score": 20.5}) is False
    assert should_swap({"score": 20.0}, {"score": 23.0}) is True


def test_an_empty_slot_is_always_filled():
    assert should_swap(None, {"score": 1.0}) is True
    assert should_swap({"score": 5.0}, None) is False


# ---------------------------------------------------------------
# 7. IT DECIDES NOTHING
# ---------------------------------------------------------------
def test_it_places_no_orders_and_sizes_nothing():
    """core/engine.py remains the only thing that trades."""
    src = open("core/ranker.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    for banned in ("place_order", "def size", "qty =", "self.dhan",
                   "execute", "def exit"):
        assert banned not in code, banned


def test_nothing_moving_is_an_answer():
    got = rank([])
    assert got["rows"] == [] and "nothing" in got["note"]


def test_it_never_raises_on_junk():
    junk = [{}, {"symbol": None}, {"symbol": "X", "change_pct": "n/a"},
            {"symbol": "Y", "change_pct": 5.0, "volume": None, "ltp": None}]
    assert rank(junk)["rows"] == []


# ---------------------------------------------------------------
# 8. A FINISHED MOVE IS NOT A TRADE
# ---------------------------------------------------------------
#     "some stocks will rally in opening 1/2 mins & sit in top gainers
#      no use of such movement in stock for trader"
#                                     -- operator, 4 August 2026
#
# RBA closed +18.2%, top of the gainers list all day, high made at
# 09:16. Five hours of nothing. Day-change ranking loves that stock.
def live(symbol, pct, recent, high=None, ltp=100.0, vwap=None, low=None):
    return {"symbol": symbol, "change_pct": pct, "sector": "CHEMICALS",
            "volume": 3_000_000, "ltp": ltp, "recent_pct": recent,
            "day_high": high, "day_low": low, "vwap": vwap}


def quiet(n=8):
    return [live(f"Q{i}", 0.3, 0.0) for i in range(n)]


def strong(s):
    return {"text": "Q1 results beat strongly", "weight": 0.8,
            "direction": "POSITIVE"}


def test_a_stock_far_off_its_high_is_fading():
    from core.ranker import liveness
    state, off = liveness(live("RBA", 18.2, 0.0, high=118.0, ltp=112.0))
    assert state == "fading"
    assert off > 5.0


def test_a_stock_at_its_high_and_still_moving_is_alive():
    from core.ranker import liveness
    state, _ = liveness(live("X", 12.0, 0.9, high=100.2, ltp=100.0, vwap=96.0))
    assert state == "alive"


def test_a_long_below_vwap_is_fading():
    """The average buyer today is under water. Not one to join."""
    from core.ranker import liveness
    state, _ = liveness(live("X", 9.0, 0.8, high=100.5, ltp=100.0, vwap=101.0))
    assert state == "fading"


def test_a_faller_is_measured_against_the_days_LOW():
    """Using the high for a short would call it fading the moment it
    bounced a rupee."""
    from core.ranker import liveness
    state, _ = liveness(live("S", -8.0, -0.9, high=112.0, low=99.8, ltp=100.0))
    assert state == "alive"


def test_no_high_and_no_recent_window_says_nothing():
    from core.ranker import liveness
    assert liveness({"symbol": "X", "change_pct": 5.0}) == (None, None)


def test_the_finished_move_cannot_lead_however_big_it_was():
    """THE ONE THAT MATTERS. A penalty alone could not do this -- an
    18-point day move outran an 8-point penalty, and raising the number
    until RBA lost would have been tuning to one example. Liveness
    sorts BEFORE score."""
    rows = [live("RBA", 18.2, 0.0, high=118.0, ltp=112.0),
            live("STYRENIX", 12.0, 0.9, high=100.2, ltp=100.0, vwap=96.0)]
    got = run(rows + quiet(), adv=10.0, mech=strong)
    named = [c["symbol"] for c in got["rows"]]
    assert named[0] == "STYRENIX"
    # RBA still SHOWN -- seeing a dying move labelled is how he learns
    # the shape. It is never handed to him as today's best idea.
    assert "RBA" in named
    assert got["rows"][named.index("RBA")]["state"] == "fading"


def test_an_unmeasured_stock_is_not_demoted():
    """Unasked is not failed -- the same rule the MTF gate follows."""
    rows = [live("KNOWN", 9.0, 0.9, high=100.1, ltp=100.0),
            {"symbol": "PLAIN", "change_pct": 12.0, "sector": "CHEMICALS",
             "volume": 3_000_000, "ltp": 100.0}]
    got = run(rows + quiet(), adv=10.0, mech=strong)
    assert got["rows"][0]["symbol"] == "PLAIN"
    assert got["rows"][0]["state"] is None


# ---------------------------------------------------------------
# 9. HE TRADES MTF. A CASH-ONLY NAME IS NOT A CANDIDATE.
# ---------------------------------------------------------------
#     "only trade in best set of stocks in MTF"
def test_a_stock_dhan_will_not_margin_is_refused():
    rows = [live("BASF", 9.0, 0.9, high=100.1, ltp=100.0),
            live("STYRENIX", 12.0, 0.9, high=100.2, ltp=100.0)]
    got = run(rows + quiet(), adv=10.0, mech=strong,
              mtf_of=lambda s, r: {"eligible": s != "BASF",
                                   "leverage": 4.0 if s != "BASF" else None})
    assert "BASF" not in [c["symbol"] for c in got["rows"]]


def test_the_leverage_reaches_the_row():
    rows = [live("STYRENIX", 12.0, 0.9, high=100.2, ltp=100.0)]
    got = run(rows + quiet(), adv=10.0, mech=strong,
              mtf_of=lambda s, r: {"eligible": True, "leverage": 4.0})
    assert got["rows"][0]["mtf_leverage"] == 4.0


def test_not_asking_about_mtf_refuses_nobody():
    """Paper mode, backtests and the preview pass no mtf_of. An unasked
    question must never read as a failed one -- that would empty the
    table everywhere the broker is absent."""
    rows = [live("STYRENIX", 12.0, 0.9, high=100.2, ltp=100.0)]
    got = run(rows + quiet(), adv=10.0, mech=strong)
    assert got["rows"]
    assert got["rows"][0]["mtf_eligible"] is None


# ---------------------------------------------------------------
# 10. DO NOT WAIT FOR THE CIRCUIT
# ---------------------------------------------------------------
#     "why bot or trader needs to wait till Circuit closing even after
#      knowing the results are excellent & volumes started buying stock
#      moving = bot / trader must buy these stocks right?"
#                                     -- operator, 4 August 2026
#
# He is right, and the reason was structural. dashboard/state.py fed
# the ranker the top 50 gainers and top 50 losers and nothing else. On
# a strong day the 50th gainer is already up 5-6%, so a stock that
# filed excellent results at 09:41 and is up 2.5% on rising volume sat
# around 180th -- invisible. It only became visible once it had run to
# its circuit, which is the one moment it cannot be bought.
def test_a_stock_at_its_circuit_is_flagged_not_offered():
    rows = [dict(live("MOREPEN", 20.0, 0.9, high=120.0, ltp=120.0),
                 headroom_up_pct=0.0)]
    got = run(rows + quiet(), adv=10.0, mech=strong)
    top = got["rows"][0]
    assert top["symbol"] == "MOREPEN"
    assert top["at_circuit"] is True
    assert top["headroom_pct"] == 0.0


def test_room_left_is_reported_so_he_can_see_there_is_a_trade():
    rows = [dict(live("BASF", 4.0, 0.8, high=104.1, ltp=104.0),
                 headroom_up_pct=15.9)]
    got = run(rows + quiet(), adv=10.0, mech=strong)
    top = got["rows"][0]
    assert top["at_circuit"] is False
    assert top["headroom_pct"] == 15.9


def test_a_short_reads_the_lower_band():
    rows = [dict(live("X", -8.0, -0.9, high=112.0, low=99.9, ltp=100.0),
                 headroom_up_pct=12.0, headroom_down_pct=0.2)]
    got = run(rows + quiet(), adv=10.0,
              mech=lambda s: {"text": "Plant shut after fire, output halted",
                              "weight": 0.8, "direction": "NEGATIVE"})
    top = [c for c in got["rows"] if c["symbol"] == "X"][0]
    assert top["action"] == "SELL"
    assert top["at_circuit"] is True


def test_no_band_means_no_claim_either_way():
    """The exchange publishes this live. When it has not reached us,
    silence -- never 'plenty of room'."""
    got = run([live("X", 4.0, 0.8, high=104.1, ltp=104.0)] + quiet(),
              adv=10.0, mech=strong)
    assert got["rows"][0]["at_circuit"] is None
    assert got["rows"][0]["headroom_pct"] is None


def test_an_early_mover_on_fresh_results_is_a_candidate():
    """The whole point. Up 2.5%, nowhere near the leaderboard, results
    just filed, volume building -- this must be rankable."""
    early = live("BASF", 2.5, 0.6, high=102.6, ltp=102.5)
    got = run([early] + quiet(), adv=10.0, mech=strong)
    assert got["rows"][0]["symbol"] == "BASF"
    assert got["rows"][0]["state"] == "alive"


def test_the_pool_is_widened_by_reason_not_by_rank():
    src = open("dashboard/state.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "self._widen_by_reason(movers)" in code
    assert "_symbols_with_news_today" in code
