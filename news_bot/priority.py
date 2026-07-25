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

    is_high = (
        confidence >= HIGH_CONFIDENCE_THRESHOLD
        and materiality == "material"
        and direction != "neutral"
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
