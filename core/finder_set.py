"""The finders themselves. One question each, answered well.

==========================================================
    "Opportunities from NEWS, RESULTS, EVENTS, structural moving
     stocks like all as a unique finders that report to trade brain
     engine"                      -- operator, 22 August 2026
==========================================================

Each of these wraps a store the bot ALREADY reads. Nothing here is a
new data source -- what is new is that a candidate now carries WHERE
it came from, so every source can be measured on what its own picks
did instead of being averaged into one anonymous score.

    NewsFinder        core/news_impact.py  -- the newswire
    EventFinder       core/stock_events.py -- the PRO Telegram channels
    FilingFinder      core/feed_store.py   -- NSE announcements
    ResultsFinder     the graded results cards. Dormant until the
                      October season; kept because it costs nothing
                      and the operator asked for it by name.
    StructuralFinder  price leaving its opening range, no reason
                      required. Off by default -- his standing rule is
                      "an event or real opportunity, NEVER random
                      stocks", and this is the lane that argues with it.

WHAT A FINDER MUST NOT DO

Place an order. Read another finder. Decide its own seat count. Score
itself. All four are the brain's business, and keeping them out of
here is what makes a finder's record its own.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

from core.finders import Finder, candidate
from core.logger import diagnostic


def _volume_x(row):
    """The stock's turnover against its own normal, or None.

    None means UNMEASURED, and the brain sorts those last. It never
    means 'quiet' -- reading it that way is how a stock nobody could
    measure ends up at the top of the list.
    """
    for key in ("volume_x", "volume_ratio", "vol_x"):
        got = (row or {}).get(key)
        if got is not None:
            try:
                return float(got)
            except (TypeError, ValueError):
                continue
    return None


class MoversFinder(Finder):
    """Everything the ranker is already naming, stamped with a source.

    The bridge from the existing path. The ranker's rows already carry
    a reason and a volume reading; this gives them provenance so the
    brain can compare them against the newer finders on equal terms.
    """

    name = "movers"

    def __init__(self, ranked_rows=None):
        self.ranked_rows = ranked_rows

    def find(self, now=None):
        rows = self.ranked_rows() if callable(self.ranked_rows) \
            else (self.ranked_rows or [])
        out = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("symbol"):
                continue
            out.append(candidate(
                row.get("symbol"), self.name,
                reason=row.get("why") or row.get("reason"),
                at=now, volume_x=_volume_x(row),
                price=row.get("ltp") or row.get("price"),
                change_pct=row.get("change_pct"),
                sector=row.get("sector"),
                score=row.get("score")))
        return out


class EventFinder(Finder):
    """A PRO channel said something about this company today.

    core/stock_events.py holds what the paid channels publish --
    OrderBook Pulse, Business Pulse, RedboxGlobal, Day Trader Telugu.
    MACRO is excluded: "RBI holds rates" explains why everything moved
    and identifies nothing.
    """

    name = "events"
    SKIP = {"MACRO", "MARKET_ANSWER", "AI_VERDICT"}

    def __init__(self, events_for=None, volume_of=None, kinds=None):
        self.events_for = events_for
        self.volume_of = volume_of
        self.kinds = set(kinds) if kinds else None

    def find(self, now=None):
        if not callable(self.events_for):
            return []
        today = (now or datetime.now()).strftime("%Y-%m-%d")
        out = []
        for row in self.events_for(today) or []:
            kind = str((row or {}).get("kind") or "").upper()
            symbol = (row or {}).get("symbol")
            if not symbol or kind in self.SKIP:
                continue
            if self.kinds and kind not in self.kinds:
                continue
            vol = None
            if callable(self.volume_of):
                try:
                    vol = self.volume_of(symbol)
                except Exception:                           # noqa: BLE001
                    vol = None
            out.append(candidate(
                symbol, self.name,
                reason=row.get("headline"), at=row.get("at"),
                volume_x=vol, kind=kind, grade=row.get("grade"),
                value_cr=row.get("value_cr"),
                source=row.get("source")))
        return out


class OrderFinder(EventFinder):
    """Order wins only -- the operator's focus once results season ends.

        "after the results season bot focus must shift to order
         books/news/events of companies"    -- 22 August 2026

    Separated from EventFinder so its record can be read on its own.
    That is the entire point of the split: on 22 August ORDER events
    measured -Rs 292 same-window against NEWS at +Rs 14, and averaged
    together they said nothing.
    """

    name = "orders"

    def __init__(self, events_for=None, volume_of=None):
        super().__init__(events_for=events_for, volume_of=volume_of,
                         kinds={"ORDER", "ORDER_WIN"})


class FilingFinder(Finder):
    """An NSE filing the exchange published today.

    core/feed_store.py. Until 21 August the trading path had never
    opened this store, and 468 of 602 daily filings were being
    discarded by the classifier before that was fixed.
    """

    name = "filings"

    def __init__(self, filing_for=None, symbols_today=None, volume_of=None):
        self.filing_for = filing_for
        self.symbols_today = symbols_today
        self.volume_of = volume_of

    def find(self, now=None):
        if not callable(self.symbols_today) or not callable(self.filing_for):
            return []
        out = []
        for symbol in self.symbols_today() or []:
            row = self.filing_for(symbol)
            if not row:
                continue
            from core.why_moving import from_filing
            said = from_filing(row, now=now)
            if not said:
                continue                    # filed, but not a reason to buy
            vol = None
            if callable(self.volume_of):
                try:
                    vol = self.volume_of(symbol)
                except Exception:                           # noqa: BLE001
                    vol = None
            out.append(candidate(
                symbol, self.name, reason=said.get("text"),
                at=row.get("_filed_dt") or row.get("filed_at"),
                volume_x=vol, kind=row.get("kind"),
                weight=said.get("weight")))
        return out


class ResultsFinder(EventFinder):
    """Graded results cards. Dormant outside the season.

        "results season completed & will re occur on oct 2nd week"
                                        -- operator, 22 August 2026

    Kept wired because it costs nothing while the flow is empty, and
    because a finder that appears the week results resume is a finder
    nobody remembered to switch on.
    """

    name = "results"

    def __init__(self, events_for=None, volume_of=None):
        super().__init__(events_for=events_for, volume_of=volume_of,
                         kinds={"RESULT", "RESULTS", "REPORTED"})


class StructuralFinder(Finder):
    """Price leaving its opening range. NO reason required.

    OFF unless explicitly enabled. His standing instruction is "an
    event or real opportunity ... NEVER in to random stocks", and this
    is the lane that argues with it -- on 20 August it produced 24 of
    34 alerts and none of them carried a published reason.

    It exists as a finder so that claim can finally be MEASURED
    against the others rather than argued about.
    """

    name = "structural"

    def __init__(self, breakouts=None, volume_of=None, enabled=False):
        self.breakouts = breakouts
        self.volume_of = volume_of
        self.enabled = bool(enabled)

    def find(self, now=None):
        if not self.enabled:
            return []
        rows = self.breakouts() if callable(self.breakouts) \
            else (self.breakouts or [])
        out = []
        for row in rows or []:
            symbol = (row or {}).get("symbol")
            if not symbol:
                continue
            out.append(candidate(
                symbol, self.name,
                reason=row.get("why") or "opening range break, no reason",
                at=now, volume_x=_volume_x(row),
                price=row.get("ltp") or row.get("price")))
        return out


def build(ranked_rows=None, events_for=None, filing_for=None,
          symbols_today=None, volume_of=None, breakouts=None,
          structural=False):
    """The standard set, in the order he named them.

    Every argument is optional. A finder with nothing wired returns []
    and the rest carry on -- which is what lets this go live before
    every source is connected.
    """
    made = [
        MoversFinder(ranked_rows=ranked_rows),
        EventFinder(events_for=events_for, volume_of=volume_of),
        OrderFinder(events_for=events_for, volume_of=volume_of),
        FilingFinder(filing_for=filing_for, symbols_today=symbols_today,
                     volume_of=volume_of),
        ResultsFinder(events_for=events_for, volume_of=volume_of),
        StructuralFinder(breakouts=breakouts, volume_of=volume_of,
                         enabled=structural),
    ]
    diagnostic(f"[FINDERS] {len(made)} wired: "
               f"{', '.join(f.name for f in made)}"
               f"{'' if structural else ' (structural OFF)'}")
    return made
