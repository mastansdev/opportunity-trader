"""
==========================================================
Overnight picture + morning brief -- run it at 08:00
==========================================================

    py tools/premarket_brief.py              # numbers only
    py tools/premarket_brief.py --brief      # numbers + AI brief
    py tools/premarket_brief.py --history    # past briefs

Collects what happened while India slept, stores it, and prints it.
With --brief it also asks Claude for three or four sentences about it.

NOT WIRED INTO THE BOT. Nothing here touches the engine, the dashboard
or any position. It is a standalone morning read, exactly as agreed on
2026-07-28: build it now, integrate after one clean session.

The AI brief is an OPINION. Nothing in the bot acts on it, and every one
is recorded to data/morning_briefs.json with the numbers it saw -- so in
a month they can be read back against what actually happened, and the
question "was it worth anything" gets an answer rather than a feeling.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.premarket import PreMarket, requests_fetcher          # noqa: E402
from core.morning_brief import MorningBrief, anthropic_client   # noqa: E402


def show_history():
    briefs = MorningBrief(client=None).history(limit=15)
    if not briefs:
        print("\n  No briefs recorded yet.\n")
        return
    print(f"\n  {len(briefs)} brief(s) on record, newest first.")
    print("  Read these against what the market actually did.\n")
    for entry in briefs:
        print("  " + "-" * 68)
        print(f"  {entry['date']}  {entry.get('at', '')}")
        print(f"  {entry['brief']}\n")


def main():
    if "--history" in sys.argv:
        return show_history()

    print("=" * 72)
    print("  COLLECTING THE OVERNIGHT PICTURE")
    print("=" * 72)

    if "--debug" in sys.argv:
        # One live call per symbol, printed. Yahoo's v8/chart is the
        # source -- Stooq's quote endpoint 404'd on every variant tried
        # on 2026-07-28 and is simply gone.
        from core.premarket import SOURCES, YAHOO_URL, parse_yahoo, \
            requests_fetcher as rf
        fetch = rf()
        print("\n  Checking every symbol against Yahoo...\n")
        bad = []
        for key, symbol, label, group in SOURCES:
            try:
                quote = parse_yahoo(fetch(symbol))
            except Exception as exc:
                print(f"  [ FAIL ] {label:<16} {symbol:<11} "
                      f"{type(exc).__name__}: {exc}")
                bad.append((label, symbol))
                continue
            if quote is None:
                print(f"  [ FAIL ] {label:<16} {symbol:<11} no usable data")
                bad.append((label, symbol))
            else:
                change = quote.get("change_pct")
                print(f"  [  ok  ] {label:<16} {symbol:<11} "
                      f"{quote['last']:>12,.2f}"
                      f"{'' if change is None else f'  {change:+.2f}%'}")
        print()
        if bad:
            print(f"  {len(bad)} symbol(s) need a different code:")
            for label, symbol in bad:
                print(f"    {label} -- currently {symbol}")
            print()
        else:
            print("  All symbols good.\n")
        return 0

    premarket = PreMarket(fetcher=requests_fetcher())
    collected = premarket.refresh()
    print()
    print(premarket.as_text())

    if collected == 0:
        print("\n  Nothing collected. Check the network and try again.")
        return 1

    if "--brief" not in sys.argv:
        print("  (add --brief for the AI read on these numbers)\n")
        return 0

    print("=" * 72)
    print("  MORNING BRIEF -- AI OPINION")
    print("=" * 72)

    client = anthropic_client()
    if client is None:
        print("\n  ANTHROPIC_API_KEY is not set, so no brief.")
        print("  The numbers above are the useful part regardless.\n")
        return 0

    brief = MorningBrief(client=client)
    text = brief.generate(premarket.as_text())
    if text is None:
        print("\n  No brief today. Nothing was invented to fill the gap.\n")
        return 0

    print()
    for line in text.split(". "):
        line = line.strip()
        if line:
            print(f"  {line}{'' if line.endswith('.') else '.'}")
    print()
    print("  This is an OPINION. Nothing in the bot reads it. It has been")
    print("  recorded so it can be judged in a month --")
    print("  py tools/premarket_brief.py --history")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
