"""
==========================================================
Is the AI layer actually wired up?
==========================================================
    py tools/ai_check.py

Costs about Rs 0.003 -- a third of a paisa. Measured, not guessed: the
first real run charged 14 input and 4 output tokens, which at $1 and
$5 per million and Rs 88 to the dollar is Rs 0.00299. (The first
version of this line said Rs 0.0002, which was fifteen times low. A
number in a docstring is a claim like any other.)

Places no orders, changes no positions, writes nothing except one row
in the spend ledger.

WHY IT EXISTS
-------------
31 July 2026. The key was created, credits were bought, and the
question "is it working?" had no cheap answer. The same shape as the
DH-905 morning: three rejected orders and hours of guessing, because
nothing could ask "what does the other side actually see?" without
doing the expensive thing first.

So this asks, in order, and stops at the first thing that is wrong:

    1. is the key even in .env, and does it LOOK like a key
    2. is the SDK installed
    3. does the budget meter allow a call
    4. does the API answer, and what does it charge

Each failure prints what to do about it rather than a stack trace.
The key itself is NEVER printed -- only its length and prefix, which
is enough to spot a truncated paste or a stray quote mark and not
enough to be worth anything to anyone reading over a shoulder.

Author : H&M Opportunity Trader
==========================================================
"""

import sys

sys.path.insert(0, ".")

from config import (                                       # noqa: E402
    ANTHROPIC_API_KEY, AI_MODEL_CHEAP, AI_MONTHLY_BUDGET_RS,
)
from core.logger import decision, warn                     # noqa: E402


def _line():
    decision("-" * 66)


def main():
    decision("=" * 66)
    decision("  AI CHECK -- one tiny call, about Rs 0.0002")
    decision("=" * 66)

    # ---- 1. the key ------------------------------------------------
    _line()
    decision("  1. THE KEY IN .env")
    key = ANTHROPIC_API_KEY or ""
    if not key:
        warn("     MISSING. config.ANTHROPIC_API_KEY is empty.")
        warn("")
        warn("     Add ONE line to D:\\Opportunity Trader\\.env :")
        warn("         ANTHROPIC_API_KEY=sk-ant-...")
        warn("     No quotes, no spaces around the = sign.")
        return 1
    decision(f"     present, {len(key)} characters, "
             f"starts {'sk-ant-' if key.startswith('sk-ant-') else key[:7]!r}")
    problems = []
    if not key.startswith("sk-ant-"):
        problems.append("it does not start with sk-ant-")
    if key != key.strip():
        problems.append("it has a leading or trailing space")
    if key.startswith(('"', "'")) or key.endswith(('"', "'")):
        problems.append("it is wrapped in quote marks -- .env needs none")
    if len(key) < 80:
        problems.append(f"it is only {len(key)} characters, which looks "
                        f"truncated")
    if problems:
        for p in problems:
            warn(f"     PROBLEM: {p}")
        warn("     Fix .env and run this again.")
        return 1
    decision("     looks right.")

    # ---- 2. the SDK ------------------------------------------------
    _line()
    decision("  2. THE PYTHON PACKAGE")
    try:
        import anthropic
    except ImportError:
        warn("     NOT INSTALLED.")
        warn("")
        warn("     Run this once, in Terminal 2:")
        warn("         pip install anthropic")
        return 1
    decision(f"     anthropic {getattr(anthropic, '__version__', '?')}")

    # ---- 3. the budget ---------------------------------------------
    _line()
    decision("  3. THE SPEND CAP")
    from core.ai_budget import AiBudget
    meter = AiBudget()
    decision(f"     {meter.report()}")
    allowed, why = meter.may_call()
    if not allowed:
        warn(f"     REFUSED: {why}.")
        warn(f"     Nothing will be called until the cap resets or "
             f"config.AI_MONTHLY_BUDGET_RS (Rs {AI_MONTHLY_BUDGET_RS:,.0f}) "
             f"is raised.")
        return 1
    decision("     a call is allowed.")

    # ---- 4. the call -----------------------------------------------
    _line()
    decision(f"  4. DOES {AI_MODEL_CHEAP} ANSWER?")
    try:
        client = anthropic.Anthropic(api_key=key, timeout=30)
        reply = client.messages.create(
            model=AI_MODEL_CHEAP, max_tokens=16,
            messages=[{"role": "user",
                       "content": "Reply with the single word: ready"}])
        text = "".join(getattr(b, "text", "") for b in reply.content).strip()
        usage = reply.usage
    except anthropic.AuthenticationError as exc:
        warn("     THE KEY WAS REJECTED.")
        warn("     Either it was copied wrong, or it belongs to a DIFFERENT")
        warn("     organisation from the one holding your credits. Check the")
        warn("     org switcher at the top-left of the Console -- the key and")
        warn("     the money must be in the same one.")
        warn(f"     {str(exc)[:200]}")
        return 1
    except anthropic.APIStatusError as exc:
        warn(f"     THE API REFUSED (HTTP {exc.status_code}).")
        if exc.status_code == 400 and "credit" in str(exc).lower():
            warn("     That is the 'credit balance too low' answer -- the")
            warn("     credits are not on this key's organisation.")
        warn(f"     {str(exc)[:300]}")
        return 1
    except Exception as exc:                               # noqa: BLE001
        warn(f"     COULD NOT REACH THE API: {type(exc).__name__}")
        warn(f"     {str(exc)[:200]}")
        warn("     Check the internet connection. Note this call goes out")
        warn("     over the HOME line, NOT the static-IP proxy -- that one is")
        warn("     only ever used for Dhan orders (see core/order_route.py).")
        return 1

    decision(f"     reply   : {text!r}")
    decision(f"     tokens  : in={usage.input_tokens} out={usage.output_tokens}")
    spent = meter.record(AI_MODEL_CHEAP, purpose="ai_check",
                         input_tokens=usage.input_tokens,
                         output_tokens=usage.output_tokens)
    decision(f"     cost    : Rs {spent:.5f}")

    _line()
    decision("  ALL FOUR PASS. The key works, the credits are live, and")
    decision("  the meter recorded the call.")
    decision("")
    decision(f"  {meter.report()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
