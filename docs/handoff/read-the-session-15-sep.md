# How to read Monday's session — 15 September 2026

Written the night before, so the questions are fixed in advance and
cannot be chosen afterwards to fit whatever happened.

**Run it in PAPER. The switch starts OFF and must stay OFF.** Three
rules that change what the bot buys and sells went in on 14 September
and none has faced a session it was not measured on.

---

## Do NOT judge it on the day's P&L

One session is noise about a rule. A good day does not make the
freshness gate right and a bad one does not make it wrong. The
questions below are answerable from one session; "did it work" is not.

---

## 1. The clock — the one that closes a two-week question

Look for `[CLOCK]` in the log (once a minute):

```
[CLOCK] The exchange's timestamps run +0.4s from this machine ...
```

- **under ~2s** — the feed is healthy and the machine clock agrees with
  NSE. The timing complaint is closed.
- **minutes** — that is the cause, finally visible. Every time rule
  (ORB window, 15:15 cutoff, move age, the drift exit's 45 minutes)
  reads the machine clock, so they were all wrong together.
- A **WARNING** rather than a quiet line means past 5s.

## 2. Did the board stop blocking the clock

`[SLOW]` lines now break out `gl_rows` separately from each panel:

```
[SLOW] The board took NN.Ns ... Worst: ranked N.Ns, gl_rows N.Ns, ...
```

- **Heartbeats should be regular.** On 10 Sep they landed 85-100s apart
  while rebuilds ran. If they are steady now, the decoupling worked.
- `gl_rows` is the shared 1,314-symbol walk. Whatever it costs is the
  honest number — on 10 Sep it was hidden inside `shortlist` and I
  misread it twice. This is the number the speed fix will target.

## 3. The freshness gate — read the REFUSALS, not the fills

This is the change that alters the day most: on last week's book it
would have refused 61 of 95 entries. Expect **far fewer trades**. A
quiet day is the rule working.

For each refusal like *"already 4.2% above the day's open"*:

- **did that stock keep running, or fade?** If the refused ones mostly
  faded, the gate is earning its place. If they ran, it is costing
  money and `ENTRY_MAX_EXTENSION_PCT = None` turns it off.

Refusals carry their reason into `core/signal_journal.py`; taken trades
now record `extension_pct` and `drift_since_rank_pct` in
`data/trade_memory.db`. Both halves are on record for the first time.

## 4. Did anything get flattened by hand at 15:15

Last week: **32 trades, -30,444 gross**, all closed by hand at
15:11-15:22 because nothing owned a drifting position.

- **Zero hand-flattening** means `DRIFTED_NO_MOVE` did its job.
- Any position still sitting there at 15:10, losing, untouched, means
  the 45-minute / +1.0% rule did not catch that shape.

## 5. Did a winner give its profit back

Look for positions that went up and came back.

- `peak_mtm` is now recorded on every closed trade. For any trade,
  compare what it was worth at its best against what was booked.
- The profit lock should stop a position that passed **+2.5%** from
  returning below roughly +2.0%. Past **1.5R** it hands over to the
  older 1:1 lock deliberately, so a big runner is NOT capped.

## 6. Telegram

- The **Last message** column should read in IST, matching when posts
  actually arrived (real lag ~0.2 min). Not 5h30m behind.
- Pushed pictures should now carry their text. Look for
  `Recovered the text of N picture(s)`.
- Alerts now end with a `[MOVE: ...]` clause. Judge whether it is
  enough to tell a live breakout from a spent one at a glance.

---

## If something is wrong, the one-line switches

    ENTRY_MAX_EXTENSION_PCT = None     the freshness gate off
    DRIFT_EXIT_ENABLED = False         the drift exit off
    PROFIT_LOCK_ENABLED = False        the profit lock off

Each is independent, and none of them touches the switch.

## What is NOT protecting him

- **No daily loss cap** in either mode — his instruction, 14 Sep.
  `PAUSE` on Telegram is the only brake, and it is his hand on it.
- **No rotation** — a better stock still cannot displace a weaker one.
- **No square-off at close** — MTF positions carry overnight, as set.

---

## After the close

1. Answer the six questions above from the log and the store.
2. Rebuild speed, now that `gl_rows` is measured separately.
3. Delete the 4 genuinely dead branches (not 19 — nine of those are
   tested features deliberately switched off).
4. `MISSED_STOP_RECONCILED`: 6 trades, -4,211, still undiagnosed.
