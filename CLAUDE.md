# Opportunity Trader — read this first

An NSE cash, intraday, long-only MTF trading bot (Dhan broker), run from
the operator's Windows laptop. `main.py` trades; `tools/collector.py`
gathers news and Telegram; `dashboard/` is the desk he watches.

## If you are a cloud / phone session

You are one if `data/*.db`, `logs/` and `.env` are missing. The laptop is
**off** and the operator is working from his phone. So:

- **Never trade, never connect to Dhan or Telegram, never add a token or
  secret** to any file or environment variable. Nothing here should be
  able to place an order.
- **Build and test only.** Changes live on a branch → PR. Nothing reaches
  the bot until he is home, pulls, runs the tests, runs a PAPER session,
  and only then switches ON.
- Tests that read `data/*.db`, `data/*.json` runtime files or `logs/` will
  fail here. That is the environment, not your change. Known failures that
  also fail on the laptop: `test_fno_stops_trading_before_the_close`
  (F&O list file stale), `test_who_else_does_this_land_on` ×2 and
  `test_a_sector_moving_is_the_event` (sector membership data).
- The logs and trade database are not in the repo. Their digests are:
  `docs/handoff/errors-7-to-10-sep.md` and
  `docs/handoff/trades-7-to-10-sep.csv`.

**Start with `docs/handoff/open-problems-10-sep.md`** — what is broken,
the evidence, and what has already been decided.

## How he wants you to work (from his own notes)

- **His rules are settled. Do not ask him to restate them.** Read
  `docs/claude-notes/his-trading-rules.md`. Decide from them, say what you
  did and why; stop only for something irreversible, something that risks
  real money, or something his rules genuinely don't decide — and say
  which of the three it is.
- **ON = real, OFF = paper. No third state**, ever
  (`docs/claude-notes/the-one-switch.md`).
- **Every change states its effect on trading** — what the bot will do
  differently tomorrow. Answer that before he has to ask.
- **Never assume. Every number needs an n.** Measure; do not guess. A
  green test suite proves the code as written, not the path a live order
  takes — trace the live path (`verify-the-value-the-live-path-reads.md`).
- **One fact, one place.** Nearly every fault on 7–10 Sep was the same
  fact stored twice and drifting (the switch vs `TRADING_MODE`, the stale
  board vs the live tick, UTC vs IST). Remove the second copy; don't patch
  a reader.
- **Never mix old data with new rules**, never average across stocks, and
  never tune a rule on the same sessions you validate it on.
- **Simple over complex.** "BOT TRADING = keep the simple . NEVER ASSUME."
- **Rules are provisional**; a quiet day with no trade is a correct day;
  there are no fixed trade limits — trade when opportunity shows.

## Where things are

- `docs/claude-notes/MEMORY.md` — index of the working notes. They are
  point-in-time: file:line references in them may have moved. Check the
  code before repeating a claim.
- `docs/claude-notes/opportunity-trader-architecture.md` — the two entry
  lanes and which dashboard page is live.
- Code comments in this repo are deliberately long and dated, quoting the
  operator. Keep that style: say what broke, when, and the measurement.
- Commit messages: a plain sentence as the title; the body carries the
  measurement and a line starting "Effect on trading:".

## Bringing phone work home (for the laptop session)

    git pull
    py -m pytest -q          # ~20 min; compare against the known failures above
    # then a PAPER session before the switch goes ON
