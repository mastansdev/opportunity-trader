"""
==========================================================
Remove the links a company name never earned
==========================================================

    "URBANCO  Rs 900cr  'Afcons secures nearly Rs 900 crore...'"

URBAN COMPANY LIMITED collapsed to URBAN once _NAME_SUFFIX stripped
COMPANY, and the adjective went into the name index. Afcons's own
announcement --

    "bolstering its position in India's URBAN infrastructure sector"

-- was therefore filed as a Rs 900 crore order for Urban Company, on
the panel the operator clicks BUY from.

core/telegram_feed.py is fixed. This removes what the old rule already
wrote.

WHAT THIS DOES NOT DO
---------------------
It does not delete a message, and it does not bulk-dedupe anything.
On 31 July a bulk tool offered to remove a real India-EU FTA story as
a "duplicate" of an unrelated solar item, and was deleted for it.

This re-runs the CURRENT matcher over the messages that carry a
suspect symbol and removes the link only where today's matcher --
which is stricter, and has been checked both ways -- does not produce
it. A message whose text genuinely names the company keeps its link.
Measured before writing anything: 17 tagged, 7 genuine, 10 false.

    py tools/purge_bad_name_links.py            # dry run, default
    py tools/purge_bad_name_links.py --apply

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import sqlite3
import sys

sys.path.insert(0, ".")

from core.master_loader import MasterLoader                # noqa: E402
from core.telegram_feed import NOT_A_NAME, TelegramFeed    # noqa: E402

TELEGRAM_DB = "data/telegram.db"
EVENTS_DB = "data/stock_events.db"


def _matcher():
    loader = MasterLoader()
    loader.load()
    feed = TelegramFeed.__new__(TelegramFeed)
    feed.master_loader = loader
    for attr in ("_name_idx", "_names", "_name_cache",
                 "_symbols", "_symbols_tagged"):
        setattr(feed, attr, None)
    return feed


def suspects(loader=None):
    """The symbols whose name-index entry has just been withdrawn.

    Derived from NOT_A_NAME rather than hardcoded, so adding a word
    there is the only edit needed to re-run this for a new case.
    """
    loader = loader or MasterLoader()
    try:
        loader.load()
    except Exception:                                      # noqa: BLE001
        pass
    out = {}
    for symbol in loader.all_symbols(include_blocked=True):
        record = loader.get_by_symbol(symbol) or {}
        name = str(record.get("COMPANY NAME") or "").upper()
        first = next((w for w in name.split() if len(w) >= 3), "")
        if first in NOT_A_NAME:
            out[symbol] = name
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the changes; default is a dry run")
    args = ap.parse_args()

    feed = _matcher()
    bad = suspects(feed.master_loader)
    if not bad:
        print("Nothing in NOT_A_NAME maps to a company. Nothing to do.")
        return
    print("Symbols whose one-word name entry was withdrawn:")
    for symbol, name in bad.items():
        print(f"   {symbol:12} {name}")
    print()

    conn = sqlite3.connect(TELEGRAM_DB)
    drop_msgs, keep_msgs = [], []
    for symbol in bad:
        rows = conn.execute(
            "SELECT message_id, text, ocr_text, symbols FROM messages "
            "WHERE symbols LIKE ?", (f"%{symbol}%",)).fetchall()
        for mid, text, ocr, stored in rows:
            blob = f"{text or ''}\n{ocr or ''}"
            fresh = set(feed.symbols_in(blob)) | set(feed.names_in(blob))
            listed = [s for s in (stored or "").split(",") if s]
            if symbol not in listed:
                continue
            if symbol in fresh:
                keep_msgs.append((mid, symbol))
            else:
                drop_msgs.append(
                    (mid, symbol, ",".join(s for s in listed if s != symbol)))

    print(f"messages carrying a suspect symbol : "
          f"{len(drop_msgs) + len(keep_msgs)}")
    print(f"   genuinely name the company      : {len(keep_msgs)}  KEPT")
    print(f"   false links to remove           : {len(drop_msgs)}")
    print()

    ev = sqlite3.connect(EVENTS_DB)
    ev_drop = []
    for symbol in bad:
        for eid, head in ev.execute(
                "SELECT id, headline FROM events WHERE symbol = ?",
                (symbol,)).fetchall():
            fresh = set(feed.symbols_in(head or "")) \
                | set(feed.names_in(head or ""))
            if symbol not in fresh:
                ev_drop.append((eid, symbol, (head or "")[:70]))

    print(f"stock_events rows on a suspect symbol : "
          f"{len(ev_drop)} to remove")
    for _, symbol, head in ev_drop[:10]:
        print(f"   {symbol:10} {head}")
    if len(ev_drop) > 10:
        print(f"   ... and {len(ev_drop) - 10} more")
    print()

    if not args.apply:
        print("DRY RUN. Nothing written. Re-run with --apply.")
        return

    for mid, _symbol, remaining in drop_msgs:
        conn.execute("UPDATE messages SET symbols = ? WHERE message_id = ?",
                     (remaining, mid))
    conn.commit()
    for eid, _symbol, _head in ev_drop:
        ev.execute("DELETE FROM events WHERE id = ?", (eid,))
    ev.commit()
    print(f"DONE. {len(drop_msgs)} message links cleared, "
          f"{len(ev_drop)} event rows removed, "
          f"{len(keep_msgs)} genuine links untouched.")


if __name__ == "__main__":
    main()
