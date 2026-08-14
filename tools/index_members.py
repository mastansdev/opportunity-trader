"""
Fetch NIFTY 50 and F&O membership from NSE and cache it.

    py tools/index_members.py            refresh if older than 7 days
    py tools/index_members.py --force    refresh no matter what
    py tools/index_members.py --show     just print what is on disk

Run it ONCE, and again after an index review. Membership changes twice
a year; the pre-open window is twelve minutes long. main.py reads the
cache and never fetches during a session.

Without this, the NIFTY 50 and F&O buttons on the pre-open panel do
not appear at all -- which is deliberate. A group whose membership is
unknown is hidden rather than shown filled with the wrong stocks.
"""

import sys

sys.path.insert(0, ".")

from core.index_members import IndexMembers
from core.logger import decision, warn


def main():
    members = IndexMembers()
    status = members.status()

    if "--show" in sys.argv:
        decision(f"[INDEX] On disk as of {status['fetched_at']}: "
                 f"{status['counts'] or 'nothing'}")
        for group in sorted(status["counts"] or {}):
            sample = sorted(members.members(group))[:8]
            decision(f"  {group:<9} {', '.join(sample)} ...")
        return

    if status["counts"] and not status["stale"] and "--force" not in sys.argv:
        decision(f"[INDEX] Already current ({status['fetched_at']}): "
                 f"{status['counts']}. Use --force to fetch anyway.")
        return

    decision("[INDEX] Fetching membership from NSE...")
    members.refresh(force="--force" in sys.argv)
    status = members.status()

    if not status["counts"]:
        warn("[INDEX] Nothing was fetched. NSE blocks unbrowser-like "
             "requests fairly aggressively -- try again in a minute. The "
             "pre-open NIFTY 50 / F&O buttons stay hidden until this "
             "works, which is correct: no list is better than a wrong one.")
        sys.exit(1)

    decision(f"[INDEX] Saved: {status['counts']} (as of {status['fetched_at']}).")
    decision("[INDEX] main.py reads this from disk -- no fetch during "
             "the session.")


if __name__ == "__main__":
    main()
