"""
==========================================================
Morning brief -- the AI layer, finally
==========================================================

    "in this era of AI! again why human needs to manual check ? why
     can't bot do all this and report to the user"
                                        -- operator, 2026-07-28

The operator's architecture, drawn six months ago:

    AI + NEWS ENGINE + BOT MEMORY + MY EXPERIENCE + EARNING PULSE DATA

News engine: built. Bot memory: built. Earning pulse: built. AI: never
existed. A grep of every file on 2026-07-28 returned zero hits for
anthropic, openai, claude, llm or gpt. ANTHROPIC_API_KEY sat in config,
unread, for months.

This is that missing piece.

WHAT IT DOES
------------
Reads what core/premarket.py collected overnight plus today's filings
and news, and writes three or four sentences: what moved, what is worth
watching, and what would make today unusual.

WHAT IT IS NOT ALLOWED TO DO
----------------------------
It does not pick stocks. It does not size. It does not place orders.
Nothing in the engine reads it. It is a BRIEFING, and the operator
decides.

That restraint is the point. The chain his own workflow chart draws --
crude up, so inflation up, so RBI hikes, so banks benefit -- is obvious
backwards and unreliable forwards. An AI writing that sentence will
sound authoritative every single morning and be wrong often enough to
cost money. So it advises; it never acts.

EVERY BRIEF IS RECORDED
-----------------------
Written to data/morning_briefs.json with the date and the numbers it
saw. In a month there will be twenty of them, and they can be read back
against what actually happened.

Same discipline as the reason gate: it earns a vote only once the
numbers say it deserves one. Until then it is a paragraph on a screen.

FAILURE POSTURE
---------------
No API key, no network, a bad response, a slow response -- every one of
them produces NO BRIEF and a plain note saying so. It never falls back
to a generic paragraph. A confident-sounding brief generated from
nothing is worse than a blank space, because a blank space cannot
mislead anyone.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import threading
from datetime import datetime

from core.logger import decision, diagnostic, warn

STORE_PATH = os.path.join("data", "morning_briefs.json")

MODEL = "claude-sonnet-5"
MAX_TOKENS = 700
TIMEOUT_SECONDS = 30

SYSTEM_PROMPT = """You brief a retail Indian equity trader before the \
NSE opens. He trades long only, on MTF, and enters on real reasons: \
results better than the previous quarter, order wins, approvals, broker \
upgrades.

Write 3-5 short sentences. Plain English, no jargon, no bullet points.

Cover only:
  1. What actually moved overnight, with the numbers.
  2. Anything that is genuinely unusual rather than ordinary drift.
  3. What is scheduled today that could matter.

RULES, and they matter more than being interesting:
- Never name a stock to buy or sell.
- Never predict a direction. "Crude fell 3%" is a fact. "Crude fell so \
oil marketing companies should rise" is a guess dressed as analysis, \
and it is exactly what gets people hurt.
- If the overnight session was unremarkable, say so in one sentence. A \
quiet night is useful information. Do not manufacture significance.
- If a number is missing, ignore it. Never estimate it.
"""


class MorningBrief:
    """Three sentences about the overnight session. Opinion, recorded."""

    def __init__(self, client=None, store_path=STORE_PATH, model=MODEL,
                 budget=None):
        # client injected so tests never touch the network and a missing
        # key degrades to "no brief" rather than a crash.
        self._client = client
        self.store_path = store_path
        self.model = model
        # ---- IT SPENT WITHOUT RECORDING. 16 August 2026. ----
        # _record() below saves the BRIEF TEXT, not the cost, and the
        # name made it look accounted for. data/ai_spend.db knew only
        # news_direction and ai_check; this call was invisible to both
        # the ledger and the Rs 2,500 cap. Injectable for tests.
        if budget is None:
            from core.ai_budget import AiBudget
            budget = AiBudget()
        self._budget = budget
        self._lock = threading.Lock()
        self._today = None

    # ------------------------------------------------------------

    def _record(self, brief, context):
        try:
            history = []
            if os.path.exists(self.store_path):
                with open(self.store_path, encoding="utf-8") as fh:
                    history = json.load(fh)
            history.insert(0, {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "at": datetime.now().strftime("%H:%M:%S"),
                "brief": brief,
                "context": context[:4000],
                "model": self.model,
            })
            del history[60:]
            directory = os.path.dirname(self.store_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as fh:
                json.dump(history, fh, indent=1)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[BRIEF] Could not record ({exc}).")

    # ------------------------------------------------------------

    def generate(self, premarket_text, extra_context=""):
        """Write today's brief. Returns the text, or None.

        None means NO BRIEF -- never a generic paragraph. A confident
        sentence generated from nothing is worse than a blank space.
        """
        if self._client is None:
            warn("[BRIEF] No AI client wired -- no brief today. "
                 "Set ANTHROPIC_API_KEY to enable it.")
            return None

        if not premarket_text or "No overnight data" in premarket_text:
            warn("[BRIEF] No overnight numbers to brief on. Skipped -- "
                 "a brief written from nothing would be fiction.")
            return None

        context = premarket_text
        if extra_context:
            context += "\n\n" + extra_context

        allowed, why = self._budget.may_call()
        if not allowed:
            warn(f"[BRIEF] Not calling: {why}. No brief today.")
            return None

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                self._budget.record(
                    self.model, purpose="morning_brief",
                    input_tokens=getattr(usage, "input_tokens", 0),
                    output_tokens=getattr(usage, "output_tokens", 0),
                    cache_read_tokens=getattr(
                        usage, "cache_read_input_tokens", 0) or 0,
                    cache_write_tokens=getattr(
                        usage, "cache_creation_input_tokens", 0) or 0)
            parts = getattr(response, "content", None) or []
            text = "".join(getattr(p, "text", "") for p in parts).strip()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BRIEF] Could not generate ({exc}). No brief today.")
            return None

        if not text:
            warn("[BRIEF] Empty response. No brief today.")
            return None

        with self._lock:
            self._today = text
        self._record(text, context)
        decision("[BRIEF] Morning brief written. It is an OPINION -- "
                 "nothing in the bot reads it, and it is recorded so it "
                 "can be judged in a month.")
        return text

    # ------------------------------------------------------------

    def today(self):
        with self._lock:
            return self._today

    def history(self, limit=30):
        try:
            with open(self.store_path, encoding="utf-8") as fh:
                return json.load(fh)[:limit]
        except (OSError, json.JSONDecodeError):
            return []

    def snapshot(self):
        """What the dashboard renders."""
        text = self.today()
        return {
            "brief": text,
            "available": bool(text),
            "note": ("AI opinion, recorded so it can be judged later. "
                     "Nothing in the bot acts on this."),
        }


def anthropic_client():
    """The live client, or None. None is a valid outcome -- no key means
    no brief, which is honest."""
    # ---- THE MASTER SWITCH. 10 August 2026. ----
    # config.AI_ENABLED says "Nothing calls out while False". Three
    # modules built a client without asking, so on 10 August every call
    # went out and came back "credit balance is too low" -- silently,
    # as DEBUG lines, all afternoon.
    try:
        from config import AI_ENABLED
    except Exception:                                      # noqa: BLE001
        AI_ENABLED = False
    if not AI_ENABLED:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SECONDS)
    except Exception as exc:                               # noqa: BLE001
        warn(f"[BRIEF] Anthropic client unavailable ({exc}).")
        return None
