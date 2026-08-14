"""
==========================================================
Read the pictures already in telegram.db
==========================================================
    py tools/telegram_ocr.py                 dry run, first 10
    py tools/telegram_ocr.py --all           dry run, every image
    py tools/telegram_ocr.py --apply         read and store

WHY
---
30 July 2026:

    "Day Trader Telugu posts all important news in live markets. NONE of
     them are being used by bot. WHY?"

Because 77 of that channel's 90 stored messages have no text at all --
the news is inside a forwarded screenshot, and the bot had no way to
read one. core/image_text.py gives it one. The poller now reads new
images as they arrive; this reads the ones already on disk.

    "all images are english only that too taken from X , or any other
     reliable sources only"

That is the easy case for OCR and the reason this is worth doing: black
text, white card, large type, no handwriting.

WHAT IT DOES NOT DO
-------------------
It does not touch the `text` column. A transcript goes to `ocr_text`,
so it stays possible to tell what a human typed from what a machine
read off a picture. Symbols found in a transcript are ADDED to the
symbols column, never substituted for what is already there.

A CAUTION WORTH READING
-----------------------
Telegram's CDN links expire. Images from months ago may simply 404 --
that is not a failure of the reader, and the summary counts it
separately so the two cannot be confused.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, ".")

from core import image_text                                # noqa: E402
from core.logger import decision, warn                     # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402
from core.telegram_feed import NOT_A_MENTION               # noqa: E402

DB_CANDIDATES = ("data/telegram.db", "telegram.db")
HASHTAG = re.compile(r"#([A-Za-z][A-Za-z0-9&\-]{1,})")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9&\-]{2,}")


def _db():
    for path in DB_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def symbols_for(text, tagged, plain):
    """Same rules as everywhere else. A picture earns no extra trust.

    Capitals for a bare word, because a lowercase "dollar" is currency
    and an uppercase "DOLLAR" is a textiles company -- and OCR of a news
    card produces plenty of ordinary lowercase prose.
    """
    found = []
    for tag in HASHTAG.findall(text or ""):
        upper = tag.upper()
        if upper in tagged and upper not in found:
            found.append(upper)
    for token in WORD.findall(text or ""):
        if token != token.upper():
            continue
        if token in plain and token not in found:
            found.append(token)
    return found


def main(apply=False, every=False):
    path = _db()
    if path is None:
        warn("No telegram.db found. Nothing to do.")
        return

    if not image_text.available():
        warn("No image reader available.")
        warn("  " + image_text.why_unavailable())
        return
    decision(f"[OCR] Reader: {image_text.backend()}")

    loader = MasterLoader()
    loader.load()
    try:
        known = {s.strip().upper()
                 for s in loader.all_symbols(include_blocked=True)}
    except TypeError:
        known = {s.strip().upper() for s in loader.all_symbols()}
    tagged = {s for s in known if s not in NOT_A_MENTION}
    plain = {s for s in tagged if len(s) >= 3}

    # Run the schema migration BEFORE querying. 30 July 2026: this tool
    # opens sqlite directly, so the ocr_text column -- which is added by
    # TelegramFeed._migrate() when the bot starts -- did not exist yet
    # and the first real run died on "no such column: ocr_text".
    #
    # Constructing the feed is what performs the migration, and using it
    # here keeps ONE definition of the schema. A second ALTER TABLE
    # written into this file would be a second source of truth, and the
    # two would drift.
    try:
        from core.telegram_feed import TelegramFeed
        TelegramFeed(client=None, db_path=path)
    except Exception as exc:                               # noqa: BLE001
        warn(f"[OCR] Could not migrate the database ({exc}).")
        return

    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select rowid, channel, at, text, symbols, photos, ocr_text "
        "from messages where trim(coalesce(photos,'')) <> '' "
        "and trim(coalesce(ocr_text,'')) = '' "
        "order by at desc").fetchall()

    if not rows:
        decision("[OCR] Nothing to read -- every stored image already "
                 "has a transcript.")
        con.close()
        return

    todo = rows if (every or apply) else rows[:10]
    decision(f"[OCR] {len(rows)} images with no transcript. "
             f"Reading {len(todo)}.")

    read_ok = blank = 0
    reasons = {}
    updates = []
    for row in todo:
        url = (row["photos"] or "").splitlines()[0]
        data, reason = image_text.fetch_with_reason(url)
        if data is None:
            # Counted BY REASON. "gone 10" was true and useless -- an
            # expired link and a machine that cannot reach Telegram at
            # all look identical under one counter.
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        text = image_text.read(data)
        if not text:
            blank += 1
            continue
        read_ok += 1
        before = [s for s in (row["symbols"] or "").split(",") if s.strip()]
        found = symbols_for(text, tagged, plain)
        merged = before + [s for s in found if s not in before]
        updates.append((row["rowid"], text, ",".join(merged)))
        decision(f"  [{row['channel']}] {row['at'][:16]}")
        for line in text.splitlines()[:4]:
            decision(f"      {line[:96]}")
        if merged != before:
            decision(f"      -> symbols: {', '.join(merged)}")

    decision("")
    decision(f"  read      {read_ok}")
    decision(f"  no text   {blank}   (a chart or a logo, nothing to match)")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        decision(f"  not read  {count}   {reason}")
    if any("unreachable" in str(r) for r in reasons):
        warn("  Every failure above is a NETWORK failure, not an expired "
             "link and not a reader problem. This machine cannot reach "
             "Telegram's image CDN (cdn*.telesco.pe). Check a proxy, a "
             "firewall, or a VPN.")

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing written. Re-run with --apply.")
        con.close()
        return

    for rowid, text, symbols in updates:
        con.execute("update messages set ocr_text=?, symbols=? where rowid=?",
                    (text, symbols, rowid))
    con.commit()
    con.close()
    decision("")
    decision(f"  DONE. {len(updates)} transcripts stored.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv, every="--all" in sys.argv)
