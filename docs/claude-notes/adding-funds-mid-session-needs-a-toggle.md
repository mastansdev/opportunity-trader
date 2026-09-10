---
name: adding-funds-mid-session-needs-a-toggle
description: "SETTLED 7 Sep 2026 — the bot now follows the Dhan balance live, no OFF/ON toggle and no restart needed"
metadata:
  node_type: memory
  type: project
---

**Done 7 September 2026.** Superseded the 6 Sep workaround ("funds add
then OFF . some time then ON"), which is no longer needed.

> "what if i add funds in to dhan after some time like lets say 50 K
> around 07:30 & 1 Lakh around 11:30. i don't want restart main run ,
> it must fetch for available funds & thats the right mechanism"

`main.py._follow_the_account(portfolio, engine, before)` runs from the
heartbeat, inside `if _real_orders_armed():`, and writes the reading
through to `portfolio.starting_capital`. Verified live on the day:
69,429.68 -> 1,00,000.68 with no prompting.

**The trap, which is why it is not one line.** Dhan's
`availabelBalance` is ALREADY NET of margin in use, and
`trading/portfolio.py` then computes
`available_margin = starting_capital - used_margin(open_positions)`.
Assigning the available figure straight in subtracts the same margin
twice and quietly UNDER-sizes every order. The bot's own used margin is
added back first. `tests/test_the_bot_follows_the_account.py` guards
this.

**Paper is untouched** -- it runs only while real orders are armed, so
a paper week is still measured against a constant purse. It only
follows a reading whose `source` is `"dhan"`.

**His own Dhan positions stay his:** Dhan has already netted them out
of the available figure, so money tied up in his manual trades is money
the bot cannot spend. Arithmetic, not the bot managing his book.

Caveat: the purse this writes into is only consulted when the process
is in LIVE mode -- see the unfinished half in [[the-one-switch]].
