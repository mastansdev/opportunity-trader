"""
==========================================================
News Bot -- Stage 3: AI Classification (paid, Claude Haiku)
==========================================================

For every Stage 2 survivor (a NewsItem that matched at least
one stock), asks Claude Haiku for: direction, confidence,
materiality, and the specific company fact that justified the
call -- so every classification is explainable, not a black
box (see PHASE3_NEWS_DESIGN.md, section 3.2, Stage 3).

Never called for DUMMY items -- that filtering happens
upstream, in news_bot/matching.py + pipeline.py, not here.
The daily call cap (news_bot/call_budget.py) is also enforced
by the CALLER (pipeline.py), before this module is invoked --
this module has no opinion about budget, only about one call,
so it stays trivially testable in isolation.

A bad or unparseable response is a failure (ClassificationError),
never a guessed default -- a made-up "neutral" would be worse
than no classification at all.

Author : H&M Opportunity Trader
==========================================================
"""

import json

MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 300

_VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}
_VALID_MATERIALITY = {"material", "routine"}


class ClassificationError(Exception):
    """Raised when Claude cannot be reached, or returns something
    unusable. Caught per-item by the caller (pipeline.py) -- one
    bad classification must never abort the whole poll cycle."""


def is_configured():
    """
    Cheap, no-network check: could classify() even attempt a real
    call right now? False means every classify() call this session
    would fail before touching the network at all (missing package
    or missing key). The caller (pipeline.py) uses this to warn
    ONCE per cycle instead of once per matched item -- without it,
    a missing key on a heavy news day would print the same warning
    hundreds of times, exactly the kind of flood this project
    deliberately avoids everywhere else.
    """
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False

    from config import ANTHROPIC_API_KEY

    return bool(ANTHROPIC_API_KEY)


def classify(item, company, client=None):
    """
    item    : a news_bot.models.NewsItem
    company : dict -- one row from MasterLoader (e.g.
              loader.get_by_symbol(symbol)), giving Claude the
              verified company facts to reason from instead of
              guessing.
    client  : injected Anthropic client (must expose
              .messages.create(...) matching the real SDK) --
              tests always inject a fake. None builds a real
              one from ANTHROPIC_API_KEY.

    Returns {"direction":, "confidence":, "materiality":, "reason":}.
    Raises ClassificationError on any failure.
    """
    if client is None:
        client = _build_client()

    prompt = _build_prompt(item, company)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise ClassificationError(
            f"Claude API call failed for {item.dedupe_key()}: {exc}"
        ) from exc

    raw_text = _extract_text(response, item)
    parsed = _parse_json(raw_text, item)
    return _validate(parsed, item)


def _build_prompt(item, company):
    return (
        f"Headline: {item.title}\n"
        f"Summary: {item.summary}\n\n"
        f"Company: {company.get('COMPANY NAME')} ({company.get('SYMBOL')})\n"
        f"Sector: {company.get('SECTOR')}\n"
        f"Industry: {company.get('INDUSTRY')}\n"
        f"Ownership: {company.get('OWNERSHIP')}\n"
        f"Commodity exposure: {company.get('COMMODITY_EXPOSURE')}\n"
        f"Economic sensitivity: {company.get('ECONOMIC_SENSITIVITY')}\n\n"
        "Classify this headline's likely price impact on THIS "
        "specific company (not the market in general). Respond "
        "with ONLY a JSON object, no other text, no markdown "
        "fences:\n"
        '{"direction": "bullish|bearish|neutral", '
        '"confidence": <integer 0-100>, '
        '"materiality": "material|routine", '
        '"reason": "<one sentence citing the specific company '
        'fact above that justifies this call>"}'
    )


def _extract_text(response, item):
    try:
        return response.content[0].text.strip()
    except (AttributeError, IndexError, TypeError) as exc:
        raise ClassificationError(
            f"Unexpected response shape from Claude for "
            f"{item.dedupe_key()}: {response!r} ({exc})"
        ) from exc


def _parse_json(raw_text, item):
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ClassificationError(
            f"Claude returned unparseable JSON for {item.dedupe_key()}: "
            f"{raw_text!r} ({exc})"
        ) from exc


def _validate(parsed, item):
    direction = parsed.get("direction")
    materiality = parsed.get("materiality")
    confidence = parsed.get("confidence")
    reason = parsed.get("reason")

    if direction not in _VALID_DIRECTIONS:
        raise ClassificationError(
            f"Invalid direction {direction!r} for {item.dedupe_key()}"
        )
    if materiality not in _VALID_MATERIALITY:
        raise ClassificationError(
            f"Invalid materiality {materiality!r} for {item.dedupe_key()}"
        )
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ClassificationError(
            f"Invalid confidence {confidence!r} for {item.dedupe_key()}"
        )
    if not (0 <= confidence <= 100):
        raise ClassificationError(
            f"Confidence {confidence!r} out of range for {item.dedupe_key()}"
        )
    if not reason or not isinstance(reason, str):
        raise ClassificationError(
            f"Missing/invalid reason for {item.dedupe_key()}"
        )

    return {
        "direction": direction,
        "confidence": int(confidence),
        "materiality": materiality,
        "reason": reason,
    }


def _build_client():
    try:
        import anthropic
    except ImportError as exc:
        raise ClassificationError(
            "'anthropic' package not installed (pip install anthropic)"
        ) from exc

    from config import ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY:
        raise ClassificationError(
            "ANTHROPIC_API_KEY missing -- copy .env.example to .env "
            "and fill it in."
        )

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
