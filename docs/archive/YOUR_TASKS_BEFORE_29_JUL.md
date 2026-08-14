# YOUR TASKS -- before tomorrow's open

Everything I built tonight is verified: **968 tests pass**, every Python
file parses, dashboard JavaScript checks clean.

Four things need your hands. Two are essential, two are optional.

---

## 1. DELETE THE PAUSE FLAG  -- essential

```
D:\Opportunity Trader\data\entries_paused.flag
```

Presence of this file = new entries are PAUSED. It is read once at
startup, so if it is there at 09:15 the bot comes up refusing every
entry, silently.

It exists because MY test run wrote it at 11:36 today. That is fixed --
tests are now sandboxed and a full 968-test run leaves it untouched --
but I cannot delete the file from my side.

**One file. If it is still there tomorrow, the clean session is wasted
before the first tick.**

---

## 2. START ONCE, BEFORE 09:15  -- essential

```
py main.py
```

Everything below is already on disk. It needs one restart to load, and
that restart must happen BEFORE the market opens.

Watch the startup lines for these four. If any is missing, tell me
before 09:15 rather than restarting:

```
[MTF] Margin sizing active -- asking Dhan per stock, Rs 1,00,000 ...
[RESULTS_GATE] Live -- a reporting stock is blocked until its numbers
               land, then allowed only if they are STRONG or GOOD.
[LEARN] Reason capture live -- every trade now records WHY it was taken.
[LEARN] trade_memory: added column ...   (x6, first run only)
```

**Then hands off until 15:30.** If something looks wrong, write it down
and send it. A broken panel costs one feature; a restart inside
09:15-09:30 cost 607 of 666 symbols today and made the whole session
unmeasurable.

---

## 3. BACKFILL THE OLD TRADES  -- optional, 2 minutes

```
py tools/backfill_reasons.py            # dry run, writes nothing
py tools/backfill_reasons.py --apply    # writes it
py tools/reason_review.py               # the nightly report
```

My sandbox cannot open the live trade_memory.db, so I proved both
against a copy. On that copy: **5 of your 40 trades had a reason known
before entry. 35 did not.**

Do this whenever convenient -- it only adds history, it changes nothing
about how the bot runs.

---

## 4. ASK DHAN ONE QUESTION  -- optional, but useful before Monday

**Is a same-day MTF exit charged INTRADAY STT (0.025%) or DELIVERY STT
(0.1% both sides)?**

Public sources contradict each other and I could not settle it. Until
then the bot uses intraday rates for same-day trades, which is what you
instructed. Thursday's live order test answers it from the contract
note if you would rather not ask.

---

## 5. THURSDAY 30 JULY -- the first real order

```
py tools/live_order_test.py --symbol COFORGE
```

Five steps, each one asks before it runs:

```
1  LIMIT order 10% below market   proves it can PLACE   costs nothing
2  cancel it                      proves it can CANCEL  costs nothing
3  MARKET order, 1 share, MTF     proves it can FILL    ~Rs 1,700
4  read the contract note         settles the STT question
5  sell it back                   proves it can CLOSE
```

Steps 1 and 2 cost NOTHING -- a limit order parked 10% below the market
cannot fill on a liquid stock, so the whole order path is proven (auth,
security id, MTF product, correlation id, response shape) before a rupee
is spent. Only step 3 buys anything, and it buys ONE share.

It will not run until BOTH switches are set in config.py:

```
TRADING_MODE = "LIVE"
I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True
```

**Step 4 is the one that matters beyond the plumbing.** Read the STT
line on the contract note. Public sources contradict each other on
whether a same-day MTF exit is charged intraday (0.025%) or delivery
(0.1% BOTH sides) STT. Nobody here has seen a real one, and the entire
cost model rests on it.

---

# WHAT CHANGED TONIGHT

```
 1  Fresh Breakouts panel      breakouts with clock time, attempt no.,
                               tests of the level, and WHY one was refused
 2  Dead click fixed           all 5 panels; BUY/SELL/SHORT can no longer
                               be eaten by the 1-second refresh
    Action log panel           every click, sent or failed, stays on screen
 3  Test isolation             a test run no longer touches the live log,
                               the live trade log, or the pause flag
 4  Per-symbol staleness       each stock judged on its own rhythm;
                               reconciled ORB ranges now UNBLOCK the symbol
 5  15:15 square-off OFF       positions carry overnight, itemised report
                               instead of forced liquidation
 6  Charges corrected          intraday by default (your correction);
                               delivery STT + interest + pledge only on
                               genuine overnight holds
 7  Slippage modelled          paper fills are no longer perfect
 8  MTF sizing                 Rs 1,00,000 of margin per position, share
                               count from Dhan's own margin calculator
 9  Peak trailing stop         2.5% below the highest price; moves only on
                               a new high, never on a pause; reaches
                               breakeven by itself at about +2.6%
10  Results gate rewritten     blocks BEFORE the numbers, allows AFTER
                               STRONG or GOOD ones
11  Reason columns             every trade now records WHY it was taken
12  Backfill + nightly review  tools/backfill_reasons.py, reason_review.py
13  LIVE EXECUTION             the module that did not exist. Market
                               orders on MTF, drift guard before send,
                               never a blind retry after a timeout,
                               hard ceilings, two switches, kill switch
14  First-order test script    tools/live_order_test.py -- the 30 July
                               five-step sequence
```

---

# WHAT IS STILL OPEN

Nothing blocking tomorrow. For the days after:

- 61-session sweep of the 2.5% trail (weekend)
- Purge X / NEW / OLD test symbols from the live path
- Log rotation -- the file is 369 MB
- Verify every SECURITY ID against Dhan's scrip master
- Drop JBCHEPHARM (subscribed, zero ticks, not on NSE's list)
- Survivorship bias in daily_candles.db
- 5 of 8 Market Intelligence tiles are dead placeholders

---

# THE ONE RULE FOR TOMORROW

```
ONE start, before 09:15.
ZERO restarts, whatever happens.
```

One unbroken session is the thing this project has never had. It is
worth more than any single fix on the list -- without it, every number
in the log is unreadable, which is exactly why three of my own findings
today turned out to be wrong.
