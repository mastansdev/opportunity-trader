# What the bot needs that is NOT code

**Written 31 July 2026 — late.**

This document should have existed before the first line of `main.py`.
It didn't, and the cost was today: a live trial planned for weeks, a
funded account, the market open, and the bot could not place a single
order because of an account setting nobody had checked.

> *"when i asked u first about my idea of trading bot. u need to tell all
> this pre-requisites right before touching any code."*
> — operator, 31 July 2026

Correct. Everything below was knowable on day one.

---

## 1. Static IP — **BLOCKING, and the one that cost today**

**Status: NOT DONE.**

SEBI requires every API-placed order to originate from a **registered
static IP**. This is a regulation, not a Dhan setting. No code change,
library or workaround gets past it.

- Applies to: **placing, modifying, cancelling** orders
- Does NOT apply to: funds, positions, quotes, order status, the tick feed

**That asymmetry is why this went unnoticed for weeks.** Every read
worked perfectly, so everything looked healthy. Only the last step —
the order — was blocked.

```
BUY AARTIIND  -> DH-905 Invalid IP
BUY SATIN     -> DH-905 Invalid IP
BUY SPORTKING -> DH-905 Invalid IP
```

**What is needed**

- A genuinely static IP. JioFiber is behind CGNAT: `157.50.96.168` is
  shared with other subscribers and rotates. Call **1800-896-9999** and
  ask for the **static IP add-on** (~₹299 + GST/month).
- It must be **IPv4**, and the bot must be pinned to IPv4 — this machine
  currently reaches `api.dhan.co` over **IPv6**, so a whitelisted IPv4
  would never be used. *(Code fix, mine, not yet built.)*
- Whitelist it: Dhan web → DhanHQ APIs, or `POST /v2/ip/setIP`.
- **Regenerate the token afterwards.** A token issued before the IP was
  added does not carry the permission.

> **A whitelisted IP is locked for 7 days.** Setting a rotating address
> to get one fill today can cost a week of live trading.

**Check it:** `py tools/dhan_ip_check.py`

---

## 2. Access token — expires every 24 hours

**Status: WORKS, but it is a daily chore and a live hazard.**

Dhan tokens last **24 hours from generation**.

```
generated  31/07/2026 09:24
dies       01/08/2026 09:24
```

**The trap:** start the bot at 09:00 tomorrow on today's token and it
dies at **09:24 — nine minutes into the session.** The tick feed keeps
running on its own socket while every REST call starts failing, so it
reads as a broker outage, not an expiry.

**Daily, before 09:00:** regenerate the token, paste into `.env`,
then start `main.py`.

**The permanent fix — set up TOTP** (Dhan web → DhanHQ APIs → Setup
TOTP). With TOTP the bot can generate its own token at startup and this
chore disappears. Required before any unattended automation.

**Check it:** `py tools/dhan_ip_check.py` now warns if the token dies
before 15:30 today.

---

## 3. Funds

**Status: DONE.** ₹1,047.38 available, read live from Dhan.

The book's capital comes from `get_fund_limits()` in LIVE — not from
`config.PAPER_STARTING_CAPITAL`. Until 31 July the dashboard showed
₹10,00,000 against an account holding a few hundred rupees.

Sizing is per position: `MTF_MARGIN_PER_POSITION_RS = 100000`. Ten
positions needs ten times that in margin.

---

## 4. MTF consent

**Status: ACTIVE**, confirmed on the account profile.

Without it every MTF order rejects. The bot trades MTF exclusively.

---

## 5. Data API subscription

**Status: CHECK IT** — `dataPlan` on the profile.

Quotes, historical data and the option chain are **paid** at Dhan;
trading APIs are free. The bot uses quotes heavily (circuit monitor,
gainers/losers, the drift check). If the plan lapses, those fail while
orders keep working — the mirror image of the static-IP problem, and
just as confusing.

---

## 6. DDPI / POA

**Status: CHECK IT** — `ddpi` on the profile.

Needed to sell delivery holdings without a per-trade authorisation.
Intraday and MTF are unaffected.

---

## 7. Security IDs verified against Dhan

**Status: DONE, and it must stay a daily step.**

On 30 July, six symbols pointed at the wrong instrument. Our file said
CHOLAFIN was 685; Dhan says 19257. An order would have bought a
completely different company and the contract note would have been the
first you heard of it.

**Daily, 08:35:** `py tools/verify_master_database.py`

---

## 8. One machine, one session

The bot must run **09:00–15:30 without interruption**, and the opening
range (09:15–09:30) cannot be rebuilt if it is missed.

Ranges and positions now persist across restarts, so a restart after
09:30 is survivable. Startup costs about two minutes of blind feed
because the Telegram poll runs before the feed connects — a defect,
logged.

---

## THE HONEST SUMMARY

| # | Prerequisite | Status | Blocks |
|---|---|---|---|
| 1 | **Static IP + whitelist** | **NOT DONE** | **all API orders** |
| 2 | Token < 24h old | manual daily | everything, mid-session |
| 3 | Funds | done | order size |
| 4 | MTF consent | active | all orders |
| 5 | Data API plan | verify | quotes, history |
| 6 | DDPI | verify | delivery sells only |
| 7 | Security IDs | done, daily | correctness of every order |
| 8 | Uninterrupted session | done | the opening range |

**Item 1 is the only thing standing between this bot and a real fill.**
Everything else on the list is either done or a routine.

---

## THE RULE THIS DOCUMENT EXISTS TO ENFORCE

Before building any capability, state what it needs **outside the
code** — account permissions, regulations, subscriptions, hardware,
network — and confirm each one against the real account.

A capability that is fully built and cannot legally run is worth
exactly as much as one that was never built. Today proved it.
