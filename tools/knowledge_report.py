"""
==========================================================
py tools/knowledge_report.py -- does the bot use what it knows?
==========================================================

    "bot is getting results, news. but i'm not sure whether bot knows
     it. stores it and reuses when ever the same situation arises."
                                -- operator, 12 August 2026

The same census the dashboard's "What the bot knows" panel draws, in a
terminal, so the question can be answered without a browser or a
running session. See core/knowledge.py.

    py tools/knowledge_report.py            the table
    py tools/knowledge_report.py --quiet    just the verdict line

Read-only. Opens every store with mode=ro and computes nothing.

Exit code is 1 when a store is unreadable or has gone stale, so this
can be dropped into tools/nightly.py later if that is wanted -- a
silent data outage is the failure mode this exists to catch. Delivery
data sat three sessions stale for four days on a dashboard that went on
printing it beside live prices.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BAR = "=" * 78


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                       # noqa: BLE001
        pass

    from core import knowledge

    got = knowledge.census()
    quiet = "--quiet" in argv

    if quiet:
        print(got["verdict"])
    else:
        print(BAR)
        print("  WHAT THE BOT KNOWS -- and whether it may use it")
        print(BAR)
        print()
        print(f"  {got['verdict']}")
        print()
        print(f"  {'STORE':<40} {'REACH':<9} {'ROWS':>9}  {'AGE':>5}")
        print("  " + "-" * 74)

        for reach in (knowledge.DECIDES, knowledge.SHOWS, knowledge.RECORDS):
            rows = [s for s in got["stores"] if s["reach"] == reach]
            if not rows:
                continue
            for s in rows:
                n = "ERR" if s["rows"] is None else f"{s['rows']:,}"
                age = "--" if s["stale_days"] is None else f"{s['stale_days']}d"
                flag = " <-- STALE" if (s["stale_days"] or 0) >= 3 else ""
                print(f"  {s['label'][:40]:<40} {reach:<9} {n:>9}  "
                      f"{age:>5}{flag}")
                if s["problem"]:
                    print(f"  {'':<40} !! {s['problem']}")
            print()

        print("  " + "-" * 74)
        print(f"  DECIDES  read on the entry path -- can stop or allow a trade")
        print(f"  SHOWS    drawn on the screen -- a human may act, the bot never")
        print(f"  RECORDS  written, and read by nothing -- measurement only")
        print()
        print(f"  {got['counts']['total_rows']:,} rows across "
              f"{len(got['stores'])} stores, checked at {got['checked_at']}.")
        print()

        # ---- STORED IS NOT UNDERSTOOD. ----
        # The single most misleading thing a row count can do is grow
        # while nothing reads what it contains.
        reasoning = got.get("reasoning") or {}
        if reasoning.get("on") is False:
            print("  " + "!" * 74)
            print("  NEWS IS BEING FILED BUT NOT UNDERSTOOD")
            print("  " + "!" * 74)
            recent, done = (reasoning.get("recent_total"),
                            reasoning.get("recent_reasoned"))
            if recent:
                print(f"    Last 7 days: {done} of {recent} stories reasoned "
                      f"about.")
            print(f"    Lifetime   : {reasoning.get('reasoned')} of "
                  f"{reasoning.get('total')}.")
            print()
            print(f"    {reasoning.get('blocked_by')}")
            print()
            print("    This is not cosmetic. An unreasoned story becomes a")
            print("    keyword link with direction UNKNOWN, and core/ranker.py")
            print("    refuses those by name -- \"reason is a lookup, not a")
            print("    mechanism\". So the ranked entry lane sees no reasons at")
            print("    all while the news store looks full, fresh and healthy.")
            print()
        elif reasoning.get("on"):
            print(f"  News reasoning ON -- {reasoning.get('reasoned')} of "
                  f"{reasoning.get('total')} stories reasoned about.")
            print()

        if got["problems"]:
            print("  PROBLEMS")
            for line in got["problems"]:
                print(f"    - {line}")
            print()
        if got["stale"]:
            print("  STALE -- these have missed at least one session")
            for line in got["stale"]:
                print(f"    - {line}")
            print()
        if got["empty"]:
            print("  EMPTY")
            for line in got["empty"]:
                print(f"    - {line}")
            print()

        print(BAR)
        print("  The learning loop does NOT vote. core/trade_memory.py,")
        print("  core/outcomes.py and dashboard/chip_stats.py each measure")
        print("  what happened after a signal, and each is deliberately kept")
        print("  off the decision path. Acting on a fortnight of data is how")
        print("  a coincidence becomes a rule -- so it learns in public")
        print("  first. That is a decision, and it is reversible.")
        print(BAR)

    # ---- IT CRIED WOLF ON THE FIRST NIGHT. 13 August 2026. ----
    #
    # This exited 1 whenever reasoning was off. It ran as tools/
    # nightly.py's `health` step that evening and failed -- for two
    # states he had chosen on purpose: config.AI_ENABLED is False until
    # the bot earns the top-up, and trade_memory is three days old
    # because the bot is OBSERVING and no trade has closed.
    #
    # "health: exited 1 ... MOVING ON" every single night is a line he
    # learns to skip, and then it is worth nothing on the night it
    # means something. That is the exact failure tools/learning_report
    # .py's own caveat warns about, walked into hours after writing it.
    #
    # So it fails only on things that need a HUMAN TO ACT:
    #
    #   a store that cannot be read       something is broken
    #   a daily store that stopped        a feed died
    #   reasoning off WITH AI_ENABLED on  it should work and does not
    #
    # Reasoning off because the master switch is off is reported in the
    # body, loudly, and is not a failure. It is the configuration he
    # asked for.
    reasoning = got.get("reasoning") or {}
    should_be_reasoning = bool(reasoning.get("has_key")) \
        and bool(reasoning.get("ai_enabled"))
    reasoning_broken = reasoning.get("on") is False and should_be_reasoning
    return 1 if (got["problems"] or got["stale"] or reasoning_broken) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
