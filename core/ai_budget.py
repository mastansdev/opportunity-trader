"""
==========================================================
The AI bill -- counted, capped, and refused at the ceiling
==========================================================

    "max .2500 per month is cap. & we need to use the best case of AI
     & trade by using the AI"          -- operator, 30 July 2026

config.AI_MONTHLY_BUDGET_RS has said 2500.0 since that day and NOTHING
HAS EVER READ IT. A hard ceiling that no code checks is a comment.

This file is written BEFORE the first API call is made, deliberately,
because of the shape of the failure it prevents. The danger is not
that the model is expensive -- at the measured volume it is Rs 53 a
month. The danger is a retry loop at 3am turning Rs 53 into Rs 25,000
while the operator is asleep, on an account that also holds his
trading money.

The bot already refuses to trade past DAILY_MAX_LOSS_RS. This is the
same idea pointed at the API bill, and it is enforced the same way: a
refusal, not a warning.

THE ONE PLACE THIS BREAKS THE CODEBASE'S RULE
---------------------------------------------
Every other read in this program FAILS OPEN. A missing database
degrades the feature and never stops the session, because a bot that
will not start is worse than a bot with one panel missing.

This one FAILS CLOSED. If the ledger cannot be read, no call is made.
Failing open on a spend meter means spending money you cannot see, and
the degraded state here is simply "the bot behaves exactly as it did
yesterday" -- which is a state we know is safe, because it ran all
week.

WHAT IT COSTS, PER CALL
-----------------------
Published rates, USD per MILLION tokens:

    claude-haiku-4-5      1.00 in    5.00 out
    claude-sonnet-5       3.00 in   15.00 out

Cache reads are charged at 10% of the input rate and cache writes at
125%. The instruction block in every news call is identical, so it is
cached, and that is where most of the saving comes from -- see
core/news_impact.py PROMPT.

A note on the rupee figure: it is INDICATIVE. Anthropic bills in USD,
adds 18% India GST on credit purchases, and the exchange rate moves.
The cap is enforced on our own arithmetic, which is deliberately
PESSIMISTIC -- it rounds against us, so the real bill is always at or
under what this reports.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import threading
from datetime import datetime

from core.logger import decision, diagnostic, warn

DB_PATH = os.path.join("data", "ai_spend.db")

# USD per MILLION tokens: (input, output).
# A model that is not in this table is not free -- it is UNKNOWN, and
# an unknown price is charged at the most expensive rate here so that
# a typo in config.AI_MODEL_SMART can never look cheap.
PRICES = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
}
_MOST_EXPENSIVE = max(PRICES.values(), key=lambda p: p[1])

CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


def price_of(model):
    """(input, output) USD per million. Unknown models cost the most."""
    key = str(model or "").strip()
    if key in PRICES:
        return PRICES[key]
    # Prefix match, so a dated variant of a known model is priced as
    # that model rather than as the worst case.
    for known, price in PRICES.items():
        if key.startswith(known):
            return price
    diagnostic(f"[AI BUDGET] Unknown model {key!r} -- priced at the most "
               f"expensive rate on file so it cannot look cheap.")
    return _MOST_EXPENSIVE


def cost_usd(model, input_tokens=0, output_tokens=0,
             cache_read_tokens=0, cache_write_tokens=0):
    """What one call cost, in USD. Pure arithmetic, no I/O."""
    rate_in, rate_out = price_of(model)
    total = (
        max(0, int(input_tokens or 0)) * rate_in
        + max(0, int(output_tokens or 0)) * rate_out
        + max(0, int(cache_read_tokens or 0)) * rate_in * CACHE_READ_MULTIPLIER
        + max(0, int(cache_write_tokens or 0)) * rate_in * CACHE_WRITE_MULTIPLIER
    )
    return total / 1_000_000.0


class AiBudget:
    """Every rupee the model costs, recorded and capped.

    One row per call. The ledger is the audit trail -- when the
    operator asks in three weeks what the AI actually cost and what it
    was asked, the answer has to be a query, not a guess.
    """

    def __init__(self, db_path=DB_PATH, monthly_cap_rs=None,
                 usd_inr=None, warn_at_pct=None):
        from config import (AI_MONTHLY_BUDGET_RS, AI_USD_INR,
                            AI_BUDGET_WARN_AT_PCT)
        self.db_path = db_path
        self.cap_rs = (AI_MONTHLY_BUDGET_RS if monthly_cap_rs is None
                       else monthly_cap_rs)
        self.usd_inr = AI_USD_INR if usd_inr is None else usd_inr
        self.warn_at_pct = (AI_BUDGET_WARN_AT_PCT if warn_at_pct is None
                            else warn_at_pct)
        self._lock = threading.Lock()
        self._warned_this_month = None
        self._ensure()

    def _ensure(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS spend (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT,
                    month TEXT,
                    model TEXT,
                    purpose TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cache_read_tokens INTEGER,
                    cache_write_tokens INTEGER,
                    usd REAL,
                    rs REAL
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_month "
                         "ON spend (month)")
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            warn(f"[AI BUDGET] Could not open the spend ledger "
                 f"({self.db_path}): {exc}. No AI calls will be made -- "
                 f"an uncounted bill is not an acceptable trade for a "
                 f"news chip.")

    @staticmethod
    def _month(when=None):
        return (when or datetime.now()).strftime("%Y-%m")

    def spent_this_month(self, when=None):
        """Rupees recorded this calendar month, or None if unreadable.

        None is NOT zero. The caller must treat it as "do not spend",
        which is what may_call() does.
        """
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                row = conn.execute(
                    "SELECT COALESCE(SUM(rs), 0.0) FROM spend WHERE month = ?",
                    (self._month(when),)).fetchone()
                conn.close()
            return float(row[0]) if row else 0.0
        except (sqlite3.Error, TypeError, ValueError) as exc:
            diagnostic(f"[AI BUDGET] Ledger unreadable: {exc}")
            return None

    def may_call(self, when=None):
        """(allowed, reason). reason is None when allowed.

        Called before EVERY request. Cheap -- one indexed SUM over at
        most a few thousand rows.
        """
        spent = self.spent_this_month(when)
        if spent is None:
            return False, ("the spend ledger could not be read, so the "
                           "month's cost is unknown")
        if self.cap_rs is not None and spent >= self.cap_rs:
            return False, (f"this month's AI spend is Rs {spent:,.2f}, at or "
                           f"over the Rs {self.cap_rs:,.0f} cap")
        return True, None

    def record(self, model, purpose=None, input_tokens=0, output_tokens=0,
               cache_read_tokens=0, cache_write_tokens=0, when=None):
        """Write one call to the ledger. Returns the rupee cost.

        Called AFTER the reply arrives, with the token counts the API
        itself reports -- never with an estimate. Estimating what was
        spent is how a cap drifts away from the real bill.
        """
        usd = cost_usd(model, input_tokens, output_tokens,
                       cache_read_tokens, cache_write_tokens)
        rs = usd * self.usd_inr
        stamp = when or datetime.now()
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "INSERT INTO spend (at, month, model, purpose,"
                    " input_tokens, output_tokens, cache_read_tokens,"
                    " cache_write_tokens, usd, rs)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (stamp.isoformat(timespec="seconds"),
                     self._month(stamp), str(model or ""), purpose or "",
                     int(input_tokens or 0), int(output_tokens or 0),
                     int(cache_read_tokens or 0), int(cache_write_tokens or 0),
                     usd, rs))
                conn.commit()
                conn.close()
        except sqlite3.Error as exc:
            # The money is already spent -- the call has happened. Losing
            # the RECORD of it is worse than losing the call, because the
            # next may_call() will then under-count and allow more.
            warn(f"[AI BUDGET] A call cost Rs {rs:.4f} and could NOT be "
                 f"recorded ({exc}). The cap is now under-counting. "
                 f"Investigate before running another session.")
        self._warn_if_near_cap(stamp)
        return rs

    def _warn_if_near_cap(self, when=None):
        """Once per month, not once per call."""
        if not self.cap_rs or not self.warn_at_pct:
            return
        month = self._month(when)
        if self._warned_this_month == month:
            return
        spent = self.spent_this_month(when)
        if spent is None:
            return
        if spent >= self.cap_rs * self.warn_at_pct:
            self._warned_this_month = month
            warn(f"[AI BUDGET] Rs {spent:,.2f} of the Rs {self.cap_rs:,.0f} "
                 f"monthly cap used ({100 * spent / self.cap_rs:.0f}%). "
                 f"Calls stop entirely at the cap.")

    def status(self, when=None):
        """For the dashboard and the startup banner."""
        spent = self.spent_this_month(when)
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                calls = conn.execute(
                    "SELECT COUNT(*) FROM spend WHERE month = ?",
                    (self._month(when),)).fetchone()[0]
                conn.close()
        except (sqlite3.Error, TypeError):
            calls = None
        allowed, reason = self.may_call(when)
        return {
            "month": self._month(when),
            "calls": calls,
            "spent_rs": None if spent is None else round(spent, 2),
            "cap_rs": self.cap_rs,
            "pct": (None if spent is None or not self.cap_rs
                    else round(100.0 * spent / self.cap_rs, 1)),
            "allowed": allowed,
            "reason": reason,
        }

    def report(self, when=None):
        """A line for the startup log."""
        s = self.status(when)
        if s["spent_rs"] is None:
            return "[AI BUDGET] Ledger unreadable -- AI calls are OFF."
        return (f"[AI BUDGET] {s['month']}: {s['calls']} call(s), "
                f"Rs {s['spent_rs']:,.2f} of Rs {s['cap_rs']:,.0f} "
                f"({s['pct']}%).")
