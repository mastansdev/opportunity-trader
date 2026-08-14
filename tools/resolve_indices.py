"""
Find the real Dhan security IDs for NIFTY, BANKNIFTY and INDIA VIX.

    py tools/resolve_indices.py

WHY THIS EXISTS
---------------
config.INDEX_INSTRUMENTS is `{}` -- empty. The index feed therefore
subscribes to nothing, and NIFTY / BANKNIFTY / VIX have shown "needs
index feed" in every session there has ever been. That is not a
display bug: the bot never asked for them.

The fix is three security IDs. They are NOT hardcoded here from
memory on purpose. An index is sent by ID exactly like a stock, and
the same rule applies: a wrong ID silently subscribes to something
else and the dashboard confidently displays the wrong market. This
reads Dhan's own scrip master and prints what it actually finds, for
you to paste in and check.

Indices live in the IDX_I segment, not NSE_EQ.
"""

import sys

sys.path.insert(0, ".")

from core.logger import decision, warn

# What to look for. Matched loosely against the scrip master's own
# names, then printed for the operator to confirm -- never guessed at.
WANTED = {
    "nifty": ("NIFTY 50", "NIFTY50"),
    "banknifty": ("NIFTY BANK", "BANKNIFTY"),
    "midcap": ("NIFTY MIDCAP 100", "MIDCPNIFTY", "NIFTY MID SELECT"),
    "vix": ("INDIA VIX", "INDIAVIX"),
}


def main():
    import pandas as pd
    from core.instrument_master import COMPACT_CSV_URL

    decision(f"Reading Dhan's scrip master from {COMPACT_CSV_URL} ...")
    try:
        df = pd.read_csv(COMPACT_CSV_URL, low_memory=False)
    except Exception as exc:                               # noqa: BLE001
        warn(f"Could not download the scrip master: {exc}")
        sys.exit(1)

    cols = {c.upper(): c for c in df.columns}
    name_col = cols.get("SEM_TRADING_SYMBOL") or cols.get("SEM_CUSTOM_SYMBOL")
    id_col = cols.get("SEM_SMST_SECURITY_ID")
    seg_col = cols.get("SEM_EXM_EXCH_ID") or cols.get("SEM_SEGMENT")
    if not name_col or not id_col:
        warn(f"Unexpected scrip-master columns: {list(df.columns)[:12]}")
        sys.exit(1)

    # Indices only -- an equity with a similar name must not match.
    inst = cols.get("SEM_INSTRUMENT_NAME")
    if inst:
        df = df[df[inst].astype(str).str.upper().str.contains("INDEX", na=False)]

    decision("")
    found = {}
    for key, needles in WANTED.items():
        hits = df[df[name_col].astype(str).str.upper().isin(
            [x.upper() for x in needles])]
        if hits.empty:                       # fall back to a contains match
            pattern = "|".join(needles)
            hits = df[df[name_col].astype(str).str.upper()
                      .str.contains(pattern, na=False, regex=True)]
        if hits.empty:
            warn(f"  {key:<11} NOT FOUND -- tried {needles}")
            continue
        for _, row in hits.head(3).iterrows():
            decision(f"  {key:<11} id={row[id_col]:<10} "
                     f"{row[name_col]:<24} "
                     f"{row[seg_col] if seg_col else ''}")
        found[key] = hits.iloc[0][id_col]

    if not found:
        warn("Nothing resolved. Do not guess -- check the column names "
             "above against the file.")
        sys.exit(1)

    decision("")
    decision("=" * 66)
    decision("  CHECK THE NAMES ABOVE FIRST, then put this in config.py:")
    decision("=" * 66)
    decision("INDEX_INSTRUMENTS = {")
    for key, sid in found.items():
        decision(f'    "{key}": "{sid}",')
    decision("}")
    decision("")
    decision("  Then restart main.py and confirm on the dashboard that")
    decision("  each index shows a LIVE number, not 'needs index feed'.")
    decision("  If one stays dead, dashboard/state.py's index_missing")
    decision("  will name it -- a wrong id looks like a wrong id there,")
    decision("  not like a dead market.")


if __name__ == "__main__":
    main()
