"""
==========================================================
What is opening where -- run it at 09:12, before the bell
==========================================================

    py tools/preopen_gaps.py            # your universe only
    py tools/preopen_gaps.py --all      # every stock NSE returns
    py tools/preopen_gaps.py --min 2    # only gaps of 2% or more

NSE fixes each stock's opening price between 09:08 and 09:12. This
reads it. At 09:12 you already know what opens where -- it is a
published fact, not a forecast.

NOT WIRED INTO THE BOT. Reads NSE, prints, writes data/preopen.json.
Touches no position and no order.

WHAT THE COLUMNS MEAN
---------------------
    IEP        the price it will open at
    gap %      IEP against yesterday's close -- NSE's own number
    matched    shares that actually traded in the pre-open
    imbalance  unmatched orders left over, -1.00 to +1.00
               +0.80 means four-fifths of the leftover book is buying

The last two are the ones worth learning to read. A stock opening +4%
on 2,000 matched shares is not the same as one opening +4% on 400,000
with heavy unfilled buying, and every other screen shows them
identically.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.preopen import PreOpen                            # noqa: E402
from core.nse_quotes import requests_fetcher                # noqa: E402
from core.master_loader import MasterLoader                 # noqa: E402


def _n(value, width=10, places=2):
    if value is None:
        return "--".rjust(width)
    return f"{value:,.{places}f}".rjust(width)


def _qty(value, width=12):
    if value is None:
        return "--".rjust(width)
    return f"{value:,.0f}".rjust(width)


def show(title, rows):
    print()
    print(f"  {title}  ({len(rows)})")
    if not rows:
        print("    nothing")
        return
    print(f"    {'symbol':<14}{'IEP':>10}{'gap %':>9}"
          f"{'matched':>12}{'imbalance':>11}")
    for row in rows:
        imbalance = row.get("imbalance")
        mark = ""
        if imbalance is not None:
            if imbalance >= 0.5:
                mark = "  buyers waiting"
            elif imbalance <= -0.5:
                mark = "  sellers waiting"
        print(f"    {row['symbol']:<14}{_n(row['iep'])}"
              f"{_n(row.get('gap_pct'), 9)}{_qty(row.get('matched_qty'))}"
              f"{_n(imbalance, 11)}{mark}")


def main():
    everything = "--all" in sys.argv
    minimum = 1.0
    if "--min" in sys.argv:
        i = sys.argv.index("--min")
        if i + 1 < len(sys.argv):
            try:
                minimum = float(sys.argv[i + 1])
            except ValueError:
                pass

    print("=" * 72)
    print("  NSE PRE-OPEN  --  where the market opens")
    print("=" * 72)

    preopen = PreOpen(fetcher=requests_fetcher())
    collected = preopen.refresh()
    if collected == 0:
        print("\n  Nothing collected.")
        print("  The pre-open session runs 09:00-09:12. Outside that")
        print("  window NSE returns an empty book, which is not an error.\n")
        return 1

    symbols = None
    scope = "every stock NSE returned"
    if not everything:
        try:
            loader = MasterLoader()
            loader.load()
            symbols = loader.all_symbols()
            scope = f"your {len(symbols)} subscribed symbols"
        except Exception as exc:                           # noqa: BLE001
            print(f"\n  Could not read the master list ({exc}) -- "
                  f"showing everything instead.")

    print(f"  {collected} stocks in NSE's pre-open book")
    print(f"  showing {scope}, gaps of {minimum:.1f}% or more")

    up, down, unknown = preopen.gaps(symbols=symbols, minimum_pct=minimum,
                                     top=25)
    show("GAPPING UP", up)
    show("GAPPING DOWN", down)
    # Flat, or a gap NSE published no pChange for -- which happens
    # exactly when it is most interesting, on a stock with no prior
    # close. Counted here rather than printed, because this tool is a
    # quick terminal read; the dashboard shows them in full.
    if unknown:
        print(f"\n  ({len(unknown)} more in the book with no gap % "
              f"published, or opening flat -- all of them are on the "
              f"dashboard's PRE-MARKET tab)")

    print()
    print("  Saved to data/preopen.json.")
    print("  These are opening prices, not signals -- nothing here says")
    print("  a gap is worth trading. That needs evidence we do not have")
    print("  yet, and it is a separate question from knowing the fact.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
