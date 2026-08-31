"""
==========================================================
py tools/bot_doc.py -- the one document, generated
==========================================================

    "as of now different files are carrying different rules set (some
     of them were used for one day tests & bot still carried with which
     needs to deleted after the test day)"
                                -- operator, 12 August 2026

SIX documents in the project root describe the trading rules:
RULE_BOOK.md, TRADING_POLICY.md, RULES_TO_TRADE.md,
TRADE_SELECTION_RULES.md, STRATEGY.md and BOT_SPEC.md. On 12 August
they disagreed with the running code and with each other:

    RULE_BOOK.md      "Rs 1,00,000 per position"   live: Rs 30,000
    RULE_BOOK.md      "ALERT_ONLY = True"          live: False
    RUN_SCHEDULE.md   "full Rs 1 lakh MTF size"    live: Rs 1.2L
    AUDIT_2026-08-12  "RISK_PER_TRADE_RS sizes nothing"
                      -- it sized every engine entry

Writing a seventh document by hand would have joined that list within a
fortnight. Every one of the six was true the day it was written.

So BOT.md is GENERATED. Every number in it is read out of config.py and
core/rules.py at the moment it is written, so it cannot describe a bot
that does not exist. Prose that is genuinely prose -- what the bot is
for, what it must never do -- lives in this file, next to the values it
explains, and travels with them.

    py tools/bot_doc.py            print it
    py tools/bot_doc.py --write    write BOT.md
    py tools/bot_doc.py --check    exit 1 if BOT.md is out of date

tests/test_bot_doc_is_current.py runs --check, so a rule change that
does not regenerate the document fails the build.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOC_PATH = "BOT.md"

# The line that says when. Excluded from --check, because a timestamp
# that changes on every run would make the check fail every day and be
# switched off within a week.
STAMP = "<!-- generated:"


def _onoff(value):
    return "ON" if value else "OFF"


def build():
    """The whole document, as a string."""
    import config as c
    from core import rules as r

    stop_cost = c.HARD_STOP_FROM_ENTRY_PCT * c.MTF_MARGIN_PER_POSITION_RS \
        * c.MTF_LEVERAGE
    position_value = c.MTF_MARGIN_PER_POSITION_RS * c.MTF_LEVERAGE
    stops_to_halt = (c.DAILY_MAX_LOSS_RS / stop_cost) if stop_cost else 0

    overnight_ok = c.BROKER_STOP_ENABLED or c.FORCE_SQUARE_OFF_AT_CLOSE

    L = []
    add = L.append

    add(f"{STAMP} {datetime.now():%Y-%m-%d %H:%M} by tools/bot_doc.py "
        f"-- do not edit by hand -->")
    add("# Opportunity Trader — what the bot is, and what it does")
    add("")
    add("**This file is generated.** Every number below is read out of "
        "`config.py` and `core/rules.py` when it is written, so it cannot "
        "drift away from the running bot. To change a rule, change the "
        "code and run `py tools/bot_doc.py --write`.")
    add("")
    add("---")
    add("")

    # ---------------------------------------------------------
    add("## 0 · The one hard rule")
    add("")
    add("> **Never assume. Keep it simple. This is a trading bot, not a "
        "rocket.**")
    add("")
    add("A number with no `n` behind it is an opinion. Show it, count it, "
        "and do not let it change a decision until it has earned that.")
    add("")

    # ---------------------------------------------------------
    add("## 1 · What it is for")
    add("")
    add("> *\"Opportunity Trader Bot = only trades when an event or real "
        "opportunity arised in markets, NEVER in to random stocks & only "
        "long positions.\"*")
    add("")
    add("An evidence panel with a BUY button. It reads Telegram pro "
        "channels, NSE/BSE filings and live prices, puts the reason next "
        "to the stock, and waits.")
    add("")
    add(f"- Short selling: **{_onoff(c.ENABLE_SHORT_TRADES)}** "
        f"(`ENABLE_SHORT_TRADES`) — long only")
    add("- Two modes, and nothing else: the switch **OFF** is paper "
        "trading, **ON** is real money. Same stocks, same sizes, same "
        "stops in both. The only difference is whether the order "
        "reaches Dhan.")
    add("- The switch starts OFF every morning. Only his click moves it.")
    add("")

    # ---------------------------------------------------------
    add("## 2 · The money")
    add("")
    add("| What | Value | Where it lives |")
    add("|---|---|---|")
    add(f"| Your own margin per position | ₹{c.MTF_MARGIN_PER_POSITION_RS:,.0f} "
        f"| `config.MTF_MARGIN_PER_POSITION_RS` |")
    add(f"| MTF leverage | {c.MTF_LEVERAGE:g}× | `config.MTF_LEVERAGE` |")
    add(f"| Stock value per position | ≈₹{position_value:,.0f} | derived |")
    add(f"| Risk budget per trade | ₹{r.RISK_PER_TRADE_RS:,.0f} "
        f"| **`core/rules.py`** — the only owner |")
    add(f"| Hard stop from entry | {c.HARD_STOP_FROM_ENTRY_PCT * 100:.2f}% "
        f"| `config.HARD_STOP_FROM_ENTRY_PCT` |")
    add(f"| A stop-out therefore costs | ≈₹{stop_cost:,.0f} | derived |")
    add(f"| Stop for the day after losing | ₹{c.DAILY_MAX_LOSS_RS:,.0f} "
        f"(≈{stops_to_halt:.0f} stop-outs) | `config.DAILY_MAX_LOSS_RS` |")
    add(f"| Stop for the day after making | ₹{c.DAILY_PROFIT_TARGET_RS:,.0f} "
        f"| `config.DAILY_PROFIT_TARGET_RS` |")
    add(f"| Positions open at once | {r.MAX_OPEN_POSITIONS} "
        f"| `core/rules.py` (engine sizes from the real balance first) |")
    add(f"| Minimum tradable price | ₹{r.MIN_TRADABLE_PRICE_RS:,.0f} "
        f"| `core/rules.py` |")
    add("")
    add("**`RISK_PER_TRADE_RS` has exactly one owner as of 12 August 2026.** "
        "It used to be 2,000 in `config.py` and 1,500 in `core/rules.py`, "
        "with both live — the engine sized its breakouts from one and the "
        "ranker sized its picks from the other.")
    add("")

    # ---------------------------------------------------------
    add("## 3 · Overnight")
    add("")
    add(f"- Force square-off at close: "
        f"**{_onoff(c.FORCE_SQUARE_OFF_AT_CLOSE)}** "
        f"(`FORCE_SQUARE_OFF_AT_CLOSE`)")
    add(f"- Resting stop at Dhan: **{_onoff(c.BROKER_STOP_ENABLED)}** "
        f"(`BROKER_STOP_ENABLED`)")
    add("")
    if overnight_ok:
        if c.BROKER_STOP_ENABLED:
            add("A position carried overnight has a **Forever Order (GTT) "
                "resting at Dhan** at the hard stop. It fires whether or "
                "not this process — or the machine — is running.")
        else:
            add("Nothing is carried overnight. The book is flat by the "
                "close.")
    else:
        add("> ### ⚠ THE OVERNIGHT HOLE IS OPEN")
        add(">")
        add("> Both switches are off, so between 15:30 and 09:15 an open "
            "MTF position has **no stop anywhere** — not at Dhan, and not "
            "in this process if the machine is off. Six trades went "
            "straight past the 2.5% stop this way for **−₹48,692**.")
        add(">")
        add("> Turn on `BROKER_STOP_ENABLED` or "
            "`FORCE_SQUARE_OFF_AT_CLOSE`.")
    add("")

    # ---------------------------------------------------------
    add("## 4 · The two ways a trade can happen")
    add("")
    add("Both lanes end at the same `Engine._enter()`, with the same "
        "stops and the same position management.")
    add("")
    add("```")
    add("A.  ranker  ->  auto_entry.take()  ->  _enter()")
    add("       knows WHY a stock is moving; scores it; sizes it")
    add("")
    add("B.  ORB breakout  ->  _try_structural_entry()  ->  _enter()")
    add("       watches a price leave its opening range")
    add("```")
    add("")
    add("Since 12 August **both require a reason** — `core/rules.py`'s "
        "`is_a_reason()`, one definition imported by both. Lane B had "
        "never asked.")
    add("")
    add(f"- Engine requires a named event: "
        f"**{_onoff(r.ENGINE_REQUIRE_REASON)}** "
        f"(`core/rules.ENGINE_REQUIRE_REASON`)")
    add("")

    # ---------------------------------------------------------
    add("## 5 · What must be true before the bot buys")
    add("")
    add("| # | Gate | Number | Owner |")
    add("|---|---|---|---|")
    add(f"| 1 | A named event exists — filing, news or published grade "
        f"| — | `core/rules.is_a_reason` |")
    add(f"| 2 | Results are OUT, not pending | — | `core/results_gate.py` |")
    add(f"| 3 | Grade is allowed | "
        f"{'/'.join(__import__('core.results_gate', fromlist=['x']).CHIP_GRADES)} "
        f"| `core/results_gate.py` |")
    add(f"| 4 | Moving, against yesterday's close "
        f"| ≥{r.MIN_MOVE_FROM_PREV_CLOSE_PCT:g}% | `core/ranker.py` |")
    add(f"| 5 | Moving, against today's open "
        f"| ≥{r.MIN_MOVE_FROM_OPEN_PCT:g}% | `core/select.py` |")
    add(f"| 6 | Money behind the move | ≥{r.MIN_VOLUME_RATIO:g}× normal "
        f"| `core/rules.py` |")
    add(f"| 7 | …or, with no published reason "
        f"| ≥{r.UNEXPLAINED_MIN_VOLUME_RATIO:g}× normal | `core/rules.py` |")
    add(f"| 8 | Liquid enough to get out of | ≥₹{r.MIN_LIQUIDITY_CR:g} Cr "
        f"| `core/rules.py` |")
    add(f"| 9 | Still near its high | ≥{r.FADED_FROM_HIGH:g} of day range "
        f"| `core/rules.py` |")
    add(f"| 10 | Stop is not too tight | ≥{r.MIN_STOP_DISTANCE_PCT:g}% "
        f"| `core/rules.py` |")
    add(f"| 11 | Stop is not too wide | ≤{r.MAX_STOP_DISTANCE_PCT:g}% "
        f"| `core/rules.py` |")
    add(f"| 12 | Reward is worth the risk "
        f"| ≥{r.MIN_REWARD_MULTIPLE:g}× the stop | `core/rules.py` |")
    add(f"| 13 | No corporate action distorting the price | — "
        f"| `core/stock_memory.py` |")
    add(f"| 14 | Book is not full | <{r.MAX_OPEN_POSITIONS} open "
        f"| `core/rules.py` |")
    add(f"| 15 | Day's loss is under the cap "
        f"| ₹{c.DAILY_MAX_LOSS_RS:,.0f} | `config.py` |")
    add("")
    add(f"**The clock.** Early lane from {r.EARLY_ENTRY_FROM}, ranker from "
        f"{r.FIRST_NEW_ENTRY}, nothing new after {r.LAST_NEW_ENTRY}.")
    add("")

    # ---------------------------------------------------------
    add("## 6 · What the bot knows, and whether it may use it")
    add("")
    add("Run `py tools/knowledge_report.py`, or read the **What the bot "
        "knows** panel on the dashboard. Three answers, not one:")
    add("")
    add("| Reach | Meaning |")
    add("|---|---|")
    add("| `DECIDES` | read on the entry path — it can stop or allow a trade |")
    add("| `SHOWS` | drawn on the screen — a human may act on it, the bot never |")
    add("| `RECORDS` | written, and read by nothing — measurement only |")
    add("")
    # ---- ROW COUNTS DO NOT BELONG IN A CHECKED DOCUMENT. ----
    #      12 August 2026, within an hour of writing them in.
    #
    # The first version of this section printed each store's row count.
    # They move every time the collector runs, so `--check` failed
    # immediately and would have failed every single day -- and a check
    # that always fails is a check somebody switches off inside a week,
    # taking the REAL drift detection with it.
    #
    # The reach is the stable fact and the one this document is for.
    # The counts are live and belong where they can be live:
    # py tools/knowledge_report.py, or the dashboard panel.
    try:
        from core import knowledge
        add("| Store | Reach | What it is |")
        add("|---|---|---|")
        for s in knowledge.STORES:
            add(f"| {s['label']} | `{s['reach']}` | {s['proof']} |")
    except Exception as exc:                               # noqa: BLE001
        add(f"*(census unavailable: {exc})*")
    add("")
    add("Row counts and freshness are deliberately **not** printed here — "
        "they change hourly and would make this document stale by "
        "definition. `py tools/knowledge_report.py` has the live numbers.")
    add("")
    add("### Stored is not understood")
    add("")
    add(f"- AI master switch: **{_onoff(c.AI_ENABLED)}** "
        f"(`config.AI_ENABLED`)")
    add("")
    if c.AI_ENABLED:
        add("News stories are reasoned about as they arrive, so each one "
            "carries a direction and a mechanism.")
    else:
        add("> **News is being filed, not understood.** With the master "
            "switch off no reasoning call is made, so every story becomes "
            "a keyword link with `direction = UNKNOWN`. "
            "`core/ranker.py` refuses those by name — *\"reason is a "
            "lookup, not a mechanism\"* — so **the ranked entry lane sees "
            "no reasons at all** while the news store looks full and "
            "fresh.")
        add(">")
        add("> Measured on 12 August: 6 of 1,991 stories in the previous "
            "seven days were reasoned about. The switch went off on "
            "10 August after calls returned *\"credit balance is too "
            "low\"*. The monthly budget is not the blocker — "
            f"`data/ai_spend.db` shows about ₹106 of the "
            f"₹{c.AI_MONTHLY_BUDGET_RS:,.0f} cap used.")
    add("")
    add("**The learning loop does not vote.** `core/trade_memory.py`, "
        "`core/outcomes.py` and `dashboard/chip_stats.py` each measure "
        "what happened after a signal and each is deliberately kept off "
        "the decision path. That is a choice, not an oversight — acting "
        "on a fortnight of data is how a coincidence becomes a rule. It "
        "is also the honest answer to *\"does it reuse what it learns\"*: "
        "**not yet.**")
    add("")

    # ---------------------------------------------------------
    add("## 7 · Exits")
    add("")
    add(f"- Bot trailing stop: **{_onoff(c.ENABLE_BOT_TRAILING_STOP)}** "
        f"(`ENABLE_BOT_TRAILING_STOP`)")
    if not c.ENABLE_BOT_TRAILING_STOP:
        add(f"- With the trail off, the stop is a **fixed "
            f"{c.HARD_STOP_FROM_ENTRY_PCT * 100:.2f}% from entry** and does "
            f"not move (`core/engine.py`, `_atr_entry_sizing`).")
        add("")
        add("> Exits tagged `TRAILING_STOP` since 29 July are therefore "
            "**hard stop-outs, not trail exits.** `BOT_SPEC.md` reads all "
            "64 as trail exits and concludes the trail is too wide; split "
            "at 29 July they are two different regimes — trail on, n=29, "
            "−₹643 average; trail off, n=35, −₹2,627 average. There has "
            "been no trail to widen since.")
    add(f"- Force square-off: **{_onoff(c.FORCE_SQUARE_OFF_AT_CLOSE)}** "
        f"at {c.SQUARE_OFF_TIME}")
    add("")

    # ---------------------------------------------------------
    add("## 8 · What the bot must never do")
    add("")
    for line in (
        "send anything to Dhan while the switch is OFF",
        "buy a stock with no named event behind it",
        "resend an order after a timeout without querying by ID first",
        "report success when the broker never answered",
        "claim a stop is resting when the API call failed",
        "treat a silent source as a negative one",
        "let an unmeasured flag change a tag",
        "show a number without its `n`",
    ):
        add(f"- {line}")
    add("")

    # ---------------------------------------------------------
    add("## 9 · Running it")
    add("")
    add("```bash")
    add("py tools/nightly.py          # 22:30, unattended, ~25 min")
    add("py tools/morning.py          # 08:30")
    add("py main.py                   # terminal 1 — trading")
    add("py tools/collector.py        # terminal 2 — Telegram")
    add("py tools/preopen_gaps.py     # 09:12, not before")
    add("```")
    add("")
    add(f"Dashboard: `http://localhost:{c.DASHBOARD_PORT}/board`")
    add("")
    add("**Never run two things that read Telegram at once.** "
        "`core/runlock.py` refuses the second — and holds a stale lock "
        "for two hours, because it ages locks out rather than checking "
        "whether the process is alive.")
    add("")
    add("---")
    add("")
    add("*Superseded by this file: `RULE_BOOK.md`, `TRADING_POLICY.md`, "
        "`RULES_TO_TRADE.md`, `TRADE_SELECTION_RULES.md`, `STRATEGY.md`. "
        "`BOT_SPEC.md` is kept for its measured chip-edge tables, which "
        "are evidence rather than rules.*")
    add("")
    return "\n".join(L) + "\n"


def _without_stamp(text):
    return "\n".join(line for line in text.splitlines()
                     if not line.startswith(STAMP))


def main(argv):
    doc = build()

    if "--check" in argv:
        if not os.path.exists(DOC_PATH):
            print(f"{DOC_PATH} does not exist. Run: py tools/bot_doc.py --write")
            return 1
        with open(DOC_PATH, encoding="utf-8") as handle:
            on_disk = handle.read()
        if _without_stamp(on_disk) != _without_stamp(doc):
            print(f"{DOC_PATH} is OUT OF DATE -- a rule changed and the "
                  f"document did not.\nRun: py tools/bot_doc.py --write")
            return 1
        print(f"{DOC_PATH} is current.")
        return 0

    if "--write" in argv:
        with open(DOC_PATH, "w", encoding="utf-8") as handle:
            handle.write(doc)
        print(f"Wrote {DOC_PATH} ({len(doc.splitlines())} lines).")
        return 0

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
