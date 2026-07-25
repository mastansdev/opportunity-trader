"""
==========================================================
News Bot -- Pipeline Orchestrator
==========================================================

One full poll cycle, start to finish: ingest -> match ->
classify (budget-capped) -> tier -> record. This is the single
function main.py's news thread calls every
news_bot.config.POLL_INTERVAL_SECONDS.

Every stage keeps its own failure isolation (see each stage's
module docstring) -- one broken RSS source, one failed
classification call, never aborts the rest of the cycle.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import decision, diagnostic, warn
from news_bot import classification
from news_bot import keyword_classifier
from news_bot import priority as priority_stage
from news_bot.config import (
    NEWS_CLASSIFIER_MODE, NEWS_STORE_NEUTRAL, NEWS_AI_ONLY_COMPANY_TIER,
)
from news_bot.news_store import default_store
from news_bot.call_budget import CallBudget
from news_bot.ingestion import fetch_everything
from news_bot.matching import NewsMatcher
from news_bot.news_queue import record


def run_once(matcher=None, budget=None, master_loader=None, store=None):
    """
    Returns a summary dict the caller can log/inspect. `store` is
    injectable so tests use a temp DB; production uses the default.
    """
    matcher = matcher or NewsMatcher()
    budget = budget or CallBudget()
    loader = master_loader or matcher.loader
    store = store or default_store()

    summary = {
        "ingested": 0,
        "matched": 0,
        "dummy": 0,
        "already_seen": 0,       # skipped before classifying (never re-billed)
        "classified": 0,
        "ai_calls": 0,           # paid Haiku calls actually spent
        "keyword_calls": 0,       # free keyword classifications
        "skipped_budget": 0,
        "skipped_not_configured": 0,
        "dropped_neutral": 0,
        "high": 0,
        "mid": 0,
        "errors": 0,
    }

    # 2026-07-24 -- classifier selection (news_bot/config.py's
    # NEWS_CLASSIFIER_MODE). Resolved ONCE per cycle into one of three
    # explicit choices so the per-item loop below is unambiguous:
    #   "haiku"   -- paid path (budget + key checked per item)
    #   "keyword" -- FREE path (no key, no budget, no network)
    #   "skip"    -- classify nothing this cycle (haiku mode, no key)
    # Modes: "keyword" always free; "haiku" always paid, skips when
    # unconfigured (strict, as before); "auto" prefers Haiku and falls
    # back to the free keyword classifier when unconfigured.
    haiku_ok = classification.is_configured()
    if NEWS_CLASSIFIER_MODE == "keyword":
        choice = "keyword"
    elif NEWS_CLASSIFIER_MODE == "haiku":
        if haiku_ok:
            choice = "haiku"
        else:
            choice = "skip"
            warn(
                "NEWS_BOT: mode='haiku' but AI not configured -- every "
                "matched item this cycle will be skipped."
            )
    else:  # "auto"
        if haiku_ok:
            choice = "haiku"
        else:
            choice = "keyword"
            diagnostic(
                "NEWS_BOT: AI not configured -- using the FREE keyword "
                "classifier (display-only, does not block trades)."
            )

    items = fetch_everything()
    summary["ingested"] = len(items)

    for matched_news in matcher.match_all(items):
        if matched_news.is_dummy:
            summary["dummy"] += 1
            continue

        summary["matched"] += 1

        item = matched_news.item
        guid = item.guid or item.link

        for match_result in matched_news.matches:
            company = loader.get_by_symbol(match_result.symbol)
            if company is None:
                # Should not happen -- Stage 2 only ever produces
                # symbols it just resolved from this same loader --
                # but never trust a match blindly, verify again.
                continue

            # ---- BUDGET GUARD #1: never process the same (story, stock)
            # twice. If it's already in the store, we already classified
            # it once (and, if it went to AI, already paid for it). Skip
            # BEFORE spending anything. This is what stops a headline that
            # sits in the RSS feed for hours from being re-billed on every
            # 45s poll.
            if store.exists(guid, match_result.symbol):
                summary["already_seen"] += 1
                continue

            if choice == "skip":
                summary["skipped_not_configured"] += 1
                continue

            # ---- BUDGET GUARD #2: only COMPANY-tier news (a named stock /
            # direct exchange filing) is worth a paid AI call. Broad
            # SECTOR/THEME/COMMODITY fan-out (~93% of volume) uses the FREE
            # keyword classifier. config.NEWS_AI_ONLY_COMPANY_TIER.
            want_ai = (choice == "haiku")
            if want_ai and NEWS_AI_ONLY_COMPANY_TIER and match_result.tier != "COMPANY":
                want_ai = False

            if want_ai and not budget.can_spend(1):
                summary["skipped_budget"] += 1
                diagnostic(
                    f"NEWS_BOT: AI call budget exhausted "
                    f"({budget.count_today()}/{budget.limit} today) -- "
                    f"{match_result.symbol} falls back to free keyword."
                )
                want_ai = False

            used_ai = False
            if want_ai:
                # Counted the moment the call is attempted, not after
                # seeing whether it parsed cleanly -- the network
                # round-trip is what costs money either way.
                budget.record_call()
                summary["ai_calls"] += 1
                try:
                    result = classification.classify(item, company)
                    used_ai = True
                except classification.ClassificationError as exc:
                    # A failed paid call falls back to the free classifier
                    # rather than dropping the item -- we still want a
                    # verdict, just not a second (also-failing) paid try.
                    warn(f"NEWS_BOT: {exc} -- falling back to keyword.")
                    summary["errors"] += 1
                    result = keyword_classifier.classify(item, company)
                    summary["keyword_calls"] += 1
            else:
                # FREE path -- no key, no budget, no network.
                result = keyword_classifier.classify(item, company)
                summary["keyword_calls"] += 1

            summary["classified"] += 1

            tiered = priority_stage.tier_for(match_result, result)

            # ---- STORE decision. Keep the row if it carries a real
            # trade signal (bullish/bearish), OR if we PAID the AI for it
            # (classifier == "haiku") -- storing a paid neutral verdict is
            # how we REMEMBER we already spent on this story so guard #1
            # never lets us pay again. Free keyword NEUTRAL noise (general
            # filings, sector fan-out -- the 78.6% junk) is dropped and
            # never stored. Neutral rows, paid or not, are excluded from
            # every dashboard read (news_store.py), so the feed stays clean.
            keep = (tiered.direction != "neutral") or used_ai or NEWS_STORE_NEUTRAL
            if not keep:
                summary["dropped_neutral"] += 1
                continue

            record(tiered, item, store=store)

            if tiered.direction == "neutral":
                # Stored only as a paid-once memory marker; not a live
                # HIGH/MID signal, so it isn't counted as either.
                continue
            if tiered.priority == "HIGH":
                summary["high"] += 1
            else:
                summary["mid"] += 1

    decision(
        f"NEWS_BOT: cycle done -- {summary['ingested']} ingested, "
        f"{summary['dummy']} dummy, {summary['matched']} matched, "
        f"{summary['already_seen']} already-seen (skipped), "
        f"{summary['classified']} classified "
        f"[{summary['ai_calls']} paid AI, {summary['keyword_calls']} free] "
        f"({summary['high']} HIGH, {summary['mid']} MID), "
        f"{summary['dropped_neutral']} dropped (neutral/no-signal), "
        f"{summary['skipped_budget']} over-budget (fell back to free), "
        f"{summary['skipped_not_configured']} skipped (AI-only mode, no key), "
        f"{summary['errors']} classification errors."
    )

    return summary
