"""
==========================================================
Every stored event, against the caption it came from
==========================================================
    py tools/audit_event_tags.py            report only
    py tools/audit_event_tags.py --apply    re-file / remove

    "after checking make sure every results, our chips, news, orders
     any other things each are tagged/linked to their own stocks & no
     lapse or swapping of results, investor presentations or mainly
     in order pulse."
                                    -- operator, 2 August 2026

THE RULE, AND WHY IT IS THE PUBLISHER'S AND NOT OURS
----------------------------------------------------
Every card on the six Pulse channels names its company in the caption.
Measured over the whole store on 2 August:

    Earnings 360      431 of 432 messages
    Breakouts         200 of 200
    Business Pulse    109 of 110
    OrderBook Pulse   102 of 110
    Earnings Pulse    370 of 430   (the rest are recaps and chat)
    Earnings Pro      441 of 537   (the rest are paginated reports)

So for those messages there is nothing to infer. The body of a card
names customers, plants, subsidiaries, peers and brokers -- STEAG and
Foundit appear in four of BLUSPRING's fifteen findings -- and none of
them is the company the card is about.

WHAT THIS TOOL LOOKS FOR
------------------------
For every stored event it finds the message it came from and asks one
question: does the symbol we filed it against match what the publisher
tagged? Three outcomes, and only one of them is a fault:

    AGREES      the tag and the row name the same company
    NO TAG      the message never named one (Day Trader Telugu, most
                of News Pulse) -- left alone, and counted
    DISAGREES   the publisher said X and the row says Y

ORDERBOOK PULSE FIRST
---------------------
He named it specifically, and he is right to. An ORDER event carries
value_cr, and a Rs 2,205cr win filed against the wrong company puts
the largest chip on the panel beside a stock that won nothing. That is
the most expensive single mis-tag this bot can make.

NOTHING IS DELETED WITHOUT A NAME
---------------------------------
An earlier sweep offered to remove 184 rows and 65 of them were not
mis-tags at all -- the tag was a VARIANT SPELLING of the same company
(#M_M for M&M, #COF for COFORGE, #HCG_RE for HCG). Deleting those
would have destroyed real events. So a row is only touched when the
caption tag resolves to a DIFFERENT REAL master symbol, and every
affected row is printed before anything happens.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402
from core.telegram_feed import TelegramFeed                # noqa: E402
from core.stock_events import symbols_first                # noqa: E402

TELEGRAM_DB = ("data/telegram.db", "telegram.db")
EVENTS_DB = ("data/stock_events.db", "stock_events.db")

# The kinds that belong to ONE company. A MACRO or MARKET_ANSWER row
# is market-wide by construction and has no caption company to check.
PER_STOCK = ("RESULT", "ORDER", "NEWS", "CONCALL", "FILING",
             "EXPECTATION", "REPORTED", "AI_VERDICT", "FLOW", "SETUP")


def _find(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def main(apply=False):
    tg, ev = _find(TELEGRAM_DB), _find(EVENTS_DB)
    if not tg or not ev:
        warn("Need both telegram.db and stock_events.db.")
        return

    loader = MasterLoader()
    loader.load()
    matcher = TelegramFeed(client=None, master_loader=loader,
                           db_path=tg, read_images=False)

    con = sqlite3.connect(tg)
    con.row_factory = sqlite3.Row
    # The CAPTION only. The OCR of the picture is prose about the
    # company; the caption is the publisher naming it.
    caption = defaultdict(list)
    for row in con.execute("SELECT channel, at, text FROM messages"):
        caption[(row["channel"], str(row["at"]))].append(row["text"] or "")
    con.close()

    con = sqlite3.connect(ev)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM events")]
    con.close()

    tally = Counter()
    by_channel = defaultdict(Counter)
    wrong = []

    for row in rows:
        kind = row["kind"]
        symbol = (row["symbol"] or "").upper()
        source = row["source"] or ""
        if kind not in PER_STOCK or not symbol:
            tally["not a single-stock row"] += 1
            continue

        texts = caption.get((source, str(row["at"])), [])
        if not texts:
            tally["no source message on file"] += 1
            by_channel[source]["unmatched"] += 1
            continue

        subjects = {s for s in
                    (symbols_first(matcher, t) for t in texts) if s}
        if not subjects:
            tally["publisher never named a company"] += 1
            by_channel[source]["no tag"] += 1
            continue

        if symbol in subjects:
            tally["AGREES with the caption"] += 1
            by_channel[source]["agrees"] += 1
        else:
            tally["DISAGREES with the caption"] += 1
            by_channel[source]["DISAGREES"] += 1
            wrong.append((row, sorted(subjects)))

    line = "=" * 70
    decision(line)
    decision(f"EVERY STORED EVENT vs THE PUBLISHER'S OWN TAG "
             f"({len(rows)} rows)")
    decision(line)
    decision("")
    for why, n in tally.most_common():
        decision(f"  {n:5}  {why}")

    decision("")
    decision("  by channel:")
    decision(f"      {'channel':20}{'agrees':>8}{'no tag':>8}"
             f"{'DISAGREES':>11}{'unmatched':>11}")
    for channel in sorted(by_channel, key=lambda c: -by_channel[c]["DISAGREES"]):
        b = by_channel[channel]
        decision(f"      {channel:20}{b['agrees']:8}{b['no tag']:8}"
                 f"{b['DISAGREES']:11}{b['unmatched']:11}")

    if not wrong:
        decision("")
        decision("  No row disagrees with its caption.")
        return

    # ORDER first: he named OrderBook Pulse, and a misplaced order
    # value is the biggest chip on the panel.
    wrong.sort(key=lambda w: (w[0]["kind"] != "ORDER", w[0]["kind"]))
    decision("")
    decision(line)
    decision(f"  {len(wrong)} ROWS FILED AGAINST A COMPANY THE PUBLISHER "
             f"DID NOT NAME")
    decision(line)
    kinds = Counter(r["kind"] for r, _ in wrong)
    for kind, n in kinds.most_common():
        decision(f"    {n:5}  {kind}")
    decision("")
    for row, subjects in wrong[:80]:
        value = f" Rs {row['value_cr']:,.0f}cr" if row["value_cr"] else ""
        decision(f"    id={row['id']:<6} {row['kind']:12} "
                 f"stored={row['symbol']:<12} caption={'/'.join(subjects)}"
                 f"{value}")
        decision(f"        {str(row['at'])[:16]}  {row['source']}")
        decision(f"        {(row['headline'] or '')[:96]}")
    if len(wrong) > 80:
        decision(f"    ... and {len(wrong) - 80} more")

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing changed. Re-run with --apply.")
        return

    # RE-FILE, do not delete.
    #
    # The event is real; only the symbol on it is wrong. Moving it is
    # strictly better than removing it: the company that actually won
    # the order gets its chip, and no true event is lost. The unique
    # index is on (symbol, at, kind, headline), so a move can collide
    # with a row that is already correct -- in which case the duplicate
    # is what gets removed, not the original.
    # ---- ONE CARD, ONE CAPTION. A DIGEST IS NEITHER. ----
    #
    # News Pulse packs several stories into one message, each with its
    # own hashtag: "MORNING PULSE (Part 1/5)" carries five. The caption
    # of such a message does not name A subject, so "the row disagrees
    # with its caption" is not evidence of anything there -- 10 of the
    # 18 disagreements are that shape, and moving them would file a
    # Nifty close against whichever company was tagged first.
    #
    # The card channels send one card about one company. Only those
    # are touched.
    ONE_CARD = ("Earnings 360", "Earnings Pulse", "Earnings Pro",
                "Business Pulse", "OrderBook Pulse", "Breakouts 🇮🇳")
    moved = dropped = skipped = 0
    con = sqlite3.connect(ev)
    for row, subjects in wrong:
        if len(subjects) != 1:
            continue                       # two candidates is not an answer
        if (row["source"] or "") not in ONE_CARD:
            skipped += 1
            continue
        target = subjects[0]
        try:
            con.execute("UPDATE events SET symbol=? WHERE id=?",
                        (target, row["id"]))
            moved += 1
        except sqlite3.IntegrityError:
            con.execute("DELETE FROM events WHERE id=?", (row["id"],))
            dropped += 1
    con.commit()
    con.close()
    decision("")
    decision(f"  DONE. {moved} rows re-filed against the caption company, "
             f"{dropped} removed as duplicates of a correct row.")
    if skipped:
        decision(f"  {skipped} left alone -- a digest channel has no single "
                 f"caption company.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
