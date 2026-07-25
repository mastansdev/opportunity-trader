"""
==========================================================
News Gate
==========================================================

The ONLY point of contact between the trading engine
(core/engine.py) and News Bot. This module itself stays a thin,
honest READER -- it never decides anything, just answers "what
does News Bot know about this symbol today". The actual
contradiction-blocking decision (operator-approved: same-day,
HIGH-confidence news pointing the OPPOSITE way from a structural
breakout blocks only that one direction, for that one symbol,
for the rest of the day -- never a blanket "no news = no trade")
lives entirely in core/engine.py's _try_structural_entry(), which
is the only caller of latest_high_priority(). Keeping the
decision out of this file means NewsGate can always be read,
tested, and reasoned about as "just a lookup", nothing more.

Author : H&M Opportunity Trader
==========================================================
"""

from news_bot.news_queue import NewsQueueReader


class NewsGate:

    def __init__(self, reader=None):
        self.reader = reader or NewsQueueReader()

    def refresh(self):
        self.reader.refresh()

    def describe(self, symbol):
        """
        Returns a short human-readable string describing the
        latest HIGH-priority news for `symbol` today, or None
        if there is none. Advisory only -- callers must never
        use this return value to change a trade decision (see
        module docstring).
        """
        items = self.reader.high_priority_for(symbol)
        if not items:
            return None

        latest = items[-1]
        return (
            f"{latest['direction']} ({latest['confidence']}%) -- "
            f"{latest['reason']}"
        )

    def all_news_stocks(self):
        """
        symbol -> latest HIGH item today, for the dashboard's
        News watchlist. Read-only, same advisory-only reasoning
        as describe() -- this is a display list, it doesn't feed
        back into any trade decision.
        """
        return self.reader.all_symbols_today()

    def recent_feed(self, limit=None):
        """
        Today's MID+HIGH news items, newest first, for the
        dashboard's news-impact panel. Includes MID (which the
        blocking gate never sees) so the operator can watch the
        FREE keyword classifier working even on a day with no HIGH
        items. Read-only, display-only -- like all_news_stocks(),
        it never feeds back into a trade decision.
        """
        items = self.reader.recent()
        return items[:limit] if limit is not None else items

    def latest_high_priority(self, symbol):
        """
        Returns the raw latest HIGH-priority item dict for
        `symbol` today (direction/confidence/reason/...), or None.
        Structured access for callers that need to reason about
        direction programmatically -- unlike describe(), which
        only ever returns a formatted display string. This is
        what core/engine.py's news-contradiction check reads;
        NOT a new veto living in this module -- NewsGate stays a
        thin, honest reader either way (see module docstring).
        """
        items = self.reader.high_priority_for(symbol)
        return items[-1] if items else None
