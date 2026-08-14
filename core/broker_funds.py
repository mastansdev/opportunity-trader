"""
==========================================================
How much money is actually there
==========================================================

    "BY CHANGING CONFIG TRADING_MODE everything must follow.
     PAPER = OUR OWN PAPER TRADING
     LIVE  = CONNECT TO DHAN FOR TRADING. SHOW LIVE MODE. FUNDS
             AVAILABLE IN DHAN & EVERYTHING LINKED"
                                    -- operator, 31 July 2026

WHY THIS EXISTS
---------------
Portfolio started with config.PAPER_STARTING_CAPITAL -- Rs 10,00,000 --
in BOTH modes. On the first live morning the dashboard showed ten lakh
of capital against a Dhan account holding a few hundred rupees.

That is not a display problem. Portfolio.available_capital gates
sizing, and a book that believes it has ten lakh will approve
positions the account cannot pay for. The broker rejects them, one at
a time, in the middle of the session, and every rejection looks like a
different bug.

THE RULE
--------
    PAPER -> the simulated purse from config. No network, no broker.
    LIVE  -> whatever Dhan says is available. Nothing else is allowed.

REFUSING IS THE CORRECT ANSWER
------------------------------
If the funds call fails in LIVE this RAISES. It does not fall back to
the paper figure, and that is deliberate -- the same reasoning as
trading/execution.py refusing to start LIVE without a client. A number
invented by config and a number reported by the broker look identical
on a screen, and the whole point of LIVE is that the screen is telling
the truth.

An expired token is the usual cause and it is fixed in two minutes in
the Dhan app. Discovering it at 09:00 costs nothing. Discovering it at
11:00, through a rejected order, costs the trade.

DHAN'S FIELD NAME IS MISSPELLED
-------------------------------
The API returns "availabelBalance" -- their typo, not ours. Both
spellings are read, because a silent None here would trigger the
refusal above for the wrong reason.

Author : H&M Opportunity Trader
==========================================================
"""

from config import PAPER_STARTING_CAPITAL, TRADING_MODE
from core.logger import decision, warn

# In Dhan's order of preference. availabelBalance is what the live API
# actually returns today; the correctly-spelled key is read too in case
# they ever fix it, and sodLimit last as the start-of-day figure.
BALANCE_KEYS = ("availabelBalance", "availableBalance", "sodLimit")


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def read_balance(dhan_client):
    """The broker's available balance, or None if it could not be read.

    Returns None rather than 0.0 on failure. Zero is a real, meaningful
    answer -- an account with no money in it -- and must not be
    confused with "the question was never answered".
    """
    if dhan_client is None:
        return None
    try:
        response = dhan_client.get_fund_limits()
    except Exception as exc:                               # noqa: BLE001
        warn(f"[FUNDS] Could not read the balance from Dhan: {exc}")
        return None
    envelope = response or {}
    body = envelope.get("data") or envelope or {}
    if not isinstance(body, dict):
        warn(f"[FUNDS] Dhan replied in an unexpected shape: {str(body)[:120]}")
        return None
    for key in BALANCE_KEYS:
        if key in body:
            value = _num(body[key])
            if value is not None:
                return value

    # ---- DHAN TOLD US WHY AND WE THREW IT AWAY. 3 August 2026. ----
    #
    #     WARNING: [FUNDS] No balance field in Dhan's reply.
    #              Keys: ['data', 'remarks', 'status']
    #
    # Those keys are Dhan's OUTER envelope, which means `data` came back
    # empty and `body` fell through to the envelope itself. An empty
    # `data` is not a missing field -- it is a REFUSED REQUEST, and the
    # reason is sitting in `remarks` and `status` right next to it.
    #
    # The old message sent him hunting for a parsing bug in a reply that
    # had no balance in it because the call never succeeded. On the
    # morning of a live session that is the wrong half-hour to lose.
    if isinstance(envelope, dict) and (
            "remarks" in envelope or "status" in envelope):
        status = envelope.get("status")
        remarks = envelope.get("remarks")
        warn(f"[FUNDS] Dhan REFUSED the balance request. "
             f"status={status!r} remarks={str(remarks)[:200]!r}")
        warn("[FUNDS] An empty 'data' beside a status is almost always the "
             "access token -- Dhan's lasts 24 HOURS. Generate a new one "
             "on Dhan's site, paste it into .env after "
             "DHAN_ACCESS_TOKEN=, then check with "
             "py tools/dhan_account_check.py")
    else:
        warn(f"[FUNDS] No balance field in Dhan's reply. Keys: "
             f"{sorted(body.keys())[:12]}")
    return None


def starting_capital(dhan_client=None, mode=None):
    """What Portfolio should open the day with.

    PAPER returns the config figure and never touches the network.
    LIVE returns the broker's balance and raises if it cannot get one.
    """
    live = str(mode if mode is not None else TRADING_MODE).upper() == "LIVE"

    if not live:
        decision(f"[FUNDS] PAPER -- simulated purse of "
                 f"Rs {PAPER_STARTING_CAPITAL:,.2f}. No broker involved.")
        return float(PAPER_STARTING_CAPITAL)

    balance = read_balance(dhan_client)
    if balance is None:
        raise RuntimeError(
            "TRADING_MODE is LIVE but Dhan's available balance could not "
            "be read. Refusing to start on config.PAPER_STARTING_CAPITAL "
            "-- a live book sized against imaginary money approves "
            "positions the account cannot pay for, and every rejection "
            "then looks like a different bug. Check the token with: "
            "py tools/dhan_account_check.py"
        )

    decision(f"[FUNDS] LIVE -- Rs {balance:,.2f} available at Dhan. "
             f"This, not config, is the book's capital today.")
    if balance <= 0:
        warn("[FUNDS] The available balance is zero. Every order will be "
             "rejected for insufficient funds. Add money before trading.")
    return float(balance)
