"""
==========================================================
Results gate -- block BEFORE the numbers, allow AFTER good ones
==========================================================

THE BUG THIS FIXES
------------------
core/engine.py refused an entry on any stock reporting results today:

    if symbol in self.earnings_calendar.get(candle_date.isoformat(), ()):
        return                      # silent, no log

The comment above it was honest about why:

    "A reporting stock's move is a news reaction, not organic momentum
     -- the ATR system can't tell the difference."

TRUE when written on 2026-07-24. The bot had no way to read a result.
It now does: the filing -> PDF -> grade chain works live (MOLDTKPAC came
back STRONG, sales +26% QoQ, PAT +24% QoQ). The premise expired.

And it is the operator's entire strategy:

    "Entry only on real reasons: results genuinely better than previous
     quarter with better guidance, order wins, approvals, deals."

So the one place results touched the trading engine, it did the exact
opposite of the plan. On 2026-07-28, CUB reported and went +8.47%; this
rule would have refused it. 27 companies reported that day, 52 the next.

WHAT REPLACES IT
----------------
The old rule was right about half the problem. Splitting it:

    BEFORE the filing lands    outcome unknown, a coin flip     BLOCK
    AFTER it, graded STRONG    the reason the operator wants    ALLOW
    AFTER it, graded GOOD      good enough                      ALLOW
    AFTER it, graded MIXED     no edge either way               BLOCK
    AFTER it, graded WEAK      actively bad news                BLOCK
    AFTER it, no grade yet     PDF not parsed -- still unknown  BLOCK

FAIL CLOSED, DELIBERATELY. Every unknown blocks. A stock reporting today
whose numbers we cannot read is exactly the coin flip the original rule
was written to avoid, and this module must not quietly widen the door
just because a lookup failed.

NOT A PREDICTION. grade() has never been validated against price -- see
core/quarterly_results.py's own docstring. A STRONG grade means the
numbers improved, not that the stock will rise. This gate decides
whether the bot is ALLOWED to consider a name, never whether it should.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import decision, diagnostic

ALLOW_GRADES = ("STRONG", "GOOD")

# ---- THE PUBLISHER'S OWN GRADES. His rule, 8 August 2026. ----
#
#     "@ results time = EXCELLENT, GREAT, GOOD"
#
# These are the words Earnings Pulse and Earnings Pro print on the
# chip. They are NOT the same vocabulary as ALLOW_GRADES above, which
# is what core/quarterly_results.py computes from parsed numbers.
CHIP_GRADES = ("EXCELLENT", "GREAT", "GOOD")

# The graded map changes when a card arrives, not tick by tick.
_GRADED = {}
_GRADED_TTL_SECONDS = 60.0

# ---- AND THE TAPE MUST AGREE. ----
#
#     "+ volumes both must agree"
#
# A published grade says the quarter was fine. It does not say anybody
# is buying. Volume against the stock's own normal is the second
# opinion, and both have to say yes. Same 1.5x bar core/select.py
# uses, imported so the two cannot drift apart.
try:
    from core.select import MIN_VOLUME_RATIO as CHIP_MIN_VOLUME_RATIO
except Exception:                                          # noqa: BLE001
    CHIP_MIN_VOLUME_RATIO = 1.5

REASON_VOLUME_DISAGREES = ("graded, but the volume does not confirm it -- "
                           "the grade and the tape must both agree")
BLOCK_GRADES = ("MIXED", "WEAK")

REASON_NOT_REPORTING = None            # nothing to say, no block
REASON_NOT_FILED = "reports today, numbers not out yet"
REASON_NO_GRADE = "filed today, numbers not read yet"
REASON_BAD_GRADE = "filed today, numbers graded {grade}"


class ResultsGate:
    """Decides whether a stock reporting TODAY may be entered.

    Every dependency is optional. Missing any of them falls back to the
    old behaviour -- block on results day -- which is the safe direction.
    """

    def __init__(self, earnings_calendar=None, announcements=None,
                 quarterly=None):
        # earnings_calendar : {"2026-07-28": {"CUB", "COFORGE", ...}}
        # announcements     : core/announcement_watcher.py (has it FILED?)
        # quarterly         : core/quarterly_results.py    (what GRADE?)
        self.earnings_calendar = earnings_calendar or {}
        self.announcements = announcements
        self.quarterly = quarterly
        self._logged = set()

    # ------------------------------------------------------------

    def reports_today(self, symbol, on_date):
        if on_date is None:
            return False
        try:
            return symbol in self.earnings_calendar.get(on_date.isoformat(), ())
        except Exception:                                  # noqa: BLE001
            return False

    def has_filed(self, symbol):
        """Has a RESULTS announcement actually landed for this symbol?

        Being on the calendar is a PLAN. The filing is the event. A
        company scheduled for 14:00 has not reported at 09:20, and
        entering before the numbers is the coin flip we are avoiding.
        """
        if self.announcements is None:
            return False
        try:
            record = self.announcements.for_symbol(symbol)
        except Exception:                                  # noqa: BLE001
            return False
        return bool(record) and record.get("kind") == "RESULTS"

    def grade_for(self, symbol):
        """STRONG / GOOD / MIXED / WEAK, or None if not read yet."""
        if self.quarterly is None:
            return None
        try:
            # ---- IT NEVER ONCE RETURNED A GRADE. 30 Aug 2026. ----
            #
            # compare() returns a dict of EIGHT keys -- symbol, period,
            # latest, qoq, yoy, grade, summary, unreliable. Unpacking a
            # dict yields its KEYS, so `qoq, yoy = compare(symbol)`
            # raised ValueError on every call, the except below
            # swallowed it, and this returned None every single time.
            #
            # Proved on the live store: compare("TCS") carries
            # grade="WEAK" and this function answered None.
            #
            # WHAT IT COST. block_reason() asks the published chip
            # first, so a stock with an EXCELLENT / GREAT / GOOD card
            # was unaffected. Everything else fell through to
            # REASON_NO_GRADE -- "numbers not read yet" -- on its
            # results day, with the numbers sitting in the store and a
            # grade already computed from them.
            #
            # Which is the same fault as 5 August, one layer along:
            # "the weaker source silently vetoed the stronger one, and
            # the refusal read like a data problem rather than a
            # decision". This time the weaker source was an exception.
            #
            # compare() already sets grade=None when the figures are
            # not believable, so reading its own answer is both correct
            # and less code than recomputing it.
            got = self.quarterly.compare(symbol)
            return got.get("grade") if isinstance(got, dict) else None
        except Exception:                                  # noqa: BLE001
            return None

    # ------------------------------------------------------------

    def _published_grade(self, symbol):
        """EXCELLENT / GREAT / GOOD off the chip, or None.

        The grade the publisher printed, read from the same place Row 1
        reads it -- core/watchlist_builder.py -- so the two can never
        disagree about what a stock was graded.
        """
        # ---- ONCE A MINUTE, NOT ONCE A SYMBOL. 9 August 2026. ----
        #
        # graded_symbols() reads the whole Telegram store and runs
        # pulse_ratings over every message. Calling it per symbol per
        # cycle hung a test for 30 seconds -- and this sits on the live
        # entry path, so it would have hung the bot. That is the third
        # time this week I have put a per-symbol database read inside a
        # per-symbol loop.
        #
        # The graded map changes when a card arrives, not tick by tick.
        import time
        now_s = time.time()
        if now_s - _GRADED.get("at", 0.0) > _GRADED_TTL_SECONDS:
            try:
                from core import watchlist_builder
                _GRADED["map"] = watchlist_builder.graded_symbols() or {}
            except Exception:                              # noqa: BLE001
                _GRADED["map"] = {}
            _GRADED["at"] = now_s
        row = (_GRADED.get("map") or {}).get(str(symbol or "").upper())
        return str((row or {}).get("grade") or "").upper() or None

    def _volume_agrees(self, symbol, volume_ratio_of=None):
        """Is the tape confirming the grade?

        Missing volume is NOT a refusal. A stock the publisher graded
        EXCELLENT must not be blocked because our own volume read
        failed -- that is the silent veto this whole section removes.
        Unknown means "no objection", and core/select.py still applies
        the real volume test before anything is bought.
        """
        reader = volume_ratio_of or getattr(self, "volume_ratio_of", None)
        if reader is None:
            return True
        try:
            ratio = reader(symbol)
        except Exception:                                  # noqa: BLE001
            return True
        if ratio is None:
            return True
        try:
            return float(ratio) >= CHIP_MIN_VOLUME_RATIO
        except (TypeError, ValueError):
            return True

    def block_reason(self, symbol, on_date):
        """None means the stock may be entered. A string means blocked,
        and the string is shown to the operator."""
        if not self.reports_today(symbol, on_date):
            return REASON_NOT_REPORTING

        # ==========================================================
        # THE PUBLISHED CHIP IS THE GRADE.  8 August 2026.
        # ==========================================================
        #
        #     "results gate open for the chips with excellent, great,
        #      good + volumes both must agree."
        #
        # This asked the same question twice from two different places.
        # Row 1 reads messages.grade -- what Earnings Pulse actually
        # PUBLISHED. This then ignored that and recomputed its own
        # grade from core/quarterly_results.py, out of parsed QoQ/YoY
        # numbers. When that second read found nothing it returned
        # "numbers not read yet" and blocked the trade.
        #
        # So a stock could hold a published GOOD card, clear volume,
        # clear the move, clear headroom -- and be refused because a
        # SECOND lookup failed. The weaker source silently vetoed the
        # stronger one, and the refusal read like a data problem rather
        # than a decision.
        #
        # SHILPAMED, 5 August: GOOD on four separate cards at 13:51,
        # 136x its own volume. Exactly the shape this used to refuse.
        #
        # Now: if the publisher graded it EXCELLENT / GREAT / GOOD and
        # the tape agrees, that is the answer. The recomputed grade is
        # still consulted BELOW, for stocks that have no chip at all.
        chip = self._published_grade(symbol)
        if chip in CHIP_GRADES:
            if self._volume_agrees(symbol):
                return None
            return REASON_VOLUME_DISAGREES

        if not self.has_filed(symbol):
            return REASON_NOT_FILED

        grade = self.grade_for(symbol)
        if grade is None:
            return REASON_NO_GRADE
        if grade in ALLOW_GRADES:
            return None
        return REASON_BAD_GRADE.format(grade=grade)

    def allows(self, symbol, on_date):
        """True if this stock may be entered today.

        Logs the FIRST time a symbol is allowed through on its results
        day -- that moment is the operator's whole strategy firing, and
        it should be visible rather than silent.
        """
        reason = self.block_reason(symbol, on_date)
        if reason is None:
            if self.reports_today(symbol, on_date) and symbol not in self._logged:
                self._logged.add(symbol)
                decision(
                    f"[RESULTS_GATE] {symbol} ALLOWED -- reported today and "
                    f"the numbers are {self.grade_for(symbol)}. This is the "
                    f"trade the reason gate exists for."
                )
            return True

        key = (symbol, reason)
        if key not in self._logged:
            self._logged.add(key)
            diagnostic(f"[RESULTS_GATE] {symbol} blocked -- {reason}.")
        return False

    def reset(self):
        self._logged.clear()
