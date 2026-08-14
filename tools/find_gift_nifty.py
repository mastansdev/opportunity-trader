"""
==========================================================
Does Dhan carry GIFT Nifty? Ask Dhan.
==========================================================

    py tools/find_gift_nifty.py

    "WHAT ? USE DHAN THEY WILL PROVIDE THE INFO"
                                    -- operator, 4 August 2026

He is right. I reached for Yahoo, found no dependable GIFT Nifty feed
there, and stopped -- when the broker the bot is already connected to
publishes a full scrip master with every instrument it can quote.

WHY THIS IS A TOOL AND NOT A GUESS
----------------------------------
GIFT Nifty trades on NSE IX in GIFT City, which is a different
exchange from NSE cash. Whether Dhan carries it, and under which
segment and security id, is a fact about Dhan's master file -- not
something to infer from the name.

The last time I picked an id by reasoning rather than reading, IDX_I 13
(NIFTY 50) and NSE_EQ 13 (ABB INDIA) collided and the index tiles were
wrong all day.

So this searches the live master for anything that looks like it, and
prints what it finds. If it prints nothing, Dhan does not carry it and
the honest answer is that the bot cannot show GIFT Nifty -- not that it
shows something else and calls it GIFT Nifty.

WHAT TO DO WITH THE OUTPUT
--------------------------
Send me the rows. The security id and segment go into
config.INDEX_INSTRUMENTS, the same place NIFTY, BANKNIFTY and VIX
already live, and it arrives on the ribbon with them.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn                     # noqa: E402

# What GIFT Nifty is called, and what it used to be called. SGX Nifty
# became GIFT Nifty in July 2023 when the contracts moved from
# Singapore to NSE IX, and master files often keep the old naming.
NEEDLES = ("GIFT", "SGX", "NIFTY IX", "IX NIFTY", "GIFTNIFTY")

# Columns differ between Dhan's compact and detailed masters, so every
# candidate name is tried rather than assuming one shape.
NAME_KEYS = ("SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "SM_SYMBOL_NAME",
             "SEM_INSTRUMENT_NAME", "tradingSymbol", "symbol", "name")
ID_KEYS = ("SEM_SMST_SECURITY_ID", "securityId", "security_id")
SEG_KEYS = ("SEM_EXM_EXCH_ID", "SEM_SEGMENT", "exchangeSegment", "segment")


def _first(row, keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def main():
    decision("=" * 70)
    decision("  DOES DHAN CARRY GIFT NIFTY?")
    decision("=" * 70)

    # InstrumentMaster keeps a pandas frame and exposes load()/resolve()
    # -- there is no rows(). I wrote rows() from memory and it does not
    # exist, which is the same naming-without-checking habit that has
    # cost this project a day already. Read the frame directly.
    try:
        from core.instrument_master import InstrumentMaster
        master = InstrumentMaster()
        master.load()
        frame = master._df
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Could not load Dhan's scrip master ({exc}).")
        warn("  This needs the same network path main.py uses.")
        return 1

    if frame is None or not len(frame):
        warn("  The master came back empty.")
        return 1

    decision(f"  Searching {len(frame):,} instruments for: "
             f"{', '.join(NEEDLES)}")
    decision("-" * 70)

    hits = []
    columns = [c for c in NAME_KEYS if c in frame.columns]
    for row in frame.to_dict("records"):
        name = ""
        for column in columns:
            value = row.get(column)
            if value not in (None, "") and value == value:      # not NaN
                name = str(value).upper()
                break
        if not name:
            continue
        if any(needle in name for needle in NEEDLES):
            hits.append((name, _first(row, ID_KEYS), _first(row, SEG_KEYS)))

    if not hits:
        warn("  NOTHING FOUND.")
        warn("  Dhan does not appear to carry GIFT Nifty. That is an")
        warn("  answer, not a failure -- the bot will show the world")
        warn("  numbers it CAN verify and stay silent about this one,")
        warn("  rather than putting Nifty spot on screen and labelling")
        warn("  it a leading indicator.")
        return 1

    decision(f"  {'SYMBOL':<38}{'SECURITY ID':<14}SEGMENT")
    for name, security_id, segment in sorted(set(hits))[:40]:
        decision(f"  {name:<38}{security_id:<14}{segment}")

    # ---- THE EXCHANGE IS NOT THE SEGMENT. 4 August 2026. ----
    #
    # The first run printed "GIFTNIFTY 5024 NSE". NSE is the EXCHANGE.
    # Dhan subscribes by SEGMENT -- IDX_I, NSE_EQ, NSE_FNO -- and those
    # are separate id spaces that collide: IDX_I 13 is NIFTY 50 and
    # NSE_EQ 13 is ABB INDIA. Subscribing 5024 to the wrong one would
    # put a completely different instrument on the ribbon labelled GIFT
    # Nifty, and it would look plausible all day.
    #
    # So dump every column for the matches and read the segment off the
    # file instead of reasoning about it.
    decision("")
    decision("  FULL ROW(S) -- the segment has to be read, not guessed")
    decision("-" * 70)
    for row in frame.to_dict("records"):
        name = str(row.get("SEM_TRADING_SYMBOL") or "").upper()
        if not any(needle in name for needle in NEEDLES):
            continue
        for key, value in row.items():
            if value in (None, "") or value != value:      # blank or NaN
                continue
            decision(f"    {key:<34} {value}")
        decision("-" * 70)
    decision("-" * 70)
    decision(f"  {len(set(hits))} match(es). Send these to me -- the id and")
    decision("  segment go into config.INDEX_INSTRUMENTS beside NIFTY.")
    decision("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
