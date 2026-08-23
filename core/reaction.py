"""
==========================================================
What the market did with the news
==========================================================

    "in real markets some stocks earnings with lower business or
     negative reading also considered as positive & stock moves as
     results were not as bad as expected (we know that market prices
     the future right, by expecting the bad results due to any reason
     from regular updates like concalls, company fire accidents, recent
     one company manufacturing facility effected in floods, govt orders
     which will impact the company business.)"
                                    -- operator, 1 August 2026

He is right, and it is the largest hole in everything built up to this
point.

WHAT WAS MISSING
----------------
Every layer this bot has reads BACKWARDS:

    quarterly_results   what was reported
    Earnings Pulse      how the channel graded it
    the FinAI grid      how it compared with consensus
    the Tally           which metrics cleared the bar
    the AI verdict      what one story means

Not one of them knows what the market ALREADY EXPECTED. And a share
price is not a scorecard of last quarter -- it is a bet on the next
one, made before the result landed. So:

    a WEAK result that RALLIES        was less bad than feared
    an EXCELLENT result that FALLS    was already in the price

Both are common, and in both the grade is the wrong signal. On 31 July
the panel showed APTUS as STRONG on +19% YoY profit while the stock
closed -5.77%: our grade and the market's answer pointed opposite ways
and only one of them was spending money.

WHY THIS NEEDS NO AI
--------------------
The market's answer is a number we already store: 1.08 million daily
bars and 11.6 million minute bars. This module reads them. The AI's
job is the other half -- explaining WHY expectations were low, from
the floods and fires and government orders that arrived in the weeks
before -- and that is core/ai_news.py's work, not this file's.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not decide anything. It reports four states, and the two
interesting ones are disagreements:

    CONFIRMS        grade and move point the same way
    PRICED IN       good result, price fell
    LESS BAD        weak result, price rose
    NO REACTION     the move is inside the noise

A disagreement is a reason to look, exactly like the CONFLICT chip.
Which side is right is what outcome tracking will eventually measure;
until then, saying "these two disagree" is honest and saying which one
wins is not.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
from datetime import datetime, timedelta

from core.logger import diagnostic

DAILY_DB = os.path.join("data", "daily_candles.db")

# Below this the day's move says nothing. A stock that closes +0.4% on
# a results day has not answered the question, and calling that
# "confirmation" would put a chip on every row.
NOISE_PCT = 1.5

# The market closes at 15:30. A result filed after that is answered on
# the NEXT session, not the one that has already finished -- reading
# the same day's move would credit the news with a move that happened
# before it existed.
CLOSE_HOUR, CLOSE_MINUTE = 15, 30

POSITIVE = {"EXCELLENT", "GREAT", "GOOD", "STRONG"}
NEGATIVE = {"WEAK", "POOR", "BAD"}


def _as_datetime(value):
    if hasattr(value, "year"):
        return value
    text = str(value or "").strip()
    if not text:
        return None

    # ---- THE OFFSET DECIDES WHICH SESSION ANSWERED. 23 Aug 2026 ----
    #
    #     "we are in IST & its +05:30 asian timing"     -- operator
    #
    # This split the offset off and kept the digits. data/telegram.db
    # stamps "2026-08-23T15:22:30+00:00", which is 20:52 IST -- after
    # the close, so the session that answers it is TOMORROW's. Read as
    # 15:22 it lands eight minutes before the close, and move_after()
    # below scored the news against the session it could not have
    # moved. Every outcome measured through this was attributed to the
    # wrong day.
    #
    # core/feed_clock.to_ist() is the one converter and handles all
    # three stored shapes. Naive here, because the hour/minute
    # comparisons against CLOSE_HOUR are naive.
    try:
        from core.feed_clock import to_ist
        moment = to_ist(text)
        if moment is not None:
            return moment.replace(tzinfo=None)
    except Exception:                                       # noqa: BLE001
        pass
    text = text.replace("Z", "").split("+")[0]
    for shape in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                  "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(shape) + 2].strip(), shape)
        except ValueError:
            continue
    return None


class Reaction:
    """The day's move for a symbol, read from the stored daily bars."""

    def __init__(self, db_path=DAILY_DB):
        self.db_path = db_path
        self._cache = {}

    def _bar(self, symbol, on_date):
        key = (symbol, on_date)
        if key in self._cache:
            return self._cache[key]
        row = None
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT close, prev_close FROM daily_bars "
                "WHERE symbol = ? AND date = ? LIMIT 1",
                (symbol, on_date)).fetchone()
            conn.close()
        except sqlite3.Error as exc:
            diagnostic(f"[REACTION] {symbol} {on_date}: {exc}")
        self._cache[key] = row
        return row

    def _next_session(self, symbol, after_date, limit=6):
        """The next date this symbol actually traded.

        Walked rather than calculated, because a weekend is not the
        only reason a session is missing -- holidays, suspensions and
        a bhavcopy that never arrived all look the same here, and the
        stored bars know which days were real.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT date FROM daily_bars WHERE symbol = ? AND date > ? "
                "ORDER BY date LIMIT 1", (symbol, after_date)).fetchone()
            conn.close()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def move_after(self, symbol, at):
        """(percent, on_date) for the session that answered this news.

        Returns (None, None) when the answer has not happened yet --
        which is the normal case for a result that landed minutes ago,
        and must never be confused with "the market ignored it".
        """
        when = _as_datetime(at)
        if not symbol or when is None:
            return None, None

        on_date = when.strftime("%Y-%m-%d")
        after_close = (when.hour, when.minute) >= (CLOSE_HOUR, CLOSE_MINUTE)
        if after_close:
            on_date = self._next_session(symbol, on_date)
            if on_date is None:
                return None, None

        bar = self._bar(symbol, on_date)
        if not bar or bar[0] is None or not bar[1]:
            return None, None
        try:
            return round((bar[0] / bar[1] - 1.0) * 100.0, 2), on_date
        except (TypeError, ZeroDivisionError):
            return None, None

    def verdict(self, symbol, at, grade):
        """How the market answered a graded result.

        {"state", "move_pct", "on_date", "note"} or None when there is
        no answer yet.
        """
        grade = str(grade or "").upper()
        if grade not in POSITIVE and grade not in NEGATIVE:
            return None
        move, on_date = self.move_after(symbol, at)
        if move is None:
            return None

        good_news = grade in POSITIVE
        if abs(move) < NOISE_PCT:
            state, note = "NO REACTION", (
                f"{grade.title()} result, stock {move:+.1f}% -- the market "
                f"did not move on it")
        elif good_news and move < 0:
            state, note = "PRICED IN", (
                f"ALREADY PRICED: {grade.title()} result, stock {move:+.1f}%")
        elif (not good_news) and move > 0:
            state, note = "LESS BAD", (
                f"LESS BAD THAN FEARED: {grade.title()} result, stock "
                f"{move:+.1f}%")
        else:
            state, note = "CONFIRMS", (
                f"market agrees: {grade.title()} result, stock {move:+.1f}%")
        return {"state": state, "move_pct": move, "on_date": on_date,
                "note": note}
