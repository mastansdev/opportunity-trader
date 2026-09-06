"""
==========================================================
Write down which sectors got hit, and by whom
==========================================================

    py tools/record_sector_impact.py [since]

    "it will be recorded in memory that this day this sector is
     impacted by that company & impacted stocks performance on event
     day"                       -- the operator, 6 September 2026

Reads the stored events, finds the ones where a company announced it
was moving into somebody else's business, and records what every
company in that business did that day -- ONE ROW PER STOCK, with its
own numbers, never filed against another stock.

Run after the close. It trades nothing and touches no trading rule;
see core/sector_impact.py for why the side it usually finds cannot be
acted on at all.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from core import sector_impact                             # noqa: E402


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    since = argv[0] if argv else "2026-08-01"

    got = sector_impact.scan(since=since)
    print()
    print(f"  events read            {got['events']:,}")
    print(f"  landed on a sector     {got['impacts']:,}")
    print(f"  company-days recorded  {got['rows']:,}")
    print()

    lines = sector_impact.what_happened()
    if not lines:
        print("  Nothing recorded yet.")
        return 0
    print(f"  {'day':<12}{'who walked in':<13}{'into':<18}"
          f"{'itself':>8}{'incumbents':>12}{'worst':>8}")
    print("  " + "-" * 72)
    for line in lines[:20]:
        itself = line["entrant_move"]
        worst = line["worst"]
        fell = f"{line['fell']} of {line['incumbents']} fell"
        print(f"  {line['day']:<12}{line['entrant'][:12]:<13}"
              f"{line['business'][:17]:<18}"
              f"{(f'{itself:+.2f}%' if itself is not None else '?'):>8}"
              f"{fell:>12}"
              f"{(f'{worst:+.2f}%' if worst is not None else '?'):>8}")
    print()
    print("  One row per stock, each with its own numbers:")
    print("      py -c \"from core import sector_impact as s; "
          "print(s.recall(business='WIRES'))\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
