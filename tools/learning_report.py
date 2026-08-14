"""
What the bot has learned so far — read-only report.

Prints the trade memory grouped by the CONDITIONS each trade was taken
in: sector, hour of entry, direction, exit reason, symbol. Nothing here
changes trading; the memory has no vote (see core/trade_memory.py).

Run:  py tools/learning_report.py            (all sessions)
      py tools/learning_report.py 3          (only buckets with >=3 trades)

---- IT CRASHED ON THE ONE LINE THAT MATTERED. 12 August 2026. ----

The final block prints "these numbers are NOT yet evidence". It opened
with a U+26A0 warning sign, and the Windows console this bot runs on is
cp1252, which cannot encode it. So every run of this tool ended:

    UnicodeEncodeError: 'charmap' codec can't encode character '\\u26a0'

AFTER printing five tables of sector and hour and symbol P&L, and
BEFORE printing the sentence saying not to believe them. The tool
showed the numbers and died on the caveat, every single time.

Two fixes, both here: stdout is reconfigured to UTF-8 with replacement
so no character can ever kill this again, and the warning sign is now
ASCII. A report that cannot print its own caveat is worse than no
report.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# BEFORE anything prints. See the docstring -- a console encoding must
# never be able to swallow the caveat at the bottom of this file.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                           # noqa: BLE001
    pass

from core.outcomes import MIN_SAMPLE
from core.trade_memory import default_trade_memory


def _table(title, rows, label="bucket"):
    print(f"\n--- {title} ---")
    if not rows:
        print("   (nothing yet)")
        return
    print(f"   {label:<22}{'trades':>7}{'win%':>7}{'total P&L':>12}{'avg':>9}")
    for r in rows:
        print(f"   {str(r['key']):<22}{r['trades']:>7}{r['win_rate']:>6.0f}%"
              f"{r['total_pnl']:>12,.0f}{r['avg_pnl']:>9,.0f}")


def main(min_trades=1):
    m = default_trade_memory()
    o = m.overall()

    print("=" * 62)
    print("  WHAT THE BOT HAS LEARNED")
    print("=" * 62)

    if not o["trades"]:
        print("\nNo trades remembered yet. Run a session first.")
        return

    print(f"\nSessions recorded : {o['sessions']}")
    print(f"Trades remembered : {o['trades']}")
    print(f"Win rate          : {o['win_rate']:.1f}%  ({o['wins']}W)")
    print(f"Total P&L         : Rs {o['total_pnl']:,.0f}")
    print(f"Avg win / avg loss: Rs {o['avg_win']:,.0f} / Rs {o['avg_loss']:,.0f}")
    if o["avg_loss"]:
        print(f"Win:loss size     : {abs(o['avg_win'] / o['avg_loss']):.2f} : 1")

    _table("By SECTOR", m.by_sector(min_trades), "sector")
    _table("By ENTRY HOUR", m.by_hour(min_trades), "hour")
    _table("By DIRECTION", m.by_direction(min_trades), "direction")
    _table("By EXIT REASON", m.by_exit_reason(min_trades), "reason")
    _table("By SYMBOL (repeat offenders)", m.by_symbol(max(min_trades, 2)),
           "symbol")

    _readiness(m, o)


# ---------------------------------------------------------------
# HAS ANY OF THIS EARNED A VOTE YET?
# ---------------------------------------------------------------
# Added 12 August 2026, for the operator's question:
#
#     "bot is getting results, news. but i'm not sure whether bot knows
#      it. stores it and reuses when ever the same situation arises."
#
# The answer is no -- core/trade_memory.py says "IT DOES NOT VOTE" in
# its own docstring, deliberately. The problem was that "when should it
# start?" had no answer at all, so the decision could only ever be made
# on somebody's judgement of whether the tables above "look convincing".
# They always look convincing. That is what small samples do.
#
# So the bar is stated, in code, and checked. core/outcomes.py already
# owns the number -- MIN_SAMPLE, currently 20 -- and refuses to call a
# bucket a result below it. Imported rather than re-typed, so the two
# cannot drift.

def _readiness(memory, overall):
    print("\n" + "=" * 62)
    print("  HAS ANY OF THIS EARNED A VOTE?")
    print("=" * 62)

    buckets = (("sector", memory.by_sector(1)),
               ("entry hour", memory.by_hour(1)),
               ("exit reason", memory.by_exit_reason(1)))

    ready = []
    for label, rows in buckets:
        for r in rows:
            if r["trades"] >= MIN_SAMPLE:
                ready.append((label, r))

    biggest = 0
    for _, rows in buckets:
        for r in rows:
            biggest = max(biggest, r["trades"])

    print(f"\n  The bar is n >= {MIN_SAMPLE} in a single bucket "
          f"(core/outcomes.MIN_SAMPLE).")
    print(f"  Biggest bucket right now: n = {biggest}.")
    print(f"  Trades recorded: {overall['trades']} across "
          f"{overall['sessions']} session(s).")
    print()

    if not ready:
        print("  NOT ONE bucket has reached it. Nothing above is evidence;")
        print("  it is a picture of what happened, which is a different")
        print("  thing. Wiring any of it into a rule today would be")
        print("  measuring noise and calling it a strategy.")
        print()
        print("  THE MEMORY CORRECTLY HAS NO VOTE. Leave it that way.")
    else:
        print(f"  {len(ready)} bucket(s) have reached n >= {MIN_SAMPLE}:")
        for label, r in sorted(ready, key=lambda x: -x[1]["trades"]):
            print(f"     {label:<12} {str(r['key']):<24} n={r['trades']:<4} "
                  f"win {r['win_rate']:.0f}%  avg Rs {r['avg_pnl']:,.0f}")
        print()
        print("  Reaching the bar is permission to LOOK, not to wire. Read")
        print("  them, decide on purpose, and change one thing at a time.")
        print()
        print("  ---- AND SIZE IS NOT THE ONLY WAY A BUCKET LIES ----")
        print()
        print("  TRAILING_STOP above is n=64 and still wrong, because it")
        print("  is TWO populations added together. ENABLE_BOT_TRAILING_")
        print("  STOP went False on 29 July; split on that date:")
        print()
        print("     trail ON   (<=28 Jul)   n=29   avg   -643")
        print("     trail OFF  (>=29 Jul)   n=35   avg -2,627")
        print()
        print("  The later 35 are fixed 2.5% hard stop-outs, not trail")
        print("  exits -- they only carry that label because one method")
        print("  fires both. BOT_SPEC.md read all 64 as trail exits and")
        print("  concluded the trail was too wide. There has been no")
        print("  trail to widen for a fortnight.")
        print()
        print("  So before believing any bucket here: ask whether a")
        print("  SWITCH changed underneath it during the window.")

    print()
    print("  A reminder of why the bar exists: on 12 August the reason")
    print("  gate was measured on the ORB lane and said the opposite of")
    print("  what it was built on --")
    print()
    print("     had_reason = 0    n=49   avg   +74")
    print("     had_reason = 1    n= 7   avg  -691")
    print()
    print("  n=7. That is a coincidence wearing a conclusion, and it is")
    print("  exactly what this bar is for.")
    print("=" * 62)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
