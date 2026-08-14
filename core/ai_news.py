"""
==========================================================
One story, one company, one verdict
==========================================================

    "we are receiving news. results and not using for decision making
     right? atleast they are presened in why ? section"

    "if today result came excellent & if the stock moved high even
     though we get them in top gainers but without why cards. i cannot
     trust the price movement right? genuine gap between trusted &
     vague buying"

THE GAP, MEASURED
-----------------
On 31 July 2026 the event store held 141 stock-scope events with a
kind and no direction:

    107 NEWS      "GAIL Board Approves Merger Of Konkan LNG With Co"
     34 ORDER     "BEL wins Rs 847 crore order for defense products"

Every one was collected correctly, matched to the right company, and
stored. None of them said whether it was GOOD or BAD, because no
keyword table can answer that. The bot knew something had happened
and nothing about what it meant.

WHAT THIS ASKS, AND WHAT IT DOES NOT
------------------------------------
One question, narrowly: for THIS company, does this story point up or
down, how sure are you, and why in one sentence.

It does not pick trades. It does not size anything. It does not move a
stop. Its answer is recorded and displayed and -- until enough of them
have been checked against what the stocks actually did -- worth
exactly zero to the score. That staircase is written out in config.py
and this file sits on step one.

UNRELATED IS THE ANSWER THAT EARNS ITS KEEP
-------------------------------------------
The keyword matcher produced these pairings, and they were on screen:

    DOLLAR     "The Indian Rupee recorded its strongest weekly gain"
    CENTRALBK  "European shares reached a record high on Friday"
    URBANCO    "Afcons secures Rs 900 crore in new infrastructure"

DOLLAR matched the word "dollar". A model allowed only POSITIVE or
NEGATIVE would pick one confidently and make the panel worse than
keywords left it. Allowed to say UNRELATED, it removes the chip
instead -- so the model's first useful job is cleaning up after the
matcher rather than adding to it.

COST
----
Every call goes through core/ai_budget.py first, which refuses at the
monthly cap and records what was actually charged. At the measured
141-event backfill this costs about a rupee; the ongoing rate is
around Rs 53 a month.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import re
import threading

from core.logger import decision, diagnostic, warn

# The instruction block is IDENTICAL on every call and is sent as a
# cached prefix, charged at 10% of the input rate. That is where most
# of the saving comes from -- see core/ai_budget.py.
SYSTEM = """You read one piece of Indian stock-market news and say what \
it means for ONE named company on the NSE.

Answer with JSON only, no other text:
{"direction": "...", "confidence": 0.0, "reason": "..."}

direction must be exactly one of:
  POSITIVE   likely to push this company's share price UP
  NEGATIVE   likely to push it DOWN
  NEUTRAL    genuinely affects this company, but not clearly either way
  UNRELATED  this story is not about this company at all

confidence is 0.0 to 1.0 -- your honest confidence in the direction.
reason is ONE short sentence naming the MECHANISM, under 120 \
characters. Not a restatement of the headline.

Rules that matter:
- UNRELATED is common and correct. These companies were matched to \
this story by keyword, and keywords are often wrong. A story about the \
rupee is not about a company merely because the word "dollar" appears. \
Say UNRELATED rather than inventing a link.
- Judge the effect on the SHARE PRICE, not whether the news is nice. \
A large order win at thin margins can still be POSITIVE for the price.
- An order WON is positive for the winner. The customer placing it is \
usually UNRELATED or NEUTRAL, not positive.
- Results already carry their own grade elsewhere; if this is just a \
results announcement with no numbers, NEUTRAL is honest.
- Do not speculate beyond what the text says. Low confidence is an \
acceptable answer; a confident guess is not."""

USER = """Company: {symbol}{business}

News ({kind}, {when}):
{headline}"""

_JSON = re.compile(r"\{.*\}", re.S)


def _text(value):
    """A cell from the master file, as clean text. "" for anything empty.

    An EMPTY CELL IS NOT AN EMPTY STRING. core/master_loader.py reads
    master_stocks.csv with pandas, which turns a blank into float NaN
    -- and NaN is TRUTHY, so the obvious

        (row.get("INDUSTRY") or "").strip()

    sails past the `or`, calls .strip() on a float and raises. That is
    exactly how the first regrade died, on the first stock whose
    INDUSTRY column happened to be blank.

    The tests missed it because the fake loader in tests/test_ai_news.py
    returns tidy strings. A fixture cleaner than the real data is a
    fixture that cannot find this class of bug.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        # NaN is the only float that is not equal to itself.
        if value != value:
            return ""
        return str(value).strip()
    return str(value).strip()


class AiNewsGrader:
    """Asks the cheap model for a direction on one event at a time.

    ONE EVENT PER CALL, deliberately. Batching several stories into one
    request would shave a little off the bill and would make every
    answer harder to attribute, harder to re-run, and harder to check
    later against what the stock did. At Rs 53 a month the saving is
    not worth losing the audit trail.
    """

    def __init__(self, budget=None, client=None, model=None,
                 master_loader=None):
        from config import AI_MODEL_CHEAP
        self.model = model or AI_MODEL_CHEAP
        self.master_loader = master_loader
        self._client = client
        self._client_tried = client is not None
        self._lock = threading.Lock()
        if budget is None:
            from core.ai_budget import AiBudget
            budget = AiBudget()
        self.budget = budget
        self.calls = 0
        self.refused = 0

    # ------------------------------------------------------------
    def _get_client(self):
        """None means "run without AI", never a crash.

        Every caller treats None as "leave the event ungraded", which
        is exactly how the bot behaved before tonight.
        """
        with self._lock:
            if self._client_tried:
                return self._client
            self._client_tried = True
            # ---- THE MASTER SWITCH. 10 August 2026. ----
            # tools/collector.py now refuses to BUILD this grader while
            # AI_ENABLED is False. This is the second lock, on the
            # module itself, so a future caller cannot spend money by
            # forgetting to ask.
            try:
                from config import AI_ENABLED
            except Exception:                              # noqa: BLE001
                AI_ENABLED = False
            if not AI_ENABLED:
                warn("[AI NEWS] OFF -- config.AI_ENABLED is False. The "
                     "cards already carry EXCELLENT / GREAT / GOOD; the "
                     "bot reads that text directly and pays nothing.")
                return None
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                warn("[AI NEWS] No ANTHROPIC_API_KEY -- events keep their "
                     "kind and stay without a direction, exactly as before.")
                return None
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=key, timeout=30)
            except ImportError:
                warn("[AI NEWS] The 'anthropic' package is not installed. "
                     "Run:  pip install anthropic")
            except Exception as exc:                       # noqa: BLE001
                warn(f"[AI NEWS] Could not start the client: {exc}")
            return self._client

    def _business(self, symbol):
        """Who this company actually is. Sent with every story.

        ---- THE FIRST BACKFILL PROVED WHY, 31 July 2026 ----

        The first version of this method looked for methods named
        description_for / industry_for / name_for. MasterLoader has
        none of them. It returned "" every time, silently, and 142
        events were graded from a BARE TICKER.

        The model did remarkably well on that -- it correctly rejected
        DOLLAR for a rupee story, NMDC for a GMDC story, and STAR for a
        Strides Pharma story. But it also produced this:

            PPLPHARMA  UNRELATED
            "News is about Piramal Pharma's Q1 FY27 performance;
             PPLPHARMA is a different company."

        PPLPHARMA *IS* Piramal Pharma. And two rows later the same
        model graded two other Piramal stories as NEUTRAL, so it was
        not confused about the company -- it was confused about the
        TICKER, which is the one thing it had no way to look up.

        The master file has known the answer all along:

            COMPANY NAME   PIRAMAL PHARMA LIMITED
            INDUSTRY       PHARMA CDMO / CONTRACT MANUFACTURING
            CORE BUSINESS  MANUFACTURES PHARMACEUTICALS AND CDMO...

        Starving a reader of the one fact that settles the question and
        then judging its answer is not a fair test of the reader.

        Fails silent. An unknown symbol sends just the ticker, which is
        how it behaved before -- degraded, not broken.
        """
        if self.master_loader is None:
            return ""
        try:
            row = self.master_loader.get_by_symbol(symbol) or {}
        except Exception:                                  # noqa: BLE001
            return ""
        bits = [_text(row.get(field)) for field in
                ("COMPANY NAME", "INDUSTRY", "CORE BUSINESS")]
        bits = [b for b in bits if b]
        if not bits:
            return ""
        return " (" + " | ".join(b[:80] for b in bits[:3]) + ")"

    # ------------------------------------------------------------
    def grade(self, event):
        """One event -> {direction, confidence, reason} or None.

        None means "no verdict", for any reason: no key, no budget, a
        network failure, an unparseable reply. The caller leaves the
        event as it was. Nothing downstream is allowed to treat a
        missing verdict as NEUTRAL -- an absent opinion and a neutral
        opinion are different facts.
        """
        symbol = str(event.get("symbol") or "").strip()
        headline = str(event.get("headline") or "").strip()
        if not symbol or not headline:
            return None

        client = self._get_client()
        if client is None:
            return None

        allowed, why = self.budget.may_call()
        if not allowed:
            self.refused += 1
            if self.refused == 1:              # once, not once per event
                warn(f"[AI NEWS] Not calling: {why}. Events will keep their "
                     f"kind and no direction until this clears.")
            return None

        prompt = USER.format(
            symbol=symbol, business=self._business(symbol),
            kind=event.get("kind") or "NEWS",
            when=str(event.get("at") or "")[:16],
            headline=headline[:600])

        try:
            reply = client.messages.create(
                model=self.model, max_tokens=200,
                system=[{"type": "text", "text": SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}])
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[AI NEWS] {symbol}: call failed ({exc})")
            return None

        usage = getattr(reply, "usage", None)
        if usage is not None:
            self.budget.record(
                self.model, purpose="news_direction",
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_read_tokens=getattr(
                    usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(
                    usage, "cache_creation_input_tokens", 0) or 0)
        self.calls += 1

        text = "".join(getattr(b, "text", "") for b in reply.content)
        return self._parse(text, symbol)

    @staticmethod
    def _parse(text, symbol):
        """A reply we cannot read is NO verdict, never a default one."""
        from core.stock_events import VERDICTS
        match = _JSON.search(text or "")
        if not match:
            diagnostic(f"[AI NEWS] {symbol}: no JSON in reply {text[:120]!r}")
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            diagnostic(f"[AI NEWS] {symbol}: bad JSON {text[:120]!r}")
            return None

        direction = str(data.get("direction") or "").strip().upper()
        if direction not in VERDICTS:
            # A direction we did not offer is a misread, not a new
            # category. Dropping it is safer than mapping it to
            # something plausible.
            diagnostic(f"[AI NEWS] {symbol}: unusable direction "
                       f"{direction!r}")
            return None

        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))

        return {"direction": direction, "confidence": confidence,
                "reason": str(data.get("reason") or "").strip()[:300] or None,
                "model": None}

    # ------------------------------------------------------------
    def grade_pending(self, events_store, limit=200, hours=None, log=False):
        """Grade everything waiting, and store each verdict as it lands.

        Written one at a time on purpose. A backfill that only saves at
        the end loses everything to one network blip, and the operator
        pays for the tokens twice.
        """
        pending = events_store.needing_a_verdict(limit=limit, hours=hours)
        done = 0
        for event in pending:
            verdict = self.grade(event)
            if verdict is None:
                if self.refused:      # budget or key -- no point continuing
                    break
                continue
            if events_store.record_verdict(
                    event["id"], verdict["direction"],
                    confidence=verdict["confidence"],
                    reason=verdict["reason"], model=self.model):
                done += 1
                if log:
                    arrow = {"POSITIVE": "+", "NEGATIVE": "-",
                             "NEUTRAL": "=", "UNRELATED": "x"}
                    decision(
                        f"  {arrow.get(verdict['direction'], '?')} "
                        f"{event['symbol']:12} "
                        f"{(verdict['reason'] or '')[:70]}")
        return {"pending": len(pending), "graded": done,
                "calls": self.calls, "spent": self.budget.status()}
