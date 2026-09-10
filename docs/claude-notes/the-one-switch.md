---
name: the-one-switch
description: "ON = REAL trades, OFF = PAPER trades, no third state — but as of 10 Sep 2026 the switch only routes the order; TRADING_MODE still decides the purse, the broker stop and the loss cap"
metadata: 
  node_type: memory
  originSessionId: 16056bf4-7288-47a5-b025-94575658f3a9
  modified: 2026-09-10T10:33:28.594Z
---

The board's ON/OFF control has exactly two meanings and no third state:

    OFF  = PAPER trades   (the default, every restart)
    ON   = REAL trades

Everything else must be IDENTICAL between them: same entries, same
exits, same capital, same sizing, same gates. The only difference is
whose money. The dashboard shows the two words and nothing else -- no
confirmation dialog, no explanation text, no extra labels.

**Why:** he specified this on 5 August and it was not built that way.
What shipped instead was ALERT_ONLY (OFF = place nothing at all, not
even a simulated fill) with PAPER/LIVE as a separate config value. That
third "watch only" state is what left the bot producing notifications
and no record for ten days -- 65 alerts and 0 trades on 31 August. He
had to ask again on 31 August: "thought u did as i told until today.
so, pls make sure atleast now." And again on 6 September: *"its not
correct. as we settled that switch . OFF = paper & ON = Real trades
thats it & final"* and *"by default OFF . after clicking ON then it
must trade in real mode & do not ask user to change in files or
restarts in run"*.

**How to apply:** never re-introduce a watch-only state. The bot always
trades; the switch only decides real or paper. A day with no qualifying
event and therefore no trade is a correct day -- "just music day (no
trade until 15:30)" -- and must not be treated as the bot being idle or
broken.

## FIXED 10 September 2026 -- commit "The switch decides the slot, the loss cap, the broker stop and the reconcile"

TRADING_MODE no longer decides real vs paper anywhere at runtime. Two
authorities: NEW orders read the switch (`engine._switch_is_live`:
execution.live and a built live executor) -> slot size
(`capital.own_cash_per_position`: 15k live / 50k paper) and the daily loss
cap. EXISTING positions read who opened them (`execution._who_opened`) ->
broker stop placement (`BrokerStop(is_live_position=...)`, fails closed)
and reconciliation (`BrokerSync._opened_live`). Startup-only reads in
main.py:753 and morning_ready.py:272 were left: the switch is always OFF
at startup, so they agree. Full suite 5,961 passed; 8 old-contract tests
rewritten; 4 failures are stale data files, not this.

The section below is the fault as found, kept for the history.

## (was) STILL BROKEN as of 10 September 2026 -- the top fix

The 6 Sep change made `trading/execution._live_executor()` return
`getattr(self, "_live", None)` with no mode check, so ROUTING follows
the switch. **That change was never followed through to anything
else.** `TRADING_MODE = "PAPER"` (config.py:132) still decides:

    core/capital.py:141        the purse -- Rs 5,00,000 paper vs Dhan's balance
    core/engine.py:665         whether the GTT broker stop is armed
    core/engine.py:424-427     whether the daily loss cap applies
    core/broker_funds.py       whether Dhan is asked for funds at all
    core/broker_sync.py:320,359  position reconciliation against the broker
    core/morning_ready.py:272  the readiness check
    main.py:753                capital from Dhan vs from the saved file

And `trading/execution.py:112` builds `self._live` regardless of mode,
gated only on `I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True` and a Dhan
client being present -- both true.

**So clicking ON in a PAPER-banner session sends real orders to Dhan,
sized against the fake Rs 5,00,000 paper purse** (10 seats x Rs 50,000
margin, positions running Rs 1.2-2.1 lakh each on MTF) against his real
Rs 1,00,000 account, **with the GTT backstop switched off**. He was
right on 6 Sep that a real buy's stop should rest at Dhan; in this
state it does not.

Fix this before anything else in [[bot-review-7-to-10-sep-2026]].

Related: [[opportunity-trader-architecture]], [[operator-work-style]],
[[verify-the-value-the-live-path-reads]].
