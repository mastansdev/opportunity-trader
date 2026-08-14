# Friday 31 July, AFTER the close — rebuild the universe

**Operator's instruction, 29 July 2026:**

> "we will clean = the rebuild the universe after friday market closes.
>  pls note and remember me."

This file exists so that instruction survives. **Do not run this before
Friday's close.** Nothing about it is urgent enough to risk a live
session, and it changes what the bot is allowed to buy.

---

## Why it is waiting

On 29 July both price bounds were removed:

| | was | now |
|---|---|---|
| `MIN_TRADABLE_PRICE_RS` (entry gate, config.py) | 200.0 | **0.0 — live now** |
| `MIN_PRICE` (universe, core/universe_builder.py) | 200.0 | 0.0 — *inert* |
| `MAX_PRICE` (universe, core/universe_builder.py) | 10,000.0 | inf — *inert* |

The entry gate took effect immediately. **The two universe bounds do
nothing until `data/master_stocks.csv` is rebuilt**, which is why the
tradable list is still 668 symbols.

Reason for the change, in the operator's words:

> "Remove cap on below 200 & above 10,000 rs as we have moved from MIS
>  to MTF we left these two unchanged."

Both bounds were MIS-era arguments — tick granularity on a cheap stock,
and whole-share sizing quantisation on an expensive one. Both were about
same-day round trips. Neither survives multi-day MTF holding.

---

## What the rebuild will do

Measured against the current master on 29 July:

```
  master rows                973
  subscribed today           668
  admitted by the rebuild   +193  stocks under Rs 200
                             +21  stocks over Rs 10,000
  new universe            ~882    a 32% increase
```

**Every one of those 214 symbols is untested.** They have never been in
a session, never had an ORB built, never had their security ID confirmed
against Dhan's scrip master.

Liquidity is unchanged and still applies to all of them:
`MIN_TURNOVER_RS = 50,000,000` (Rs 5cr/day). A cheap stock that barely
trades still cannot get in — which is the real risk of dropping a price
floor, not the price itself.

---

## The run, Friday after 15:30

```
py tools/build_universe.py          # or the subscribe-list refresh
py tools/verify_master_database.py  # security IDs against Dhan
py tools/preflight.py               # must pass before Monday
```

Then **check, before Monday**:

- [ ] How many symbols the universe actually became
- [ ] Every new security ID resolves against Dhan's scrip master
- [ ] No SME / trade-to-trade / fund scrips slipped in on the EQ series
- [ ] The feed can carry the extra symbols — snapshot cadence is already
      ~4.6s per symbol at 666, and it gets slower with more
- [ ] `data/backtest_candles.db` has no history for the new names, so
      their ATR and volume averages start empty on day one

**The feed cadence is the one to watch.** More symbols means a slower
loop, and the opening-range window is only fifteen minutes long.

---

## Going live

Live date is **Monday 3 August**. If the rebuild is not fully checked by
Sunday night, go live on the 668 that have been tested and add the rest
the following weekend. Trading real money on 214 symbols nobody has ever
watched is not a thing to do on day one.
