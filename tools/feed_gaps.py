"""
==========================================================
py tools/feed_gaps.py  --  is every channel actually reaching us?
==========================================================

    "i don't know whether every img, data, mesaage is reaching to bot
     or not."
                                -- operator, 10 August 2026

WHAT THIS ANSWERS
-----------------
For each Telegram channel: the newest message we hold, in IST, and how
far behind that is right now. A channel that has gone quiet and a
channel we have stopped reading look identical in the message table;
they do not look identical here.

    py tools/feed_gaps.py            where each channel stands
    py tools/feed_gaps.py --window   the exact catch-up window to pull

THE CLOCK, SETTLED
------------------
data/telegram.db carries two clocks in one table and neither is
labelled in a way code can tell apart:

    messages.at        2026-08-09T16:14:15+00:00     UTC, tagged
    messages.seen_at   2026-08-09T21:46:09           IST, untagged

Measured over 400 messages the gap never fell below 5.51 hours, so the
offset is a clean +5:30 and seen_at is local IST. Everything printed
below is IST, converted through core/feed_clock.py, so no one has to
hold the offset in their head -- which is how core/catalysts.py and
core/supply_events.py each had to learn it separately.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import feed_clock                                    # noqa: E402


def main():
    seeded = feed_clock.backfill()
    now = feed_clock.now_ist()
    rows = feed_clock.gaps(now=now)

    print()
    print("=" * 70)
    print(f"  TELEGRAM FEED  --  now {now:%a %d %b %Y %H:%M} IST")
    print("=" * 70)
    if not rows:
        print("  No channels on record. Has the collector ever run?")
        return 1

    print(f"  {'CHANNEL':<24}{'NEWEST WE HOLD':<16}{'BEHIND':>9}  {'MSGS':>6}")
    print("  " + "-" * 62)
    stale = 0
    for row in rows:
        behind = (f"{row['behind_hours']:.1f} h"
                  if row["behind_hours"] is not None else "never")
        try:
            from core.telegram_feed import _skip_catch_up
            skipped = _skip_catch_up(row["channel"])
        except Exception:                                      # noqa: BLE001
            skipped = False
        if skipped:
            mark = "  (no catch-up -- his call)"
        else:
            mark = "  <-- STALE" if row["stale"] else ""
        if row["stale"] and not skipped:
            stale += 1
        print(f"  {row['channel'][:24]:<24}{row['last_at_ist'] or '-':<16}"
              f"{behind:>9}  {row['messages']:>6}{mark}")

    print()
    if stale:
        print(f"  {stale} of {len(rows)} channels are behind.")
        print("  A quiet channel and an unread channel look the same in the")
        print("  message table. They do not look the same here -- if a")
        print("  channel posts daily and shows 60 hours, it is not quiet.")
    else:
        print(f"  All {len(rows)} channels are current.")

    window = feed_clock.catch_up_window(now=now)
    if window:
        print()
        print(f"  CATCH-UP NEEDED: {window['from_ist']:%a %d %b %H:%M} "
              f"-> {window['to_ist']:%a %d %b %H:%M}  "
              f"({window['hours']:.1f} hours)")
        print("     py tools/collector.py --catchup")
    print("=" * 70)
    if seeded:
        print(f"  (watermark seeded from {seeded} channels already in the "
              f"store)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
