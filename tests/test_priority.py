"""
Decision-correctness tests for News Bot Stage 4 (priority
tiering). Each test asserts the SPECIFIC tier for a known
input combination, per the exact rule in priority.py's
docstring: HIGH requires confidence >= threshold AND
materiality == material AND direction != neutral, all three.
"""

from news_bot.models import MatchResult
from news_bot.priority import HIGH_CONFIDENCE_THRESHOLD, tier_for


def _match(symbol="TCS", field="COMPANY_NAME", tier="COMPANY"):
    return MatchResult(symbol=symbol, field=field, matched_term="TCS", tier=tier)


def _classification(direction="bullish", confidence=85, materiality="material",
                     reason="Large new export order."):
    return {
        "direction": direction,
        "confidence": confidence,
        "materiality": materiality,
        "reason": reason,
    }


def test_high_confidence_material_directional_is_high():
    result = tier_for(_match(), _classification())
    assert result.priority == "HIGH"
    assert result.symbol == "TCS"
    assert result.direction == "bullish"


def test_low_confidence_is_mid_even_if_material_and_directional():
    result = tier_for(
        _match(), _classification(confidence=HIGH_CONFIDENCE_THRESHOLD - 1)
    )
    assert result.priority == "MID"


def test_routine_materiality_is_mid_even_at_high_confidence():
    result = tier_for(_match(), _classification(materiality="routine"))
    assert result.priority == "MID"


def test_neutral_direction_is_mid_even_at_high_confidence_material():
    result = tier_for(_match(), _classification(direction="neutral"))
    assert result.priority == "MID"


def test_mid_items_still_carry_direction_and_reason_not_discarded():
    result = tier_for(
        _match(), _classification(direction="bearish", confidence=40)
    )
    assert result.priority == "MID"
    assert result.direction == "bearish"
    assert result.reason == "Large new export order."


def test_result_carries_stage2_provenance():
    result = tier_for(_match(field="SECTOR", tier="BROAD"), _classification())
    assert result.matched_field == "SECTOR"
    assert result.tier == "BROAD"


def test_exact_threshold_confidence_qualifies_as_high():
    result = tier_for(
        _match(), _classification(confidence=HIGH_CONFIDENCE_THRESHOLD)
    )
    assert result.priority == "HIGH"
