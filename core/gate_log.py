"""
==========================================================
Gate Log -- why the bot did NOT take a trade
==========================================================

Operator, 2026-07-26: "#1 too we can judge our bot trading descison on
this i guess and improve the gates which are used by bot".

Exactly right, and it is the biggest blind spot in the system. The
dashboard shows what the bot DID. It has never shown what the bot
ALMOST did. Every session, hundreds of breakouts are declined by
seventeen consecutive gates in core/engine.py's entry path, and until
now not one of those declines was recorded anywhere -- I grepped: there
was no skip, reject or gate logging in that file at all.

That matters more here than in most systems, because eight of those
gates are admitted guesses (POST_MONDAY_TODO H3: RS band 0.4-5%, sector
top-8, staged 3/6/10, no-progress 30min/0.5R, early-momentum RS>=1.0%,
blow-off 12%, rotation edge 0.4%, still-trending 0.65). If the RS band
is set too tight, the ONLY symptom is trades that never happened -- and
you cannot see those.

THE ONE DESIGN DECISION THAT MATTERS
------------------------------------
These gates fire on EVERY candle close for as long as their condition
holds. A symbol failing the RS band from 09:31 to 15:15 would log ~350
rejections. Counting events would produce a "funnel" dominated entirely
by how long each condition happened to last, which is noise.

So this counts CANDIDATES, not events, and each candidate is counted at
the DEEPEST gate it ever reached:

    PARAS/LONG rejected at RS_BAND on the 09:31 candle,
    then at SECTOR on the 10:15 candle
    -> counted once, at SECTOR

That makes the funnel a real funnel -- every candidate appears exactly
once, the numbers sum to the total, and "reached the sector gate and
died there" is genuine information about which gate is binding.

WHERE THE FUNNEL STARTS -- READ THIS BEFORE INTERPRETING A NUMBER
-----------------------------------------------------------------
A "candidate" is a symbol+direction for which core/strategy.py detected
a FRESH cross of the ORB boundary. It is NOT every stock in the
universe. A stock that simply never broke out today is not a declined
candidate; it was never a candidate.

That matters when reading the top of the funnel. If a session shows 40
candidates out of 545 subscribed names, the other 505 did not fail a
gate -- they never made a breakout to judge. The funnel measures which
GATE is binding, not how selective the strategy is overall.

WHAT THIS IS NOT
----------------
It has no vote. Nothing reads it to make a decision, nothing in
core/engine.py branches on it, and every call is wrapped so that a
failure in here can never affect a trade. Same discipline as
core/trend_structure.py and core/trade_memory.py: describe first,
measure, change the rule only on evidence.

Memory is bounded by construction: at most one record per
(symbol, direction), so 750 symbols x 2 = 1,500 rows, plus a capped
deque of recent near-misses for the detail view.

Author : H&M Opportunity Trader
==========================================================
"""

from collections import deque

# The entry path in core/engine.py, in the order the gates actually
# run. The ORDER IS THE POINT -- position in this list is what makes a
# funnel possible, so a new gate must be inserted where it really sits,
# not appended.
GATES = (
    ("SQUARE_OFF", "past square-off time"),
    ("FROZEN", "price frozen -- feed repeating the same tick"),
    ("ORB_UNRELIABLE", "feed was stale during the 09:15-09:30 range"),
    ("CIRCUIT", "approaching a circuit limit"),
    ("BLOCKED", "symbol/direction blocked for a stated reason"),
    ("REGIME", "market regime forbids this direction"),
    ("TREND_RANK", "not in the top-N gainers (long) / losers (short)"),
    ("ALREADY_TRIED", "already attempted this symbol+direction today"),
    ("RS_BAND", "relative strength outside the 0.4%-5.0% band"),
    ("STILL_TRENDING", "rolled over -- not holding near the day's extreme"),
    ("SECTOR", "sector not in the day's leading group"),
    ("NO_ENTRY_WINDOW", "past the staged no-entry cutoff"),
    ("BOOK_FULL", "all staged seats taken, rotation could not free one"),
    ("DAILY_HALT", "daily loss halt or profit goal reached"),
    ("BREAKOUT_MARGIN", "cleared the range by less than the required margin"),
    ("VOLUME", "breakout candle lacked a volume surge"),
    ("PANIC_SECTOR", "sector is panic-flagged today"),
    ("SIZING", "no ATR / computed quantity below 1 share"),
)

GATE_INDEX = {code: i for i, (code, _) in enumerate(GATES)}
GATE_HELP = dict(GATES)

ENTERED = "ENTERED"

# How many near-misses to keep for the detail view. Enough to scroll
# through a session, small enough to never matter.
RECENT_LIMIT = 120

# Gates at or past this index mean the candidate passed every
# selection rule and died on execution mechanics instead. Those are
# the interesting ones -- a trade the strategy WANTED and did not get.
NEAR_MISS_FROM = GATE_INDEX["BREAKOUT_MARGIN"]


class GateLog:
    """
    Not thread-safe by design decision, not by oversight: every writer
    is core/engine.py's single tick-worker thread, and the dashboard
    only ever reads via snapshot(), which copies. Adding a lock would
    put one on the hot tick path for a diagnostic.
    """

    def __init__(self, recent_limit=RECENT_LIMIT):
        self._deepest = {}          # (symbol, direction) -> gate code
        self._events = {}           # gate code -> raw firing count
        self._recent = deque(maxlen=recent_limit)
        self._entries = 0
        self.day = None

    # ----------------------------------------------------------

    def start_day(self, day):
        """Clear at the start of a session. Called with the trading
        date so a restart mid-session does NOT wipe the record."""
        if self.day == day:
            return
        self.day = day
        self._deepest.clear()
        self._events.clear()
        self._recent.clear()
        self._entries = 0

    def reject(self, symbol, direction, gate, detail=None, at=None):
        """
        Record that `symbol`/`direction` was declined at `gate`.

        Keeps the DEEPEST gate this candidate ever reached, so a name
        that fails RS at 09:31 and sector at 10:15 is counted once, at
        sector. Unknown gate codes are ignored rather than trusted --
        a typo must not silently create a phantom bucket.
        """
        if gate not in GATE_INDEX:
            return
        self._events[gate] = self._events.get(gate, 0) + 1

        key = (symbol, direction)
        current = self._deepest.get(key)
        if current == ENTERED:
            return                  # it traded; nothing later demotes that
        if current is None or GATE_INDEX[gate] > GATE_INDEX[current]:
            self._deepest[key] = gate
            if GATE_INDEX[gate] >= NEAR_MISS_FROM:
                self._recent.appendleft({
                    "symbol": symbol, "direction": direction,
                    "gate": gate, "detail": detail, "at": at,
                })

    def accept(self, symbol, direction):
        """Record that this candidate actually became a trade."""
        key = (symbol, direction)
        if self._deepest.get(key) != ENTERED:
            self._entries += 1
        self._deepest[key] = ENTERED

    # ----------------------------------------------------------

    def funnel(self):
        """
        [{gate, help, died, survived, events}] in gate order.

        `died`     candidates whose deepest gate was this one
        `survived` candidates that got PAST this gate
        `events`   raw firings, for context only -- a huge events count
                   against a small died count just means the condition
                   lasted a long time

        The survived column is the funnel: it starts at the number of
        candidates that reached the entry path at all and steps down.
        """
        died_by_gate = {}
        for value in self._deepest.values():
            if value == ENTERED:
                continue
            died_by_gate[value] = died_by_gate.get(value, 0) + 1

        total = len(self._deepest)
        remaining = total
        rows = []
        for code, help_text in GATES:
            died = died_by_gate.get(code, 0)
            remaining -= died
            rows.append({
                "gate": code,
                "help": help_text,
                "died": died,
                "survived": remaining,
                "events": self._events.get(code, 0),
            })
        return rows

    def summary(self):
        rows = self.funnel()
        total = len(self._deepest)
        blocking = max(rows, key=lambda r: r["died"]) if rows else None
        return {
            "candidates": total,
            "entries": self._entries,
            "rejected": total - self._entries,
            # The gate that killed the most distinct candidates today.
            # It is the first place to look, NOT automatically the one
            # to loosen -- the top gate is usually doing its job.
            "biggest_filter": blocking["gate"] if blocking and
            blocking["died"] else None,
            "biggest_filter_died": blocking["died"] if blocking else 0,
        }

    def recent_near_misses(self, limit=25):
        """Candidates that passed every SELECTION rule and then died on
        execution mechanics -- breakout margin, volume, sizing. The
        trades the strategy wanted and did not get."""
        return list(self._recent)[:limit]

    def snapshot(self):
        return {
            "day": self.day,
            "summary": self.summary(),
            "funnel": self.funnel(),
            "near_misses": self.recent_near_misses(),
        }


class NullGateLog:
    """
    Drop-in no-op. core/engine.py holds one of these when logging is
    switched off, so the entry path has no `if self.gate_log:` branches
    -- the calls are simply free.
    """

    day = None

    def start_day(self, day):
        pass

    def reject(self, *args, **kwargs):
        pass

    def accept(self, *args, **kwargs):
        pass

    def funnel(self):
        return []

    def summary(self):
        return {"candidates": 0, "entries": 0, "rejected": 0,
                "biggest_filter": None, "biggest_filter_died": 0}

    def recent_near_misses(self, limit=25):
        return []

    def snapshot(self):
        return {"day": None, "summary": self.summary(), "funnel": [],
                "near_misses": []}
