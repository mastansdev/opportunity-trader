"""
==========================================================
py tools/silent_subscriptions.py -- subscribed, but never ticks
==========================================================

    "MOTHERSON has no price data ... i'm taking position in kalyankjil
     & bot dont track that"
                                -- operator, 7-8 August 2026

WHY THIS EXISTS
---------------
MOTHERSON is in the master, is not blocked, carries SUBSCRIBE = YES,
resolves to security id 25510, and has produced ZERO candles on every
recorded session. The operator holds 2,000 shares of it and the bot is
blind to the price.

Nothing reported that. It was found by accident, days later, while
chasing a different question.

That is the failure this file removes. A subscription that is accepted
and then delivers nothing is invisible: no error, no exception, no
gap in any count he sees. The only way to detect it is to compare what
was SUBSCRIBED against what actually ARRIVED, and nothing did.

Measured 8 August 2026: 1,139 subscribed, 1,120 recorded, 19 silent on
every one of the last six sessions.

WHAT IT SEPARATES
-----------------
Three different faults look identical from the outside, and each needs
a different fix:

    WRONG ID     the master's security id disagrees with Dhan's.
                 data/scrip_verified.json already knows these.
                 -> py tools/fix_security_ids.py

    NOT AT DHAN  the symbol does not exist in Dhan's scrip master --
                 delisted, renamed, or never listed.
                 -> it must come out of the universe

    UNEXPLAINED  correct id, present at Dhan, subscribed, and still
                 silent. MOTHERSON is one of these, and it cannot be
                 diagnosed offline: it needs one live session with the
                 feed logging what it actually receives.

WHY IT DOES NOT GUESS
---------------------
The third bucket is the honest answer, not a failure of the tool. A
tool that invented a cause for MOTHERSON would be the same mistake as
a chip built from another company's numbers.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANDLES_DB = "data/backtest_candles.db"
PROOF_PATH = os.path.join("data", "scrip_verified.json")

# A symbol silent for this many recorded sessions is not having a
# quiet day -- it is not arriving at all.
SESSIONS = 5


def _proof():
    """What tools/verify_master_database.py found last time it ran."""
    try:
        with open(PROOF_PATH, encoding="utf-8") as handle:
            return json.load(handle) or {}
    except Exception:                                      # noqa: BLE001
        return {}


def main():
    from core.master_loader import MasterLoader

    loader = MasterLoader()
    loader.load()
    subscribed = list(loader.all_symbols())

    con = sqlite3.connect(CANDLES_DB)
    days = [row[0] for row in con.execute(
        "select distinct date from candles order by date desc limit ?",
        (SESSIONS,))]
    if not days:
        print("No recorded sessions. Run the bot first.")
        return 0

    seen = {}
    for day in days:
        seen[day] = {row[0] for row in con.execute(
            "select distinct symbol from candles where date = ?", (day,))}
    con.close()

    ever = set()
    for day in days:
        ever |= seen[day]
    silent = sorted(s for s in subscribed if s not in ever)

    print("=" * 72)
    print("  SUBSCRIBED BUT NEVER TICKING")
    print(f"  across the last {len(days)} recorded session(s): "
          f"{days[-1]} to {days[0]}")
    print("=" * 72)
    print(f"  subscribed : {len(subscribed)}")
    print(f"  ticking    : {len(subscribed) - len(silent)}")
    print(f"  SILENT     : {len(silent)}")

    if not silent:
        print("\n  Every subscribed symbol is delivering data.")
        print("=" * 72)
        return 0

    proof = _proof()
    wrong_id = {}
    for line in proof.get("mismatches") or []:
        # "TRIVENI: master 13084, Dhan 13081"
        try:
            symbol, rest = str(line).split(":", 1)
            wrong_id[symbol.strip().upper()] = rest.strip()
        except ValueError:
            continue
    not_found = {str(s).upper() for s in (proof.get("not_found") or [])}

    buckets = {"WRONG ID": [], "NOT AT DHAN": [], "UNEXPLAINED": []}
    for symbol in silent:
        if symbol in wrong_id:
            buckets["WRONG ID"].append((symbol, wrong_id[symbol]))
        elif symbol in not_found:
            buckets["NOT AT DHAN"].append((symbol, "absent from Dhan's "
                                                   "scrip master"))
        else:
            buckets["UNEXPLAINED"].append(
                (symbol, f"id {loader.security_id(symbol)}, verified "
                         f"correct, subscribed, silent"))

    for name, rows in buckets.items():
        if not rows:
            continue
        print(f"\n  {name}  ({len(rows)})")
        for symbol, detail in rows:
            print(f"     {symbol:<14} {detail}")

    print("\n" + "=" * 72)
    if buckets["WRONG ID"]:
        print("  -> py tools/fix_security_ids.py     (applies Dhan's ids)")
    if buckets["NOT AT DHAN"]:
        print("  -> these should come out of the universe; they cannot "
              "be traded")
    if buckets["UNEXPLAINED"]:
        print("  -> these need ONE live session with the feed logging "
              "what arrives.")
        print("     Nothing offline can tell the difference between "
              "'Dhan never sent it'")
        print("     and 'we dropped it'. Do not guess -- measure it.")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
