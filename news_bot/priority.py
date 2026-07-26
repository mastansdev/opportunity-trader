"""
==========================================================
News Bot -- Stage 4: Priority Tiering
==========================================================

Two independent axes (see PHASE3_NEWS_DESIGN.md, section 3.2,
Stage 4):

  priority  : MID (matched but not high-conviction) / HIGH
              (matched + high confidence + material + not
              neutral). DUMMY is decided entirely in Stage 2
              (news_bot/matching.py) -- this module is never
              even called for a dummy match, so it has no
              DUMMY case of its own.
  direction : bullish / bearish / neutral -- recorded on MID
              items too. The design doc is explicit: do not
              throw away MID items, they matter for later
              backtesting of "silent movers."

Pure logic, no I/O, no network -- everything it needs is
passed in. Only HIGH results get pushed to Brain Bot
(news_bot/news_queue.py decides that, not here).

Author : H&M Opportunity Trader
==========================================================
"""

from dataclasses import dataclass

# A HIGH classification requires ALL three: confidence at or
# above this bar, a "material" event (not a routine filing),
# and a real (non-neutral) direction. Any one of those failing
# means MID, never silently dropped.
HIGH_CONFIDENCE_THRESHOLD = 70


@dataclass
class PriorityResult:
    symbol: str
    priority: str        # "MID" or "HIGH"
    direction: str        # "bullish" / "bearish" / "neutral"
    confidence: int
    materiality: str      # "material" / "routine"
    reason: str
    matched_field: str    # from the MatchResult that produced this symbol
    tier: str              # "COMPANY" or "BROAD", from Stage 2
    classifier: str = "haiku"  # "haiku" (paid) or "keyword" (free) --
                                # so the gate can choose to trust only
                                # Haiku for real-money blocking


def tier_for(match_result, classification_result):
    """
    match_result        : a news_bot.models.MatchResult
    classification_result : the dict returned by
                             news_bot.classification.classify()

    Returns a PriorityResult -- never None, never a silent
    default. HIGH requires confidence >= HIGH_CONFIDENCE_THRESHOLD
    AND materiality == "material" AND direction != "neutral".
    """
    direction = classification_result["direction"]
    confidence = classification_result["confidence"]
    materiality = classification_result["materiality"]

    # A BROAD match is a SECTOR story, not a fact about this stock.
    # 2026-07-26: "V-Mart Retail Q1 Results: Profit surges 40%" was
    # stored as bullish/HIGH against RELIANCE, DMART and ABFRL, and a
    # single steel filing reached 131 symbols at HIGH. Through the news
    # gate that blocks entries in every one of them at once, on the
    # strength of a story about a different company.
    #
    # Sector news is still recorded and still shown -- it is context,
    # and context should never veto an individual trade. Only a headline
    # that NAMES the stock (COMPANY tier) can reach HIGH.
    classifier = classification_result.get("classifier", "haiku")

    # THE KEYWORD CLASSIFIER CAN NEVER REACH HIGH -- 2026-07-26.
    #
    # Operator, unambiguously: "i do not want a hardcoded keyword /
    # matchmaker decides & tell the brain bot to buy/sell or any
    # decisions".
    #
    # He is right, and the examples were not edge cases:
    #
    #   "Ujjivan Small Finance BANK ... financial results"
    #        -> 'ban' matched inside 'Bank'  -> bearish 80% HIGH
    #   "Intimation of Tax Deduction on Dividend"
    #        -> 'dividend' matched            -> bullish 80% HIGH
    #
    # The first is fixed (word boundaries). The second is not fixable by
    # any word list, because the WORD is genuinely there and the meaning
    # is the opposite of what a lexicon can see. A bag of words cannot
    # read "tax deduction ON dividend" as routine admin.
    #
    # HIGH is the level that blocks a trade. So HIGH now requires a
    # classifier that actually reads the sentence. The keyword lexicon
    # still runs, still labels, still shows on the dashboard -- it just
    # cannot veto anything. When the paid classifier is bought, its
    # output reaches HIGH with no further change.
    is_high = (
        confidence >= HIGH_CONFIDENCE_THRESHOLD
        and materiality == "material"
        and direction != "neutral"
        and match_result.tier == "COMPANY"
        and classifier != "keyword"
    )

    return PriorityResult(
        symbol=match_result.symbol,
        priority="HIGH" if is_high else "MID",
        direction=direction,
        confidence=confidence,
        materiality=materiality,
        reason=classification_result["reason"],
        matched_field=match_result.field,
        tier=match_result.tier,
        classifier=classification_result.get("classifier", "haiku"),
    )
