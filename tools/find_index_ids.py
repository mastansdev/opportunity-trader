"""
==========================================================
NIFTY 50, BANKNIFTY and INDIA VIX -- from Dhan, not guessed
==========================================================
    py tools/find_index_ids.py            show what Dhan lists
    py tools/find_index_ids.py --apply    write them into config.py

    "i want to see NIFTY 50 ; BANK NIFTY ; VIX . first complete this"
                                    -- operator, 3 August 2026

WHY THE TILES WERE BLANK
------------------------
config.INDEX_INSTRUMENTS is {} -- empty. Nothing subscribes to an
index, so every tile reads "needs index feed". The comment above it in
config.py says why it was left that way:

    "Left EMPTY on purpose. A blank tile is honest; a confident number
     for the wrong instrument is not, and guessing these ids has now
     failed twice."

That was the right call and the wrong method. It suggested running a
session, watching for unmapped IDX packets, and identifying each index
BY ITS LEVEL -- Nifty near 24,000, BankNifty near 52,000, VIX 8-20.
That is still guessing; it just guesses later, with more steps, during
market hours.

WHERE THE ANSWER ACTUALLY IS
----------------------------
The same file the bot already downloads to resolve every equity:

    https://images.dhan.co/api-data/api-scrip-master.csv

core/instrument_master.py filters it to SEM_INSTRUMENT_NAME == EQUITY.
The indices are in there too, under a different instrument name, with
their real security ids. Nothing to infer.

WHAT THIS WILL NOT DO
---------------------
Write an id it is not certain of. It matches the trading symbol
exactly, on the NSE index segment, and prints everything it found so
the ids can be checked against a broker screen before anything trades
near them. If a name matches more than one row it refuses that one and
says so.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import sys

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402

CSV = "https://images.dhan.co/api-data/api-scrip-master.csv"

# What the dashboard calls them -> how Dhan spells them. The dashboard
# keys are fixed by dashboard/state.py's _idx() calls; the Dhan side is
# matched case-insensitively and without spaces, because that column is
# not consistent between index families.
WANTED = {
    "nifty":     ("NIFTY 50", "NIFTY"),
    "banknifty": ("NIFTY BANK", "BANKNIFTY"),
    "vix":       ("INDIA VIX", "INDIAVIX"),
    "midcap":    ("NIFTY MIDCAP 100", "NIFTY MID SELECT"),
}


def _norm(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def main(apply=False):
    import pandas as pd

    decision("=" * 70)
    decision("  INDEX SECURITY IDS -- read from Dhan's own scrip master")
    decision("=" * 70)
    decision(f"  Fetching {CSV} ...")
    frame = pd.read_csv(CSV, low_memory=False)
    decision(f"  {len(frame):,} rows.")

    # Everything on NSE that is not an equity. Printed in full below so
    # the shape of this column is visible rather than assumed.
    nse = frame[frame["SEM_EXM_EXCH_ID"] == "NSE"]
    kinds = sorted(set(nse["SEM_INSTRUMENT_NAME"].dropna().astype(str)))
    decision(f"  NSE instrument kinds: {', '.join(kinds)}")

    idx = nse[nse["SEM_INSTRUMENT_NAME"].astype(str)
              .str.upper().str.contains("INDEX", na=False)]
    decision(f"  {len(idx)} index row(s) on NSE.")
    decision("")

    # ---- THE WHOLE MENU FIRST. 3 August 2026. ----
    #
    #     "first you check what dhan gives us & then we decide what we
    #      can use & drop . all possible"
    #
    # He asked for this after catching me writing an id for INDIA VIX
    # that I had invented. A tool that only reports on the four names I
    # thought to look for is the same mistake with more steps: it can
    # only ever confirm my guess, never correct it.
    #
    # So every index Dhan publishes is printed, with its id, before
    # anything is matched. He picks from the list.
    decision("  EVERY INDEX DHAN PUBLISHES ON NSE:")
    decision(f"  {'id':>8}  {'trading symbol':<28} {'name'}")
    decision("  " + "-" * 66)
    listing = idx.sort_values("SEM_TRADING_SYMBOL")
    for _, row in listing.iterrows():
        pretty = row.get("SEM_CUSTOM_SYMBOL") or ""
        decision(f"  {str(row['SEM_SMST_SECURITY_ID']):>8}  "
                 f"{str(row['SEM_TRADING_SYMBOL'])[:28]:<28} {pretty}")
    decision("")
    decision("  Anything on that list can go in INDEX_INSTRUMENTS. The "
             "four below are only")
    decision("  the ones the dashboard already has tiles for.")
    decision("")

    found = {}
    for key, spellings in WANTED.items():
        targets = {_norm(s) for s in spellings}
        hits = idx[idx["SEM_TRADING_SYMBOL"].map(
            lambda v: _norm(v) in targets)]
        if hits.empty:
            hits = idx[idx["SEM_CUSTOM_SYMBOL"].map(
                lambda v: _norm(v) in targets)] \
                if "SEM_CUSTOM_SYMBOL" in idx.columns else hits

        if hits.empty:
            warn(f"  {key:10} NOT FOUND under {spellings}")
            continue
        if len(hits) > 1:
            warn(f"  {key:10} matched {len(hits)} rows -- refusing to "
                 f"choose. Check by hand:")
            for _, row in hits.iterrows():
                warn(f"             id={row['SEM_SMST_SECURITY_ID']} "
                     f"{row['SEM_TRADING_SYMBOL']}")
            continue

        row = hits.iloc[0]
        sec = str(row["SEM_SMST_SECURITY_ID"])
        found[sec] = key
        decision(f"  {key:10} id={sec:>8}   {row['SEM_TRADING_SYMBOL']}")

    decision("")
    if not found:
        warn("  Nothing resolved. The column names may have changed --")
        warn(f"  available columns: {', '.join(map(str, frame.columns))}")
        return

    literal = ("INDEX_INSTRUMENTS = {\n"
               + "".join(f'    "{sec}": "{name}",\n'
                         for sec, name in found.items())
               + "}")
    decision("  What goes in config.py:")
    for line in literal.splitlines():
        decision(f"      {line}")

    if not apply:
        decision("")
        decision("  DRY RUN -- config.py untouched. Re-run with --apply.")
        decision("  Then restart main.py and check the tiles against your")
        decision("  broker screen: Nifty ~24,000, BankNifty ~52,000, VIX 8-20.")
        decision("=" * 70)
        return

    src = open("config.py", encoding="utf-8").read()
    if "INDEX_INSTRUMENTS = {}" not in src:
        warn("  config.INDEX_INSTRUMENTS is already filled in. Not "
             "overwriting it -- edit by hand if these ids are better.")
        return
    open("config.py", "w", encoding="utf-8").write(
        src.replace("INDEX_INSTRUMENTS = {}", literal))
    decision("")
    decision(f"  WRITTEN. {len(found)} index/indices in config.py.")
    decision("  Restart main.py, then CHECK THE TILES against your broker")
    decision("  screen before you trade on anything that reads them.")
    decision("=" * 70)


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
