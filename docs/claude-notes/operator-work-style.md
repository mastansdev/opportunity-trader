---
name: operator-work-style
description: "How the Opportunity Trader operator wants work done — never assume, keep it simple, evidence with an n behind every number"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-01T17:04:00.704Z
---

The operator's standing instruction, repeated in his own words across the
codebase and in chat: **"NEVER ASSUME. Keep it simple. This is a trading
bot, not a rocket."** A number without an `n` behind it is an opinion.

**Why:** He has been burned repeatedly by rules set on n=25 in late July
that stopped being true by August, and by documents that were accurate
the day they were written and quietly rotted. He also caught three false
conclusions himself, which is why measurement-before-action is now the
house discipline.

**How to apply:**
- Query the databases for real numbers before making any claim. Do not
  trust the audit documents in the repo — `AUDIT_2026-08-12.md` called
  `RISK_PER_TRADE_RS` "legacy, sizes nothing" while it sized every
  engine entry, and `BOT_SPEC.md` diagnosed a "trail width bug" on 64
  exits that were two different regimes averaged together.
- When evidence contradicts something you just built, say so plainly and
  write the counter-evidence into the code comment. He would rather have
  an honest "n=7, this proves nothing" than a confident wrong answer.
- He is not a native English speaker and writes in short bursts. Give
  him tables and plain sentences, not paragraphs of hedging.
- **PLAIN WORDS AND A REAL STOCK, EVERY TIME.** He has had to ask for
  this more than once — *"every time i need to remind you? about plain
  simple words with real stock examples"* (1 Sep 2026). Never explain a
  rule with the constant's name or the code's own phrasing. Say what it
  means, then name the stock it actually hit and the count:
  "It barely moved — less than 3% — 194 stocks yesterday, ADANIPOWER,
  ASHOKLEY…" not "MIN_MOVE_FROM_PREV_CLOSE_PCT = 3.0". The examples are
  in `data/decisions.db` (`refused_symbols`) and `data/signal_journal.db`
  (`signals.refused_why`), one row per stock per day — query them rather
  than describing the rule in the abstract. Same for jargon: "more
  buying than selling" not "cumulative delta"; "broker won't lend
  against it" not "not MTF-eligible".
- Verify flags exist before using them. `py tools/nightly.py --dry-run`
  silently ran the full live chain because the flag is `--dry`.

See [[opportunity-trader-architecture]] and
[[opportunity-trader-open-decisions]].
