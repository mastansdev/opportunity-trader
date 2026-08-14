"""
==========================================================
Every message, accounted for. No sampling, no assuming.
==========================================================
    py tools/audit_pro_channels.py

    "can u get 100% confirmation that every item we recvd from pro
     channels are tagged with their respective stocks & data memory
     was building around their respective stock?"
                                    -- operator, 2 August 2026

WHAT THIS TOOL CAN AND CANNOT PROVE
-----------------------------------
It CAN prove, over 100% of the stored messages:

    1. COVERAGE   every message either produced an event or was
                  dropped for a NAMED reason -- and the reasons are
                  counted, not summarised.

    2. AGREEMENT  where the publisher tagged the card themselves
                  (#SYMBOL in the caption), whether the symbol we
                  filed it against is the SAME symbol. That is a
                  machine-checkable fact on every such message.

    3. UNREAD     which images have no transcript at all, so nothing
                  in them could have been tagged to anything.

It CANNOT prove that a card with NO publisher tag was filed against
the right company. Nothing can, short of a human reading it. That
population is counted and listed here rather than waved past, because
"we are almost using everything" is the answer that started this.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402
from core.telegram_feed import TelegramFeed                # noqa: E402
from core.stock_events import (                            # noqa: E402
    classify, events_from_message, is_digest,
)

TELEGRAM_DB = ("data/telegram.db", "telegram.db")

# The publisher's own tag. "#HEROMOTOCO", "#M_M", "#HCG_RE".
_TAG = re.compile(r"#([A-Z][A-Z0-9_&]{1,19})\b")

# Words that appear as #hashtags on these channels and are NOT a
# company: the channel's own branding and section labels. Counted
# separately so they cannot be mistaken for an untagged card.
_NOT_A_TAG = {
    "EARNINGS", "RESULTS", "RESULT", "NEWS", "NIFTY", "BANKNIFTY",
    "SENSEX", "IPO", "MARKET", "STOCKS", "STOCK", "Q1", "Q2", "Q3",
    "Q4", "FY26", "FY27", "CONCALL", "BREAKOUT", "ORDERBOOK",
    "INVESTOR", "PRESENTATION", "BRIEF", "UPDATE", "TRADING",
}


def _find(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def caption_tags(text, known):
    """The symbols the PUBLISHER tagged, in caption order.

    Only tags that resolve to a real master symbol count. #COF and
    #M_M are variant spellings of COFORGE and M&M -- real cards, but
    the tag cannot be checked against anything, so they are reported
    as unresolvable rather than as a disagreement.
    """
    hit, unresolved = [], []
    for tag in _TAG.findall(str(text or "").upper()):
        if tag in _NOT_A_TAG:
            continue
        if tag in known:
            if tag not in hit:
                hit.append(tag)
        elif tag not in unresolved:
            unresolved.append(tag)
    return hit, unresolved


def main():
    path = _find(TELEGRAM_DB)
    if path is None:
        warn("No telegram.db found. Nothing to do.")
        return

    loader = MasterLoader()
    loader.load()
    matcher = TelegramFeed(client=None, master_loader=loader,
                           db_path=path, read_images=False)
    known = {s.upper() for s in matcher._known_symbols()}

    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM messages ORDER BY at").fetchall()

    # Per channel: every message falls into exactly ONE bucket.
    bucket = defaultdict(Counter)
    # The three findings that matter.
    disagreed = []          # publisher tagged X, we filed Y
    untagged_filed = []     # no publisher tag, we filed something
    unread_images = []      # photo, no transcript
    unresolved_tags = Counter()

    for row in rows:
        channel = row["channel"] or "?"
        typed = (row["text"] or "").strip()
        read = (row["ocr_text"] or "").strip() if "ocr_text" in row.keys() else ""
        body = (typed + "\n" + read).strip()
        photos = row["photos"] if "photos" in row.keys() else None

        bucket[channel]["messages"] += 1
        if photos:
            bucket[channel]["with an image"] += 1
            if not read:
                bucket[channel]["IMAGE NEVER READ"] += 1
                unread_images.append((channel, row["at"], typed[:70]))

        tagged, unresolved = caption_tags(typed, known)
        for tag in unresolved:
            unresolved_tags[tag] += 1

        events = events_from_message(
            matcher, text=row["text"], ocr_text=read, at=row["at"],
            channel=channel, url=row["url"], grade=row["grade"])

        if not events:
            bucket[channel]["no event"] += 1
            if not body:
                bucket[channel]["  .. nothing to read"] += 1
            elif is_digest(body):
                bucket[channel]["  .. digest, several stories"] += 1
            else:
                symbols = list(dict.fromkeys(
                    matcher.symbols_in(body) + matcher.names_in(body)))
                if len(symbols) >= 3:
                    bucket[channel]["  .. a list, not a story"] += 1
                else:
                    kind, _ = classify(body, grade=row["grade"],
                                       has_symbol=bool(symbols))
                    bucket[channel][f"  .. {kind.lower()}, not an event"] += 1
            # A card the PUBLISHER named, that produced nothing at all,
            # is the loss he is asking about: the data arrived, the
            # company was stated outright, and no memory was built.
            if tagged:
                bucket[channel]["TAGGED BUT NOT FILED"] += 1
            continue

        bucket[channel]["filed"] += 1
        filed = [e["symbol"] for e in events if e.get("scope") == "STOCK"]
        filed = [s for s in filed if s]
        if not filed:
            bucket[channel]["  .. market-wide, no stock"] += 1
            continue

        if tagged:
            wrong = [s for s in filed if s not in tagged]
            if wrong:
                bucket[channel]["FILED AGAINST A DIFFERENT STOCK"] += 1
                disagreed.append((channel, row["at"], tagged, filed,
                                  typed[:70]))
            else:
                bucket[channel]["  .. agrees with the publisher tag"] += 1
        else:
            bucket[channel]["  .. no publisher tag, UNVERIFIABLE"] += 1
            untagged_filed.append((channel, row["at"], filed, typed[:70]))

    # ---------------------------------------------------------------
    line = "=" * 68
    decision(line)
    decision("EVERY PRO MESSAGE, ACCOUNTED FOR")
    decision(line)

    total = sum(b["messages"] for b in bucket.values())
    for channel in sorted(bucket, key=lambda c: -bucket[c]["messages"]):
        b = bucket[channel]
        pct = 100.0 * b["filed"] / max(b["messages"], 1)
        decision("")
        decision(f"{channel}   {b['messages']} messages, "
                 f"{b['filed']} filed ({pct:.0f}%)")
        for key in sorted(b, key=lambda k: (not k.startswith("  "), k)):
            if key in ("messages", "filed"):
                continue
            decision(f"      {b[key]:5}  {key.strip()}"
                     if not key.startswith("  ")
                     else f"        {b[key]:5}  {key.strip()}")

    decision("")
    decision(line)
    decision("THE THREE ANSWERS")
    decision(line)
    ver = sum(b["  .. agrees with the publisher tag"] for b in bucket.values())
    unv = sum(b["  .. no publisher tag, UNVERIFIABLE"] for b in bucket.values())
    bad = sum(b["FILED AGAINST A DIFFERENT STOCK"] for b in bucket.values())
    lost = sum(b["TAGGED BUT NOT FILED"] for b in bucket.values())
    blind = sum(b["IMAGE NEVER READ"] for b in bucket.values())
    decision("")
    decision(f"  {total:5}  messages on file")
    decision(f"  {ver:5}  PROVEN right -- publisher tagged it, we agree")
    decision(f"  {bad:5}  PROVEN WRONG -- publisher tagged it, we disagree")
    decision(f"  {unv:5}  filed, but the publisher never tagged it "
             f"-> cannot be proven either way")
    decision(f"  {lost:5}  publisher tagged a company and we filed NOTHING")
    decision(f"  {blind:5}  images with no transcript at all")

    if disagreed:
        decision("")
        decision("  EVERY DISAGREEMENT (publisher tag -> what we filed):")
        for channel, at, tags, filed, head in disagreed[:60]:
            decision(f"    {str(at)[:16]}  {channel:16} "
                     f"#{'/'.join(tags)} -> {'/'.join(filed)}")
            decision(f"        {head}")
        if len(disagreed) > 60:
            decision(f"    ... and {len(disagreed) - 60} more")

    if unresolved_tags:
        decision("")
        decision("  TAGS THAT ARE NOT MASTER SYMBOLS "
                 "(variant spellings, or stocks we do not carry):")
        for tag, n in unresolved_tags.most_common(30):
            decision(f"    {n:4}  #{tag}")

    if unread_images:
        decision("")
        decision(f"  IMAGES WITH NO TRANSCRIPT ({len(unread_images)}):")
        seen = Counter(c for c, _at, _h in unread_images)
        for channel, n in seen.most_common():
            decision(f"    {n:4}  {channel}")

    decision("")
    decision(line)
    decision("  Nothing was written. This tool only counts.")
    decision(line)


if __name__ == "__main__":
    main()
