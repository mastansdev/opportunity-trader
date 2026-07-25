"""
==========================================================
News Bot -> Brain Bot Interface (store-backed)
==========================================================

Still decoupled -- News Bot never imports the trading engine.
As of 2026-07-24 the shared medium is a DATABASE (news_bot/
news_store.py), not two flat .jsonl files, so the engine can run
24/7 as its own process (locally, or on Railway) while the brain
bot reads the same store. See news_store.py's docstring for WHY
(dedup across poll cycles, per-stock history, cross-process).

This module keeps the SAME public surface the rest of the bot
already depends on, so nothing downstream changed:

  record(priority_result, item)  -- write one (item, stock) row,
      deduped. DUMMY items never reach here (pipeline filters them).

  NewsQueueReader                 -- brain-bot-side reader. refresh()
      pulls from the store into an in-memory index once per poll
      cycle, so the hot tick path (engine's news-contradiction
      check) only ever touches memory, never the database.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import diagnostic
from news_bot.news_store import default_store


def record(priority_result, item, store=None):
    """
    Writes every MID/HIGH item to the store, deduped on
    (guid, symbol) -- the same story for the same stock is stored
    once, ever, no matter how many poll cycles re-see it. DUMMY
    items never reach this function (pipeline.py filters them before
    priority.tier_for() is called). Logs HIGH items, exactly as the
    old file-based version did, so the console signal is unchanged.
    """
    store = store or default_store()
    is_new = store.record(priority_result, item)

    if is_new and priority_result.priority == "HIGH":
        diagnostic(
            f"NEWS_BOT: HIGH priority stored for Brain Bot: "
            f"{priority_result.symbol} {priority_result.direction} "
            f"({priority_result.confidence}%) -- {priority_result.reason}"
        )
    return is_new


class NewsQueueReader:
    """
    Brain-Bot-side reader. Loads actionable HIGH items (and a recent
    MID+HIGH display feed) from the store on demand -- call refresh()
    periodically (once per poll cycle, NOT per tick) and answer
    per-symbol lookups from memory, so the hot path never touches the
    database.
    """

    def __init__(self, store=None):
        self.store = store or default_store()
        self._by_symbol = {}     # symbol -> [actionable HIGH items]
        self._recent = []         # recent MID+HIGH items, newest first

    def refresh(self):
        """
        Rebuild the in-memory indices from the store, then swap them
        in atomically (build locals first, assign at the end) -- a
        concurrent read from the tick thread never sees a
        half-populated index. Both the HIGH-per-symbol lookup and the
        recent display feed come straight from the store's own
        freshness-windowed queries.
        """
        latest_high = self.store.all_high_symbols()
        new_index = {}
        for symbol in latest_high:
            new_index[symbol] = self.store.high_priority_for(symbol)
        self._by_symbol = new_index
        self._recent = self.store.recent()

    def high_priority_for(self, symbol):
        """Actionable HIGH items for symbol, oldest first, or an empty
        list if there are none."""
        return list(self._by_symbol.get(symbol, []))

    def recent(self):
        """Recent MID+HIGH items, newest first -- the dashboard's
        display feed. Copy so a caller can't mutate the cache."""
        return list(self._recent)

    def all_symbols_today(self):
        """
        symbol -> latest actionable HIGH item, for every symbol with
        at least one. Used by the dashboard's News watchlist.
        """
        return {
            symbol: items[-1]
            for symbol, items in self._by_symbol.items()
            if items
        }
