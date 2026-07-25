"""
==========================================================
News Bot -- AI Call Budget
==========================================================

Enforces MAX_AI_CALLS_PER_DAY (news_bot/config.py) so a heavy
news day can't run away on Claude API cost -- see the cost
control decision in PHASE3_NEWS_DESIGN.md, section 4.

Persisted to disk and date-tagged, same reasoning as
core/state_store.py: if a restart reset the counter to zero,
the DAILY cap would mean nothing -- someone could blow the
real daily budget by just restarting the bot a few times.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
from datetime import datetime

from core.logger import warn
from news_bot.config import MAX_AI_CALLS_PER_DAY

BUDGET_PATH = os.path.join("data", "ai_call_budget.json")


class CallBudget:

    def __init__(self, path=BUDGET_PATH, limit=MAX_AI_CALLS_PER_DAY):
        self.path = path
        self.limit = limit
        self._date, self._count = self._read()

    # --------------------------------------------------

    def _read(self):
        if not os.path.exists(self.path):
            return datetime.now().date().isoformat(), 0

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return payload.get("date", ""), int(payload.get("count", 0))
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
            warn(
                f"[NEWS_BOT] AI call budget file unreadable, starting "
                f"at 0 for today: {e}"
            )
            return datetime.now().date().isoformat(), 0

    def _write(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"date": self._date, "count": self._count}, f)
        os.replace(tmp_path, self.path)

    def _roll_if_new_day(self):
        today = datetime.now().date().isoformat()
        if self._date != today:
            self._date = today
            self._count = 0

    # --------------------------------------------------

    def count_today(self):
        self._roll_if_new_day()
        return self._count

    def remaining(self):
        self._roll_if_new_day()
        return max(0, self.limit - self._count)

    def can_spend(self, n=1):
        return self.remaining() >= n

    def record_call(self):
        """Counts one call as spent, right now, unconditionally.
        Called by the caller (pipeline.py) at the moment it
        commits to making the API request -- not after seeing
        whether the response parsed cleanly, since the network
        round-trip itself is what costs money."""
        self._roll_if_new_day()
        self._count += 1
        self._write()
