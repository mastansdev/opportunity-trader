"""
==========================================================
Are the index ids right? Ask Dhan now, not tomorrow.
==========================================================
    py tools/check_index_levels.py

    "why we need to wait for the next market ? now we can get the
     closing value of stocks & indices. whats stopping your reasoning
     to thinking, working & giving responses?"
                                    -- operator, 3 August 2026

Nothing was stopping it. I had just written a healthcheck that reads
the WebSocket feed's log, noticed the feed is silent after 15:30, and
concluded the ids could not be verified until 09:15 the next morning.

The feed is one way to reach Dhan. The REST quote endpoint is another,
it serves the last traded price all day and all night, and this
codebase has been calling it every few seconds since July --
core/circuit_monitor.py is built on exactly that call.

So the whole question, "is 13 really NIFTY 50", is answerable in one
request at any hour.

WHAT IT CHECKS
--------------
Every id in config.INDEX_INSTRUMENTS, against the level that index
actually trades at:

    NIFTY 50      ~24,000        INDIA VIX      8-20
    NIFTY BANK    ~52,000        sector indices 5,000-80,000

A number in range does not prove the id is right, but a number OUT of
range proves it is wrong -- and that is the failure that has cost this
project two wrong diagnoses. The Nifty tile once showed 7,234, which
is ABB's share price, and it took a week to notice.

Author : H&M Opportunity Trader
==========================================================
"""

import sys

sys.path.insert(0, ".")

from config import (DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN,          # noqa: E402
                    INDEX_INSTRUMENTS, SECTOR_INDICES)
from core.logger import decision, warn                          # noqa: E402

# ---- THESE BOUNDS ARE EVIDENCE, NOT MEMORY. 3 August 2026. ----
#
# The first version of this file used SECTOR_RANGE = (1_000, 120_000),
# a floor I invented. The very first real run flagged
#
#     34  sector:Realty   913.05   OUT OF RANGE
#
# and the id was right: Nifty Realty is the lowest-valued NSE sector
# index and genuinely trades near 900. Dhan's own master confirms it --
# tools/find_index_ids.py printed "34  NIFTY REALTY  NIFTY Realty".
# Media at 1,568 cleared the same floor by luck.
#
# So a checker built to catch invented numbers reported a false alarm
# from an invented number of its own, on its first use. The floor below
# now sits under the LOWEST level actually observed, and the ceiling
# above the highest, both from that run:
#
#     Realty        913        lowest
#     Media       1,568
#     PSU Bank    8,486
#     ...
#     BankNifty  58,248        highest
#
# Widened either side so an index can move without tripping this, and
# still narrow enough to catch a three-digit share price where a
# five-digit index belongs.
#
# THE AUTHORITATIVE CHECK IS NOT THIS ONE. Dhan's scrip master names
# every id outright; tools/find_index_ids.py reads it. This is the
# cheap second opinion that runs in one second, after the close, and
# catches the gross error.
EXPECTED = {
    "nifty":     (20_000, 32_000),
    "banknifty": (40_000, 70_000),
    "vix":       (5, 60),
}
SECTOR_RANGE = (500, 150_000)

# Dhan's own enum for the index segment -- see their annexure:
# IDX_I, Index Value, 0. The string form is what quote_data expects.
IDX_SEGMENT = "IDX_I"


def main():
    from dhanhq import DhanContext, dhanhq as DhanRestClient

    line = "=" * 72
    decision(line)
    decision("  INDEX LEVELS -- asked of Dhan's REST quote endpoint")
    decision("  Works after the close. The feed sleeps; this does not.")
    decision(line)

    ids = sorted(INDEX_INSTRUMENTS.keys(), key=lambda x: int(x))
    decision(f"  Asking for {len(ids)} index/indices on {IDX_SEGMENT} ...")

    client = DhanRestClient(DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN))
    try:
        raw = client.quote_data({IDX_SEGMENT: [int(i) for i in ids]})
    except Exception as exc:                                   # noqa: BLE001
        warn(f"  Could not reach Dhan: {exc}")
        return

    if str((raw or {}).get("status", "")).lower() not in ("success", ""):
        warn(f"  Dhan refused: {raw}")
        return

    # Two "data" keys deep -- Dhan's HTTP wrapper nests the API body.
    # core/circuit_monitor.py's docstring documents this; same shape.
    body = ((raw or {}).get("data") or {}).get("data") or {}
    quotes = {}
    for segment, rows in body.items():
        if not isinstance(rows, dict):
            continue
        for sec_id, quote in rows.items():
            quotes[str(sec_id)] = quote

    if not quotes:
        warn(f"  No quotes came back. Raw response: {str(raw)[:300]}")
        return

    decision("")
    decision(f"  {'id':>5}  {'configured as':<22} {'last price':>13}   verdict")
    decision("  " + "-" * 68)

    bad = []
    for sec_id in ids:
        name = INDEX_INSTRUMENTS[sec_id]
        quote = quotes.get(sec_id)
        if not quote:
            warn(f"  {sec_id:>5}  {name:<22} {'--':>13}   NO QUOTE RETURNED")
            bad.append((sec_id, name, "no quote"))
            continue

        price = quote.get("last_price") or quote.get("ltp")
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
        if not price:
            warn(f"  {sec_id:>5}  {name:<22} {'--':>13}   NO PRICE")
            bad.append((sec_id, name, "no price"))
            continue

        tight = name in EXPECTED
        low, high = EXPECTED.get(name, SECTOR_RANGE)
        ok = low <= price <= high
        if not ok:
            verdict = f"OUT OF RANGE ({low:,}-{high:,})"
        elif tight:
            # A 20,000-32,000 window around Nifty is a real test: no
            # NSE share trades there, so passing it means something.
            verdict = "confirmed by level"
        else:
            # Sector indices run from 913 (Realty) to 58,248
            # (BankNifty). Share prices live inside that, so a pass
            # here is NOT confirmation and must not be printed as if
            # it were. YASHO at 4,114 would clear this window.
            verdict = "plausible -- name confirmed by scrip master"
        say = decision if ok else warn
        say(f"  {sec_id:>5}  {name:<22} {price:>13,.2f}   {verdict}")
        if not ok:
            bad.append((sec_id, name, f"{price:,.2f}"))

    decision("")
    decision(line)
    if bad:
        warn(f"  {len(bad)} id(s) look WRONG:")
        for sec_id, name, why in bad:
            warn(f"      {sec_id} configured as {name}: {why}")
        warn("  Re-run py tools/find_index_ids.py and compare.")
    else:
        decision(f"  All {len(ids)} ids return a level consistent with the "
                 f"index they are labelled as.")
        decision("")
        decision("  WHAT THAT DOES AND DOES NOT PROVE:")
        decision("    Nifty, BankNifty and VIX sit in windows no NSE share")
        decision("    can occupy, so those three are confirmed by level.")
        decision("    Sector indices run 913 (Realty) to 58,248 (BankNifty)")
        decision("    and share prices live inside that range -- a stock at")
        decision("    4,114 would clear it. Their names come from Dhan's own")
        decision("    scrip master via tools/find_index_ids.py, which is the")
        decision("    authoritative check. This is the cheap second opinion.")
    decision(line)


if __name__ == "__main__":
    main()
