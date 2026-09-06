"""ONE question, asked in ONE place: may a REAL order be placed?

---- TWO STATES, NOT THREE. 4 September 2026. ----

    "separate the REAL & PAPER modes completely so that user can check
     more no of tests & sample data, trades without checking. as of
     now IP is not renewed & dhan can't be reached but ON & OFF needs
     to be taken care."                            -- the operator

    "ON = REAL TRADES . OFF = PAPER TRADES"        -- his standing rule

WHAT WAS WRONG. The answer to "is this order real?" was spread across
three things that never checked each other:

    config.TRADING_MODE     "PAPER" / "LIVE", read once at startup
    execution.live          the switch, flipped at runtime
    core.broker_funds       whether Dhan actually answered

The desk's switch says "ON -- real / OFF -- paper", but ON in a PAPER
process only ever meant "place PAPER orders". The label was telling
him one thing and the code was doing another, and nothing anywhere
compared the three.

THE RULE, whole:

    A real order needs the switch ON *and* a broker that answered.
    Everything else is paper. There is no third state.

WHY THE BROKER CHECK IS PART OF THE GATE, not a separate warning: on
4 September his static IP was not renewed and Dhan could not be
reached at all. Arming ON in that state would have placed "real"
orders at a broker the process cannot talk to -- silently failing, or
worse, sizing on a margin figure cached from a previous session. The
gate refuses to arm and says why.

WHY PAPER MUST NOT TOUCH DHAN AT ALL. He wants to run tests, sample
data and trades freely while the IP is down. Paper therefore asks the
broker NOTHING: not the purse (config.PAPER_STARTING_CAPITAL, a fixed
Rs 5 lakh), not the margin (core.mtf_margin falls back to
MTF_FALLBACK_MARGIN_PCT = 1.0, so a paper trade with no MTF reading
buys only what the allotted capital covers). No token, no network, no
wait, nothing for an unreachable broker to break.

FAILS CLOSED. Every uncertain case returns PAPER. An engine that
cannot be read, a mode that cannot be parsed, a broker whose state is
unknown -- all paper. The expensive mistake is a real order nobody
meant; a paper order costs a line in a log.
"""

from core.logger import warn

# How recently Dhan must have answered for ON to count as armed. A
# funds read is taken at startup and on every heartbeat (60s), so two
# missed heartbeats means something is wrong.
BROKER_FRESH_SECONDS = 180.0


def _mode():
    """The process mode, or None when it cannot be read."""
    try:
        from config import TRADING_MODE
        return str(TRADING_MODE).upper()
    except Exception:                                      # noqa: BLE001
        return None


def broker_is_reachable(max_age_seconds=BROKER_FRESH_SECONDS):
    """Did Dhan answer recently enough to trade against?

    Reads core.broker_funds' own record of its last successful call --
    it does NOT make a call, so this is free and cannot block a tick.

    Returns (True|False, why). Unknown is False: a broker whose state
    cannot be established is not one to send money through.
    """
    try:
        from datetime import datetime

        from core import broker_funds
        last = broker_funds.last_read() or {}
    except Exception as exc:                               # noqa: BLE001
        return False, f"cannot read the broker's state ({exc})"

    if (last.get("source") or "").lower() != "dhan":
        return False, ("no reading has come from Dhan this session -- "
                       "the last figure came from "
                       f"{last.get('source') or 'nowhere'}")
    at = last.get("at")
    if not at:
        return False, "the last reading carries no time, so it cannot be aged"
    try:
        when = at if hasattr(at, "timestamp") else datetime.fromisoformat(
            str(at).replace("T", " ")[:19])
        age = (datetime.now() - when).total_seconds()
    except (TypeError, ValueError) as exc:
        return False, f"the reading's time is unreadable ({exc})"
    if age > max_age_seconds:
        return False, (f"Dhan last answered {age / 60:.0f} minutes ago "
                       f"-- stale past {max_age_seconds / 60:.0f}")
    return True, f"Dhan answered {age:.0f}s ago"


def may_place_real_orders(engine):
    """THE gate. (True|False, why) -- and False means PAPER, not idle.

    Both must hold:
        the switch is ON        execution.live is True
        the broker answered     recently, per broker_is_reachable()

    The process mode is honoured as an outer bound: a process started
    in PAPER never places a real order however the switch is set, so a
    paper session cannot be turned real by a click.
    """
    # THE SWITCH IS THE WHOLE ANSWER. TRADING_MODE no longer gates a
    # real order -- see trading/execution._live_executor(). What used
    # to be an outer bound is now a refusal at the switch, with a
    # reason he can read: refuse_to_arm_reason() below will not let ON
    # happen while the broker is unreachable.

    # ---- IT WAS READING THE WRONG FLAG. 5 September 2026. ----
    #
    # This asked engine.alert_only, which is what the switch USED to
    # mean. By the time anything called this function, that flag was
    # permanently False -- so it reported "the switch is ON" whether it
    # was on or off. Only the MESSAGE was ever wrong, never the
    # routing, because trading/execution._route() reads execution.live
    # and always has. Corrected with the collapse to two.
    execution = getattr(engine, "execution", None) if engine else None
    live = getattr(execution, "live", None) if execution is not None else None
    if live is None:
        return False, "the engine did not say whether the switch is on"
    if not live:
        return False, "the switch is OFF -- paper"

    ok, why = broker_is_reachable()
    if not ok:
        return False, f"the switch is ON but {why} -- paper until it answers"
    return True, f"the switch is ON and {why}"


def apply_switch(engine, on):
    """Move THE switch. The desk and the phone both come through here.

    ---- THE SAME 'OFF' MEANT TWO THINGS. 4 September 2026. ----

        "i didn't understand why so much complex is in this switch
         ON / OFF .?"
        "i told you my requirements too, how each switch works right"
                                              -- the operator

    He is right, and the audit found it. Until this function existed:

        dashboard OFF -> alert_only = False, execution.live = False
                         the bot still trades, on paper.  HIS RULE.

        Telegram  OFF -> RAISED the alert-only flag and left
                         execution.live untouched: the bot stopped
                         trading entirely and only alerted.  THE THIRD
                         STATE he abolished on 31 August after 65
                         alerts and 0 trades.

    (Written out in words rather than as code, because
    tests/test_the_guard_stops_a_dead_feed.py greps the live tree for
    that assignment and a docstring quoting it reads exactly like the
    bug. A guard that fires on its own explanation is a guard that
    gets switched off.)

    and Telegram ON set alert_only = False without touching
    execution.live, so it did not turn real trading on either -- it
    just unfroze the bot. One flag, two opposite meanings, depending
    on which screen he happened to press.

    So there is one function, and both callers use it. The dashboard
    keeps its own extra work around this -- the readiness check, the
    purse -- but the thing that decides WHOSE MONEY is decided here
    and nowhere else.

    Returns (ok, message). A refusal is a sentence, never silence.
    """
    if on:
        refusal = refuse_to_arm_reason(engine)
        if refusal:
            return False, f"Refusing to arm: {refusal}"

    execution = getattr(engine, "execution", None)
    if execution is None:
        return False, "no execution path in this session"

    # THE ONE ASSIGNMENT. alert_only and breakout_armed were retired on
    # 5 September: the bot always trades, and the breakout path always
    # alerts and never buys. There is nothing else to set.
    execution.live = bool(on)

    if not on:
        return True, "OFF -- every order is paper."
    ok, why = may_place_real_orders(engine)
    if ok:
        return True, "ON -- real orders. " + why
    return True, ("ON -- but " + why)


def refuse_to_arm_reason(engine):
    """Why the switch must not go ON right now, or None if it may.

    Called by the dashboard BEFORE flipping the switch, so a refusal
    reaches him as a sentence instead of as orders that quietly go
    nowhere.

    The switch may always be turned OFF -- that direction is never
    refused, and is not this function's business.
    """
    # Asked ALWAYS now, not only in a LIVE process. This is the check
    # that replaced the mode outer bound: ON means real money, so ON
    # must not be possible while Dhan is not answering -- which is the
    # state he was in on 4 September when the IP was not renewed.
    ok, why = broker_is_reachable()
    if not ok:
        warn(f"[GATE] Refusing to arm: {why}. Orders would go to a broker "
             f"this process cannot talk to.")
        return why
    return None
