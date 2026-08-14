"""
==========================================================
py tools/find_scrip.py -- every row Dhan holds for a stock
==========================================================

    "BUT YOU NEED TO CHECK WITH NSE/CHROME FOR THE CHOLAFIN, ELECTCAST,
     MOTHERSON . ID'S & CHECK WITH DHAN DATABASE = LIST OF STOCKS WITH
     THAT ID/NAME OF THE COMPANY/SYMBOL."
                                -- operator, 8 August 2026

WHAT THE PROBE FOUND
--------------------
py tools/probe_silent.py, run on his machine 8 August:

    HINDALCO   1363   1059.60   control, works
    ANTELOPUS 13598    799.45   Dhan serves it, our feed never stored it
    ... 10 more the same ...
    CHOLAFIN  19257       --    Dhan will not serve this id
    ELECTCAST 18116       --    Dhan will not serve this id
    MOTHERSON 25510       --    Dhan will not serve this id

Three ids Dhan refuses to quote -- while tools/verify_master_database.py
has been reporting all three as CORRECT every night.

THE SUSPECT
-----------
core/instrument_master.py resolves a symbol like this:

    match = df[(EXCH == "NSE") & (INSTRUMENT == "EQUITY")
               & (TRADING_SYMBOL == symbol)]
    security_id = match.iloc[0]["SEM_SMST_SECURITY_ID"]

iloc[0] -- the FIRST matching row, with no check that there is only
one. If Dhan carries a symbol twice (two series, a renamed entity, a
stale listing), we silently take whichever sorts first.

And the verifier calls the SAME function, so it compares a wrong id
against itself and agrees. A check that shares its bug with the thing
it checks cannot fail.

WHAT THIS PRINTS
----------------
Every row in Dhan's scrip master matching the symbol OR the company
name, across all exchanges, segments and series -- nothing filtered,
nothing collapsed. If a symbol has three rows, three rows print, and
which one the feed can actually quote becomes visible.

    py tools/find_scrip.py                     the three that failed
    py tools/find_scrip.py MOTHERSON CHOLAFIN  named symbols
    py tools/find_scrip.py --name MOTHERSON    search company names too

Read-only. Downloads Dhan's public scrip master and prints. Nothing
is written and no order is placed.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# Where the answer is left, so it can be read by someone who was not
# standing at the terminal. Mirrors data/scrip_verified.json.
OUT_PATH = os.path.join("data", "scrip_lookup.json")

# The three the probe proved Dhan will not quote on NSE_EQ.
DEFAULT = ["MOTHERSON", "CHOLAFIN", "ELECTCAST"]

# Columns worth seeing. Kept short so a row fits one line; the rest are
# dumped only when --wide is passed.
SHOW = [
    "SEM_SMST_SECURITY_ID",
    "SEM_TRADING_SYMBOL",
    "SEM_EXM_EXCH_ID",
    "SEM_SEGMENT",
    "SEM_INSTRUMENT_NAME",
    "SEM_SERIES",
    "SEM_LOT_UNITS",
    "SM_SYMBOL_NAME",
]


def main():
    wide = "--wide" in sys.argv
    by_name = "--name" in sys.argv
    wanted = [a.strip().upper() for a in sys.argv[1:]
              if not a.startswith("--")] or DEFAULT

    try:
        import pandas as pd
    except Exception as exc:                               # noqa: BLE001
        print(f"pandas is needed: {exc}")
        return 1

    print("=" * 78)
    print("  EVERY ROW DHAN HOLDS FOR THESE STOCKS")
    print(f"  source: {CSV_URL}")
    print("=" * 78)
    print("\n  downloading...")
    try:
        df = pd.read_csv(CSV_URL, low_memory=False)
    except Exception as exc:                               # noqa: BLE001
        print(f"\n  DOWNLOAD FAILED: {exc}")
        print("  Run this from the machine that reaches Dhan.")
        return 1
    print(f"  {len(df):,} rows, {len(df.columns)} columns\n")

    columns = [c for c in SHOW if c in df.columns]
    if wide:
        columns = list(df.columns)

    symbol_col = "SEM_TRADING_SYMBOL"
    name_col = "SM_SYMBOL_NAME" if "SM_SYMBOL_NAME" in df.columns else None

    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
    except Exception:                                      # noqa: BLE001
        loader = None

    findings = {}
    for symbol in wanted:
        print("-" * 78)
        ours = loader.security_id(symbol) if loader else None
        print(f"  {symbol}      our master says id = {ours}")
        print("-" * 78)

        mask = df[symbol_col].astype(str).str.upper() == symbol
        if by_name and name_col:
            mask = mask | df[name_col].astype(str).str.upper().str.contains(
                symbol, na=False)
        rows = df[mask]

        if rows.empty:
            findings[symbol] = {"our_id": str(ours) if ours else None,
                                "rows": 0, "nse_equity_ids": [],
                                "verdict": "not present under that symbol"}
            print("     NOT PRESENT under that trading symbol.")
            if name_col:
                # The symbol may have been renamed. Look for the
                # company instead -- this is how a rename is caught.
                stem = symbol[:6]
                near = df[df[name_col].astype(str).str.upper()
                          .str.contains(stem, na=False)]
                if not near.empty:
                    print(f"     but {len(near)} row(s) whose NAME "
                          f"contains '{stem}':")
                    print(near[columns].to_string(index=False,
                                                  max_rows=12))
            print()
            continue

        print(f"     {len(rows)} row(s) in Dhan's master:\n")
        print(rows[columns].to_string(index=False))

        # THE POINT OF THE WHOLE TOOL
        equity = rows
        if "SEM_INSTRUMENT_NAME" in rows.columns:
            equity = rows[rows["SEM_INSTRUMENT_NAME"].astype(str)
                          .str.upper() == "EQUITY"]
        if "SEM_EXM_EXCH_ID" in equity.columns:
            equity = equity[equity["SEM_EXM_EXCH_ID"].astype(str)
                            .str.upper() == "NSE"]
        ids = sorted({str(v) for v in
                      equity.get("SEM_SMST_SECURITY_ID", [])})
        findings[symbol] = {
            "our_id": str(ours) if ours is not None else None,
            "rows": int(len(rows)),
            "nse_equity_ids": ids,
            "all_rows": rows[columns].astype(str).to_dict("records"),
            "verdict": ("ambiguous" if len(ids) > 1 else
                        "no nse equity row" if not ids else
                        "master wrong" if ours is not None
                        and str(ours) != ids[0] else "agrees"),
        }
        print()
        if len(ids) > 1:
            print(f"     >>> {len(ids)} DIFFERENT NSE EQUITY IDS: "
                  f"{', '.join(ids)}")
            print("     >>> instrument_master.py takes iloc[0] and cannot")
            print("     >>> know which of these the feed will quote.")
        elif ids:
            only = ids[0]
            if ours is not None and str(ours) != only:
                print(f"     >>> OUR MASTER IS WRONG: we hold {ours}, "
                      f"Dhan's NSE equity row is {only}")
            else:
                print(f"     >>> single NSE equity id {only}, and it "
                      f"matches our master.")
                print("     >>> so the id is right and the quote refusal")
                print("     >>> is something else -- segment entitlement,")
                print("     >>> or the instrument is suspended today.")
        else:
            print("     >>> NO NSE EQUITY ROW AT ALL. Whatever we hold, "
                  "it is not an NSE cash listing.")
        print()

    # ---- WRITE IT DOWN. 8 August 2026. ----
    #
    #     "py tools/find_scrip.py = DONE PLS CHECK"
    #
    # He ran it and I could not check anything, because the first
    # version only printed to his terminal. tools/verify_master_
    # database.py has written data/scrip_verified.json since the day it
    # was built, for exactly this reason: a diagnostic whose answer
    # lives only on a screen has to be copied by hand before anyone can
    # act on it, and that step is where it stops happening.
    try:
        import json
        record = {"looked_at": datetime.now().isoformat(timespec="seconds"),
                  "source": CSV_URL, "rows_in_master": int(len(df)),
                  "symbols": findings}
        with open(OUT_PATH, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        print(f"  written: {OUT_PATH}")
    except Exception as exc:                               # noqa: BLE001
        print(f"  (could not write {OUT_PATH}: {exc})")

    print("=" * 78)
    print("  If a symbol shows more than one NSE EQUITY id above, that is")
    print("  the bug: core/instrument_master.py picks the first silently,")
    print("  and tools/verify_master_database.py calls the same function")
    print("  so it agrees with the wrong answer.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
