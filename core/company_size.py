"""
==========================================================
How big the company is, and what that makes it
==========================================================

    "why cant we have that for all stocks or atleast for the sortlisted
     candidates each day along with their size = Largecap , Midcap,
     smallcap"                  -- the operator, 6 September 2026

TWO DIFFERENT NUMBERS, KEPT APART ON PURPOSE
--------------------------------------------
core/market_cap.py holds FREE FLOAT -- only the shares that can
actually be bought and sold, promoter and locked-in holdings stripped
out. That is the right measure for "how big is this order against the
company", because the price is set by the part that floats, and it is
the number core/cause_effect.py's gate reads.

THIS file holds TOTAL market capitalisation -- every share, including
the promoter's. That is the right measure for SIZE CLASS, because that
is how SEBI defines one, and it is the wrong measure for the order
gate. They are separate modules so that the two can never be swapped
by accident. Nothing here is read by any gate.

WHY IT EXISTS AT ALL, given it decides nothing
----------------------------------------------
Asked on 6 September whether size predicts anything, his own book
could not answer:

    from 29 August, under the rules running now
        LARGE       2 trades      2 up     0 down
        MID         3 trades      3 up     0 down
        SMALL      56 trades     25 up    31 down

Five non-small trades. That settles nothing, and the 139 trades before
29 August ran a different stop, target and sizing -- his rule is that a
new rule is never tuned on trades from the old one. The question is not
unanswered because the answer is hard; it is unanswered because
NOTHING WROTE THE SIZE DOWN. So this writes it down, beside door,
volume_x, jump_x and liveness, and the book answers it later by itself.

WHERE THE NUMBER COMES FROM
---------------------------
data/LIST_NSE.xlsx -- NSE's own SEBI-LODR filing, average market cap
July-December 2025, in lakhs. HIS file, already on disk since 8 August.
No network, no NSE crawling, nothing to throttle.

    1,741 of the 1,976 symbols on file are covered -- 88%
    versus 500 for free float, which is capped by what the NSE index
    API will serve (NIFTY 500 works; MICROCAP 250, TOTAL MARKET and
    SMALLCAP 100 return zero rows, measured 6 September)

The 235 it does not cover are mostly listings after December 2025. An
unknown size is stored as nothing and reported as nothing -- never
guessed, never defaulted to SMALL.

THE RANK IS NSE'S OWN. The file carries a Rank column, verified on
6 September to be exactly the size order and contiguous 1..2,773. SEBI
defines the bands by that rank across all listed companies:

    rank    1 - 100     LARGE      RELIANCE 1, DRREDDY 100
    rank  101 - 250     MID        SHREECEM 101, TATAELXSI 250
    rank  251 and on    SMALL      NLCINDIA 251

Recomputing the ranking here would only invent a second answer that
drifts from NSE's.

A NOTE ON THE COLUMN THAT WENT MISSING. core/centre.py reads an
MCAP_CR column out of data/master_stocks.csv and has been getting None
for every stock. The repo's own note says that column "has never
existed". It did: the backup from 10 August carries it for 1,474 of
1,608 rows, and it was dropped when the master was rebuilt to 1,976
symbols. This does not put it back -- a number that moves with the
price does not belong in his hand-edited universe file, which is the
same reasoning core/market_cap.py was built on.

Refresh:  py tools/refresh_company_size.py

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
from datetime import datetime

from core.logger import decision, diagnostic, warn

STORE = os.path.join("data", "company_size.json")
SOURCE = os.path.join("data", "LIST_NSE.xlsx")

# SEBI's own boundaries, by rank across all listed companies.
LARGE_CAP_MAX_RANK = 100
MID_CAP_MAX_RANK = 250

# NSE files the figure in LAKHS. Everything this bot says is in crore.
_LAKHS_PER_CRORE = 100.0

BANDS = ("LARGE", "MID", "SMALL")


def band_for_rank(rank):
    """LARGE / MID / SMALL for a rank, or None if there is no rank."""
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value <= LARGE_CAP_MAX_RANK:
        return "LARGE"
    if value <= MID_CAP_MAX_RANK:
        return "MID"
    return "SMALL"


def refresh(source=None, store=None):
    """Read the NSE list and write the store. Returns how many.

    Reads an .xlsx, so pandas is imported HERE and not at module load
    -- the live path only ever opens the json this writes.

    Never raises. A size that cannot be read costs a label on a screen.
    """
    src = source or SOURCE
    path = store or STORE
    if not os.path.exists(src):
        warn(f"[SIZE] {src} is not on disk. Nothing refreshed -- this "
             f"is NSE's SEBI-LODR list and it is not fetched, it is "
             f"placed there by hand.")
        return 0
    try:
        import pandas as pd
    except Exception as exc:                               # noqa: BLE001
        warn(f"[SIZE] pandas is not available ({exc}). Nothing refreshed.")
        return 0
    try:
        frame = pd.read_excel(src)
    except Exception as exc:                               # noqa: BLE001
        warn(f"[SIZE] Could not read {src}: {str(exc)[:70]}")
        return 0

    columns = [c for c in frame.columns
               if "market capitalisation" in str(c).lower()]
    if not columns or "Symbol" not in frame.columns:
        warn(f"[SIZE] {src} does not look like the NSE list -- "
             f"columns are {list(frame.columns)[:4]}")
        return 0
    cap_column = columns[0]

    sizes, skipped = {}, 0
    for _index, row in frame.iterrows():
        symbol = str(row.get("Symbol") or "").strip().upper()
        if not symbol:
            skipped += 1
            continue
        # 94 rows read "Not traded during the period" rather than a
        # number, and two carry no rank. Both are left out entirely:
        # a company with no size gets no band, not a small one.
        try:
            lakhs = float(row.get(cap_column))
            rank = int(row.get("Rank"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        if lakhs != lakhs or lakhs <= 0 or rank <= 0:       # NaN, or junk
            skipped += 1
            continue
        sizes[symbol] = {"cap_cr": round(lakhs / _LAKHS_PER_CRORE, 1),
                         "rank": rank,
                         "band": band_for_rank(rank)}

    if not sizes:
        warn(f"[SIZE] {src} yielded no company sizes. Store untouched.")
        return 0

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"at": datetime.now().isoformat(timespec="seconds"),
                       "source": os.path.basename(src),
                       "basis": "total market capitalisation, NSE "
                                "SEBI-LODR list",
                       "unit": "crore rupees",
                       "sizes": sizes}, fh, indent=1, sort_keys=True)
    except Exception as exc:                               # noqa: BLE001
        warn(f"[SIZE] Could not write {path}: {exc}")
        return 0

    decision(f"[SIZE] {len(sizes)} company sizes on file from "
             f"{os.path.basename(src)} ({skipped} rows carried no "
             f"usable figure).")
    return len(sizes)


_CACHE = {}


def load(path=None):
    """{"at", "sizes": {symbol: {...}}}. Empty when nothing is stored."""
    p = path or STORE
    try:
        stamp = os.path.getmtime(p)
    except OSError:
        return {"at": None, "sizes": {}}
    held = _CACHE.get(p)
    if held and held[0] == stamp:
        return held[1]
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[SIZE] {p} unreadable: {exc}")
        return {"at": None, "sizes": {}}
    if not isinstance(data.get("sizes"), dict):
        data["sizes"] = {}
    _CACHE[p] = (stamp, data)
    return data


def of(symbol, path=None):
    """{"cap_cr", "rank", "band"} for this company, or None.

    None means NOT KNOWN. It never means small, and it is never a
    guess -- 235 of his 1,976 symbols are not on NSE's list at all,
    mostly listings after December 2025.
    """
    sizes = load(path).get("sizes") or {}
    got = sizes.get(str(symbol or "").strip().upper())
    return got if isinstance(got, dict) else None


def band_of(symbol, path=None):
    """LARGE / MID / SMALL, or None when the company is not on file."""
    got = of(symbol, path)
    return got.get("band") if got else None


def bands_for(symbols, path=None):
    """{symbol: band} for many, in one read. For the board."""
    sizes = load(path).get("sizes") or {}
    out = {}
    for symbol in symbols or ():
        name = str(symbol or "").strip().upper()
        got = sizes.get(name)
        if isinstance(got, dict) and got.get("band"):
            out[name] = got["band"]
    return out


def label(symbol, path=None):
    """One short thing to read beside a stock, or None.

        "SMALL CAP, Rs 2,412 cr"

    Nothing is shown for a company that is not on file, because
    "unknown size" beside a stock is noise, not information.
    """
    got = of(symbol, path)
    if not got or not got.get("band"):
        return None
    cap = got.get("cap_cr")
    if not cap:
        return f"{got['band']} CAP"
    return f"{got['band']} CAP, Rs {cap:,.0f} cr"


def status(path=None):
    """What the board can say about this store without guessing."""
    data = load(path)
    sizes = data.get("sizes") or {}
    counts = {b: 0 for b in BANDS}
    for got in sizes.values():
        band = (got or {}).get("band")
        if band in counts:
            counts[band] += 1
    return {
        "available": bool(sizes),
        "symbols": len(sizes),
        "at": data.get("at"),
        "source": data.get("source"),
        "basis": "total market cap",
        "large": counts["LARGE"],
        "mid": counts["MID"],
        "small": counts["SMALL"],
    }
