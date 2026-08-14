"""
==========================================================
Re-link stored Telegram messages to their stocks
==========================================================
    py tools/telegram_resymbol.py            dry run
    py tools/telegram_resymbol.py --apply    rewrite

WHY THIS EXISTS
---------------
30 July 2026. The operator asked why four Telegram channels the bot
polls all day were not being used:

    "hey we have telegram channel called earnings pulse which will post
     almost instant result & we are not utilising that at all"

Part of the answer was a bug. 79 of 368 stored messages displayed a
#TICKER and had an EMPTY symbols column, so nothing downstream could
find them -- telegram.for_symbol() reads that column, and it is what
the stock card's Telegram section and every per-stock lookup use.

    #ACMESOLAR - Excellent Results        ->  symbols: (empty)
    #QUESS     - Good Results             ->  symbols: (empty)
    L&T secures mega order ... #LT        ->  symbols: (empty)

Two causes, both in _known_symbols():

  * all_symbols() returns the SUBSCRIBED list (668 of 973), so the 305
    blocked stocks were invisible. "May the bot trade this" and "does
    the bot know what this is" are different questions.
  * the >= 3 character floor was applied to hashtags as well as to
    prose, so an explicit "#LT" was discarded.

Both are fixed in core/telegram_feed.py. This backfills the messages
already on disk, which the fix alone does not touch.

Nothing is deleted. Symbols are only ADDED to rows that have none or
that gain one -- no existing link is removed.
==========================================================
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, ".")

from core.master_loader import MasterLoader                # noqa: E402
from core.telegram_feed import NOT_A_MENTION               # noqa: E402
from core.logger import decision, warn                     # noqa: E402

DB_CANDIDATES = ("data/telegram.db", "telegram.db")
HASHTAG = re.compile(r"#([A-Za-z][A-Za-z0-9&\-]{1,})")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9&\-]{2,}")


def _db():
    for path in DB_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def symbols_for(text, tagged, plain):
    """Hashtags first (explicit), then CASE-SENSITIVE word matches.

    The case rule is the whole difference between a ticker and a word.
    Caught on the first dry run:

        "Following the Hugging Face breach, OpenAI reported that ...
         dollar ..."                            -> tagged DOLLAR

    DOLLAR is a real NSE ticker (Dollar Industries, textiles). It is
    also an ordinary English word, and matching it case-insensitively
    put a textiles company on a story about an AI security breach.

    Tickers are written in capitals. A lowercase "dollar" is currency;
    an uppercase "DOLLAR" is the company. Requiring the capitals costs
    nothing real -- every channel here writes tickers as #TAGS or in
    caps -- and it removes a whole class of false link without needing
    a blocklist that would have to grow forever.
    """
    found = []
    for tag in HASHTAG.findall(text or ""):
        upper = tag.upper()
        if upper in tagged and upper not in found:
            found.append(upper)
    for token in WORD.findall(text or ""):
        if token != token.upper():          # not written as a ticker
            continue
        if token in plain and token not in found:
            found.append(token)
    return found


def main(apply=False):
    path = _db()
    if path is None:
        warn("No telegram.db found. Nothing to do.")
        return

    loader = MasterLoader()
    total = loader.load()
    try:
        known = {s.strip().upper()
                 for s in loader.all_symbols(include_blocked=True)}
    except TypeError:
        known = {s.strip().upper() for s in loader.all_symbols()}
    if not known:
        warn("The master file produced no symbols -- refusing to run.")
        return
    tagged = {s for s in known if s not in NOT_A_MENTION}
    plain = {s for s in tagged if len(s) >= 3}
    decision(f"[RESYMBOL] Master: {total} rows, {len(tagged)} usable symbols "
             f"({len(tagged) - len(plain)} of them shorter than 3 chars, "
             f"hashtag-only).")

    # ---- THE TRANSCRIPT COUNTS TOO. 1 August 2026. ----
    #
    # This read row["text"] only. Most results cards ARE the picture --
    # the caption is a line and the numbers are in the image -- so
    # every symbol named only inside a card was invisible to this pass.
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    columns = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
    has_ocr = "ocr_text" in columns
    rows = con.execute(
        "select rowid, channel, text, symbols"
        + (", ocr_text" if has_ocr else "")
        + " from messages").fetchall()

    # ---- A CARD LABEL IS NOT A COMPANY. 1 August 2026. ----
    #
    #     symbols = DLINKINDIA, DLINKINDIA, CLEAN
    #
    # because the card prints "EARNINGS QUALITY | CLEAN" and CLEAN is
    # Clean Science's real ticker, in capitals, so every guard passed
    # it. 140 stored messages carried that tag.
    #
    # The ADD-ONLY rule below is right for the bug this tool was
    # written for -- recovering a link that a later edit removed -- and
    # exactly wrong for this one, which needs a symbol taken AWAY. So
    # the removal is deliberately narrow: a symbol is dropped only when
    # it disappears once the card's own labels are stripped, and stays
    # if it is named anywhere else in the message. That cannot lose a
    # true link, because a true mention survives the strip.
    from core.stock_events import _for_matching

    def _label_artifacts(body):
        if not body:
            return set()
        with_label = set(symbols_for(body, tagged, plain))
        without = set(symbols_for(_for_matching(body), tagged, plain))
        return with_label - without

    changes, gained, dropped = [], 0, 0
    for row in rows:
        before = [s for s in (row["symbols"] or "").split(",") if s.strip()]
        text = row["text"] or ""
        ocr = (row["ocr_text"] if has_ocr else None) or ""
        body = (text + "\n" + ocr).strip()

        after = symbols_for(_for_matching(body), tagged, plain)
        artifacts = _label_artifacts(body)

        # ADD ONLY, except for a proven label artifact. A symbol already
        # stored stays, whatever this pass thinks -- it may have come
        # from a hashtag this text no longer carries, and losing a true
        # link to fix a missing one is a bad trade.
        #
        # DEDUPED, 1 August 2026. The column really does hold
        # "DLINKINDIA,DLINKINDIA" -- a card hashtagged twice, stored
        # twice. It means nothing extra, and downstream it broke the
        # news table's own de-duplication, because ('X',) and ('X','X')
        # are different tuples.
        merged, seen = [], set()
        for symbol in list(before) + list(after):
            if symbol in artifacts or symbol in seen:
                continue
            seen.add(symbol)
            merged.append(symbol)
        if merged != before:
            removed = [s for s in before if s not in merged]
            changes.append((row["rowid"], row["channel"],
                            (text or ocr)[:58], before, merged))
            gained += len([s for s in merged if s not in before])
            dropped += len(removed)

    decision(f"[RESYMBOL] {len(rows)} messages, {len(changes)} would change, "
             f"{gained} symbols recovered, {dropped} label artifacts removed.")
    for rowid, channel, text, before, after in changes[:25]:
        added = [s for s in after if s not in before]
        removed = [s for s in before if s not in after]
        decision(f"  [{channel:18}] {' '.join(str(text).split())[:56]}")
        if added:
            decision(f"      + {', '.join(added)}")
        if removed:
            decision(f"      - {', '.join(removed)}   (card label, not a "
                     f"company)")
    if len(changes) > 25:
        decision(f"  ... and {len(changes) - 25} more")

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing written. Re-run with --apply.")
        con.close()
        return

    for rowid, _c, _t, _b, after in changes:
        con.execute("update messages set symbols=? where rowid=?",
                    (",".join(after), rowid))
    con.commit()
    linked = con.execute(
        "select count(*) from messages where trim(coalesce(symbols,'')) <> ''"
    ).fetchone()[0]
    con.close()
    decision("")
    decision(f"  DONE. {linked} of {len(rows)} messages now carry a symbol.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
