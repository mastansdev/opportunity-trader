"""
==========================================================
py tools/prove_entry_path.py  --  did the fix actually work
==========================================================

    "whats the reason we started the bot?"   -- operator, 11 Aug 2026

To make money. And on 11 August, at 14:50, I found that the entry path
had never once been handed a candidate:

    dashboard/state.py    row.get("day_open")
    core/ranker.py        writes that field as "open"

day_open was None on every row, core/select.py answered "no price",
and the entry-rules loop dropped 100% of the ranker's output. Every
cycle. Every session. Nothing raised, nothing logged -- it simply
looked like a market where nothing ever qualified.

WHY THIS FILE EXISTS AND NOT JUST A UNIT TEST
---------------------------------------------
A unit test proves the code does what I wrote. It does not prove the
number he cares about, which is: HOW MANY REAL STOCKS, ON A REAL DAY,
now reach the entry path that did not before.

So this replays the actual tape -- the gainers off his own running
dashboard at 15:09 on 11 August 2026 -- through both the broken call
and the fixed one, and prints the two counts side by side.

    py tools/prove_entry_path.py

Author : H&M Opportunity Trader
==========================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The real tape. symbol, ltp, open, high, low, prev_close, volume, chg%
# Copied from http://127.0.0.1:8000/api/snapshot at 15:09, 11 Aug 2026.
TAPE = """
CHENNPETRO,1422,1249,1449,1237,1240.1,16290569,14.67
FINCABLES,1210.85,1070,1224.5,1052.65,1058.05,7331950,14.44
MRPL,180.6,163,181.38,161.2,162.96,52052522,10.82
GLAND,2924.6,2845.5,2988.4,2808,2667.3,8450983,9.65
KSHINTL,979.25,973.05,1045.5,933.25,900.6,3251596,8.73
ENTERO,1423.6,1363.9,1439,1328.3,1315.1,563686,8.25
OMNI,597.95,561.6,608.8,548.25,552.85,9272000,8.16
SUNDRMFAST,1211.7,1200,1226,1177,1121.3,967907,8.06
NILKAMAL,1864.8,1725.8,1874.6,1721,1731.3,122306,7.71
AARTIPHARM,885.3,848.9,932.6,826.2,823,14365477,7.57
VRLLOG,305.4,284.5,310,284.5,284.9,1760459,7.2
ZYDUSLIFE,1197.7,1119,1205,1117.6,1119,8016320,7.03
DEVYANI,142.87,133.56,144.7,132.76,133.56,23459909,6.97
SAPPHIRE,235.97,220.5,237.79,219.57,220.62,11911895,6.96
POLICYBZR,1729.8,1620,1747,1618,1630,3020025,6.12
NAUKRI,1359.1,1297,1391,1291.1,1282,9816927,6.01
LUMAXIND,5995,5700,6090,5661.5,5655.5,94990,6
SEDEMAC,3078.9,2945,3089,2900,2908.3,295556,5.87
"""


def rows():
    out = []
    for line in TAPE.strip().splitlines():
        bits = line.split(",")
        out.append({
            "symbol": bits[0],
            "ltp": float(bits[1]),
            # EXACTLY the key names dashboard/state.py builds. This is
            # the whole point -- if the fixture said day_open it would
            # prove nothing.
            "open": float(bits[2]),
            "high": float(bits[3]),
            "low": float(bits[4]),
            "prev_close": float(bits[5]),
            "volume": float(bits[6]),
            "change_pct": float(bits[7]),
            "turnover_cr": float(bits[1]) * float(bits[6]) / 1e7,
            "volume_ratio": 2.5,
            "why": "results",
            "sector": "DIVERSIFIED",
        })
    return out


def main():
    from core import select as rules
    from core.ranker import rank

    tape = rows()
    ranked = rank(tape, adv_of=lambda s: 60.0, top=50)
    candidates = ranked.get("rows") or []

    broken = kept = 0
    broken_why, kept_why = {}, {}
    for row in candidates:
        # ---- WHAT THE CODE DID UNTIL 11 AUGUST ----
        before = rules.movement({
            "ltp": row.get("ltp"),
            "day_open": row.get("day_open"),
            "day_high": row.get("day_high"),
            "day_low": row.get("day_low"),
            "volume_ratio": row.get("volume_ratio") or 1.6,
        })
        # ---- WHAT IT DOES NOW ----
        after = rules.movement({
            "ltp": row.get("ltp"),
            "day_open": row.get("day_open") or row.get("open"),
            "day_high": row.get("day_high") or row.get("high"),
            "day_low": row.get("day_low") or row.get("low"),
            "volume_ratio": (row.get("volume_ratio")
                             or row.get("volume_x") or 1.6),
        })
        if before.get("ok"):
            broken += 1
        else:
            broken_why[before.get("why")] = broken_why.get(
                before.get("why"), 0) + 1
        if after.get("ok"):
            kept += 1
        else:
            kept_why[after.get("why")] = kept_why.get(after.get("why"), 0) + 1

    print()
    print("  DID THE ENTRY PATH EVER GET A CANDIDATE?")
    print("  " + "=" * 62)
    print(f"  real gainers replayed          {len(tape)}")
    print(f"  cleared core/ranker.py         {len(candidates)}")
    print()
    print(f"  reached the entry path BEFORE  {broken}")
    for why, n in sorted(broken_why.items(), key=lambda kv: -kv[1]):
        print(f"      {why} x{n}")
    print()
    print(f"  reaches the entry path NOW     {kept}")
    for why, n in sorted(kept_why.items(), key=lambda kv: -kv[1]):
        print(f"      {why} x{n}")
    print()
    if broken == 0 and kept > 0:
        print(f"  {kept} real stocks now reach auto_entry that never could.")
    elif kept == 0:
        print("  STILL ZERO. The fix did not do what I said it did.")
    print()
    return 0 if kept > broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
