---
name: his-trading-rules
description: "The complete rule set for Opportunity Trader in his own words — entries, exits, sizing, book separation. Read this instead of asking him again."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-02T17:31:46.628Z
---

**He should not have to state these again.** 2 September 2026:

> "my rules are simple & i cannot tell you each & every time"

## The shape of it

NSE cash, intraday, **long only**, MTF. Trade 09:15–15:15.

## Entry — only on a reason

A stock is a candidate only when something explains the move:

- NEWS
- EVENTS (upside)
- GOVT SCHEME — **sector-level schemes, not order books companies win.**
  He corrected this specifically: "Govt order in the sense of Schemes
  which will boost sectors not order book received by companies."
- ORDER + volume
- ORB + volume
- **Volume surge ≥10× its own normal** — a reason on its own
- During results season only: results grades + volume

"all irrespective of time." No door outranks another.

Candidates are ordered by **volume multiple, not score** — measured over
15 sessions: highest volume × earned +₹565/trade, highest score −₹68
(worse than random).

> "trade when opportunity occurs, not first come = first buy or orb path"

## Exit

- 2.0 ATR stop
- Buying dried up (order flow says momentum is finished)
- "book atleast 2500 rs"

2 September, on sizing:

> "to be realistic i'll trade based on qty in my real trading. not
> based on risk per trade & i'll book profits once orderflow shows the
> momentum exhuasted"

So: **size from the MTF slot, stop from the stock's own range, exit on
order flow.** Not a fixed rupee risk per trade. See
[[what-the-live-stop-and-seats-actually-are]].

## Standing constraints

- **One stock, one trade a day** — including when he sells by hand;
  his manual sell locks the bot out of that name for the day.
- **His own Dhan trades never block the bot.** Separate books, shown
  separately on screen, never merged.
- Rotation stays OFF.
- Number of trades depends on available capital and opportunity only.
  See [[no-fixed-limits-trade-when-opportunity-shows]].
- ON = real trades, OFF = paper. No third state — [[the-one-switch]].
- Never pool or average across stocks — "thats not stock working
  mechanism". See [[never-mix-old-data-with-new-rules]].
- No duplicates, ever. Lose no information by mistake.
- Never hit anti-bot crawls at NSE or Telegram.

## How he wants it built

> "create an opportunity trading bot with simpler mechansim and avoid
> complex work whenever simpler working methods available."

> "BOT TRADING = keep the simple . NEVER ASSUME."

Rules are provisional, not permanent — a gate that fenced in a weak
signal retires when a better signal arrives:
[[rules-are-provisional-not-permanent]].
