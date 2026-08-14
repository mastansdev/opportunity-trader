"""
==========================================================
Fresh breakouts -- the window that never existed
==========================================================

Operator, 2026-07-28 (market open, 18 minutes before close):

    "by this dashboard new / fresh orb breakouts cannot be identified
     at all. today i missed some of the best movers - TVS."

TVS WAS NOT MISSED BY THE BOT
-----------------------------
Searching that same session's log for breakout signals found dozens of
real ones:

    TVSMOTOR  NTPCGREEN  PINELABS  MSUMI     MOTHERSON  LOTUSDEV
    ALOKINDS  PPLPHARMA  OLAELEC   LEMONTREE RAIN       KTKBANK
    OIL       CRIZAC     VGUARD    HEG       MARKSANS   RVNL
    PNB       IRFC       KOTAKBANK ...

Every one of them was computed by the engine. Every one was logged.
Every one was then refused in silence -- the market regime read
SHORT_ONLY (445 of 665 symbols declining, past the 0.60 threshold), and
engine.py's regime check returns without a word for a LONG in a
SHORT_ONLY tape.

And there was nowhere on the dashboard that showed a breakout at all.

So the signal existed, the refusal existed, and the operator could see
neither. He watched TVSMOTOR run and had no way to know his own bot had
already spotted it.

WHY THIS RECORDS *BEFORE* THE GATES, NOT AFTER
----------------------------------------------
record() is called at the SIGNAL, not at the entry. A breakout that was
blocked is exactly as interesting as one that was taken -- more so,
because the blocked ones are where the operator's judgement and the
bot's rules disagree, and that disagreement is the whole reason he
wanted a bot beside him rather than instead of him.

So every breakout lands here with WHY it was or wasn't taken attached.

WHAT A ROW MEANS
----------------
    ACTIVE   price is still beyond the range it broke
    FADED    price has fallen back inside -- the breakout failed

A faded row is kept, greyed, and loses its button. A breakout that
quietly vanishes from the screen teaches nothing; one that visibly
fails teaches how often they fail.

Newest first, with an age in seconds, because a breakout is worth
something only while it is fresh. Volume multiple sits beside it
deliberately: this project's own 7.5-year study found a big move on 6x+
volume had NEGATIVE edge in 6 of 7 years, while quiet-volume moves
averaged +3.37%. Loud is not the same as good.

NEVER RAISES. A bookkeeping panel must not be able to break a tick.

Author : H&M Opportunity Trader
==========================================================
"""

import threading
from datetime import datetime

MAX_ROWS = 60

STATUS_ACTIVE = "ACTIVE"
STATUS_FADED = "FADED"

LONG = "LONG"
SHORT = "SHORT"

# A TEST is not a failed breakout. Operator's RADICO chart, 2026-07-28:
# ORB high 4,182, and price pressed against it for HOURS without ever
# closing through, then broke late and ran to 4,335. None of that
# pressure showed up anywhere, because the engine only wakes on a CLOSE
# beyond the range.
#
#   TEST     price reaches the level, gets rejected, never closes above
#   ATTEMPT  price CLOSES beyond the range, then falls back inside
#
# The test count is arguably the more useful of the two: it is what the
# operator's eye is already doing on the chart, and it builds BEFORE the
# break rather than after it.
TEST_ZONE_PCT = 0.002        # within 0.2% of the boundary = at the level
TEST_RESET_PCT = 0.006       # must fall 0.6% away before it counts again


class BreakoutFeed:
    """Every structural signal the engine produced today, in order,
    with what happened to it."""

    def __init__(self, max_rows=MAX_ROWS):
        self._lock = threading.Lock()
        self._rows = {}          # symbol+direction -> row
        self._max_rows = max_rows
        self._tests = {}         # symbol+direction -> {"count", "at_level"}

    # ------------------------------------------------------------

    @staticmethod
    def _key(symbol, direction):
        return f"{symbol}|{direction}"

    def record(self, symbol, direction, price, orb_high, orb_low,
               tick_time=None, taken=False, blocked_reason=None,
               volume_mult=None):
        """A structural signal fired. Called BEFORE the entry gates, so
        blocked breakouts are recorded too.

        Re-firing the same symbol+direction updates the existing row
        rather than adding another -- a breakout that keeps triggering
        every candle is ONE event, not forty. first_seen is preserved so
        the age clock keeps counting from the real first break.
        """
        try:
            key = self._key(symbol, direction)
            now = tick_time or datetime.now()
            with self._lock:
                row = self._rows.get(key)
                if row is None:
                    row = {
                        "symbol": symbol,
                        "direction": direction,
                        "first_seen": now,
                        "first_ever": now,
                        "break_price": price,
                        "orb_high": orb_high,
                        "orb_low": orb_low,
                        "status": STATUS_ACTIVE,
                        "fired_count": 0,
                        "attempt": 1,
                    }
                    self._rows[key] = row
                elif row["status"] == STATUS_FADED:
                    # A NEW ATTEMPT. Price went back inside the range and
                    # has now crossed out again -- operator's question,
                    # 2026-07-28: "by what attempt will get more opinion
                    # on breakout right?"
                    #
                    # fired_count (how many candles it held outside) is
                    # PERSISTENCE. This is different: how many separate
                    # times the stock has tried this level today.
                    #
                    # NOTE: attempt number is DISPLAYED, never scored.
                    # The lore says "third time breaks"; an equally
                    # plausible story says each failed attempt burns
                    # buying pressure. Nobody here has measured which is
                    # true, so it does not touch rank or size until the
                    # 61-session study says something. Same discipline
                    # the shortlist is held to.
                    row["attempt"] += 1
                    row["status"] = STATUS_ACTIVE
                    row["first_seen"] = now      # clock for THIS attempt
                    row["break_price"] = price
                    row["fired_count"] = 0
                    row["blocked_reason"] = None
                    row["taken"] = False
                row["last_seen"] = now
                row["fired_count"] += 1
                row["taken"] = bool(taken)
                row["blocked_reason"] = blocked_reason
                if volume_mult is not None:
                    row["volume_mult"] = volume_mult
                self._trim_locked()
        except Exception:                                  # noqa: BLE001
            pass

    def note_touch(self, symbol, price, orb_high, orb_low):
        """Count how many times price has TESTED the range boundary
        without closing through it.

        Called on every tick, so it must stay cheap: two float compares
        and a dict lookup, no allocation on the common path.

        HYSTERESIS IS THE WHOLE TRICK. Without it, a stock hovering at
        its ORB high would clock up hundreds of "tests" in a minute. A
        test counts once when price enters the zone, and cannot count
        again until price has pulled back TEST_RESET_PCT away. So the
        RADICO chart's hours of pressing against 4,182 register as the
        handful of real approaches the operator's eye sees, not as noise.
        """
        try:
            if not price or not orb_high or not orb_low:
                return
            for direction, boundary, inside in (
                (LONG, orb_high, True), (SHORT, orb_low, False),
            ):
                if direction == LONG:
                    at_level = price >= boundary * (1 - TEST_ZONE_PCT)
                    cleared = price < boundary * (1 - TEST_RESET_PCT)
                else:
                    at_level = price <= boundary * (1 + TEST_ZONE_PCT)
                    cleared = price > boundary * (1 + TEST_RESET_PCT)
                if not at_level and not cleared:
                    continue
                key = self._key(symbol, direction)
                with self._lock:
                    state = self._tests.get(key)
                    if state is None:
                        state = {"count": 0, "at_level": False}
                        self._tests[key] = state
                    if at_level and not state["at_level"]:
                        state["count"] += 1
                        state["at_level"] = True
                    elif cleared and state["at_level"]:
                        state["at_level"] = False
        except Exception:                                  # noqa: BLE001
            pass

    def test_count(self, symbol, direction):
        with self._lock:
            state = self._tests.get(self._key(symbol, direction))
            return state["count"] if state else 0

    def note_block(self, symbol, direction, reason):
        """Why this breakout was refused. Separate from record() because
        the refusal happens further down the gate chain, after the
        signal is already on the panel."""
        try:
            with self._lock:
                row = self._rows.get(self._key(symbol, direction))
                if row is not None:
                    row["blocked_reason"] = reason
                    row["taken"] = False
        except Exception:                                  # noqa: BLE001
            pass

    def attempt_for(self, symbol, direction):
        """How many separate times this stock has tried this level
        today, or None if it has not fired at all.

        DISPLAYED AND RECORDED, never scored. The lore says "third time
        breaks"; an equally plausible story says each failed attempt
        burns buying pressure. Nobody here has measured which is true,
        so it goes in the journal and waits for evidence.
        """
        try:
            with self._lock:
                row = self._rows.get(self._key(symbol, direction))
                return row.get("attempt") if row else None
        except Exception:                                  # noqa: BLE001
            return None

    def mark_taken(self, symbol, direction):
        """The bot actually entered. No BUY button on a row already in
        the book -- the engine refuses pyramiding, so offering it lies."""
        try:
            with self._lock:
                row = self._rows.get(self._key(symbol, direction))
                if row is not None:
                    row["taken"] = True
                    row["blocked_reason"] = None
        except Exception:                                  # noqa: BLE001
            pass

    def update_price(self, symbol, price):
        """Mark a breakout FADED once price is back inside the range it
        broke. Cheap enough for the tick path -- a dict lookup on two
        keys and a float compare, nothing more.

        A faded row is NEVER deleted. The operator learns more from
        seeing a breakout fail than from it disappearing.
        """
        try:
            with self._lock:
                for direction in (LONG, SHORT):
                    row = self._rows.get(self._key(symbol, direction))
                    if row is None or row["status"] != STATUS_ACTIVE:
                        continue
                    if direction == LONG and price < row["orb_high"]:
                        row["status"] = STATUS_FADED
                    elif direction == SHORT and price > row["orb_low"]:
                        row["status"] = STATUS_FADED
        except Exception:                                  # noqa: BLE001
            pass

    def _trim_locked(self):
        if len(self._rows) <= self._max_rows:
            return
        ordered = sorted(self._rows.items(),
                         key=lambda kv: kv[1]["first_seen"])
        for key, _ in ordered[:len(self._rows) - self._max_rows]:
            self._rows.pop(key, None)

    # ------------------------------------------------------------

    def snapshot(self, now=None, limit=None):
        """Newest first. Each row carries its own age so the panel does
        not have to do clock arithmetic in the browser."""
        try:
            now = now or datetime.now()
            with self._lock:
                rows = list(self._rows.values())
            rows.sort(key=lambda r: r["first_seen"], reverse=True)
            if limit:
                rows = rows[:limit]
            out = []
            for r in rows:
                age = (now - r["first_seen"]).total_seconds()
                out.append({
                    "symbol": r["symbol"],
                    "direction": r["direction"],
                    "price": round(r["break_price"], 2),
                    "orb_high": round(r["orb_high"], 2),
                    "orb_low": round(r["orb_low"], 2),
                    "status": r["status"],
                    "age_seconds": int(max(0, age)),
                    "age_label": _age_label(age),
                    "taken": r.get("taken", False),
                    "blocked_reason": r.get("blocked_reason"),
                    "fired_count": r.get("fired_count", 0),
                    "volume_mult": r.get("volume_mult"),
                    "attempt": r.get("attempt", 1),
                    "tests": (self._tests.get(
                        self._key(r["symbol"], r["direction"]), {}
                    ).get("count", 0)),
                    "attempt_label": _attempt_label(r.get("attempt", 1)),
                    "first_seen": r["first_seen"].strftime("%H:%M:%S"),
                    "first_ever": r.get("first_ever", r["first_seen"])
                                   .strftime("%H:%M:%S"),
                    "actionable": (r["status"] == STATUS_ACTIVE
                                   and not r.get("taken", False)),
                })
            return out
        except Exception:                                  # noqa: BLE001
            return []

    def count(self):
        with self._lock:
            return len(self._rows)

    def clear(self):
        with self._lock:
            self._rows.clear()


def _attempt_label(attempt):
    """"1st try", "2nd try", "3rd try". Shown, never scored -- see the
    note in record() for why."""
    attempt = int(attempt or 1)
    if attempt == 1:
        return "1st try"
    if attempt == 2:
        return "2nd try"
    if attempt == 3:
        return "3rd try"
    return f"{attempt}th try"


def _age_label(seconds):
    """Short enough to sit in a 46px column."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    return f"{minutes // 60}h {minutes % 60}m ago"
