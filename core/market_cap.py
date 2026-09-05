"""How big is the company. For judging how big a thing that happened to it is.

==========================================================
    "see the order is compared to Market price of the company &
     pricing the stock. check the % of that order to their market
     cap. this reveal the significance of the order book.
     ex simple = 100 cr order for 200 MCAP & 10000 MCAP company
     1st is 50% & the other is 1%"
                            -- the operator, 5 September 2026
==========================================================

He is right, and the evidence from this bot's own store says so.
Ranking orders by RUPEES put an investor presentation at the top --
JNPR, Rs 26,231 cr, where the figure was a megawatt target. Ranking
them by SHARE OF THE COMPANY puts the two that actually ran near the
top, and exposes the bad row without anyone having to look:

    date        stock         order    free float   share      3d     10d
    2026-08-21  NUVAMA     15,840cr     14,099cr    112%   +2.0%       -
    2026-08-26  ADANIENSOL 24,700cr     46,996cr     53%   -9.7%       -
    2026-08-20  WELCORP    15,840cr     33,636cr     47%  +17.0%  +31.7%
    2026-08-27  TEJASNET    1,537cr      5,043cr     30%   +6.0%       -
    2026-08-13  RAILTEL       630cr      2,370cr     27%   -2.8%   -2.2%
    2026-08-03  KEC         1,063cr      5,281cr     20%   -0.2%   -8.9%

An order bigger than the whole company is not an order -- that NUVAMA
row is an acquisition APPROACH, and this measure catches it without a
rule being written for it. And RAILTEL's Rs 630 cr looks small in
rupees and is a quarter of the company, which is exactly the
information absolute size destroys.

WHAT THIS IS NOT. Not a signal. Of the eleven orders above 20% of
their company, WELCORP and TEJASNET rose meaningfully and AFCONS, NBCC,
RAILTEL and KEC fell. It is a better ORDERING, not a prediction, and
nothing here votes on a trade.

TWO LIMITS, both stated on every reading.

  FREE FLOAT, NOT FULL MARKET CAP. NSE publishes ffmc in bulk and the
  full figure only per symbol. Free float excludes promoter holding,
  so a promoter-heavy company reads as smaller than it is and its
  orders read as more significant. The share is therefore an UPPER
  bound on significance, and it is labelled as free float wherever it
  is shown.

  PARTIAL COVERAGE. A handful of index calls reach about 500 of the
  1,976 symbols on file. The liquid names are covered; the tail is
  not. An unknown size is stored as nothing and shown as nothing --
  never guessed, never defaulted.

WHY A SIDE FILE AND NOT THE MASTER. data/master_stocks.csv is his
curated universe, rebuilt by tools/refresh_universe.py and edited by
hand. A number that changes with the price every day does not belong
in it. core/centre.py already reads an MCAP_CR column that has never
existed in that file -- 0 of 1,976 rows carry one -- and the honest
fix is a store that is actually written, not another column nobody
fills.

Refresh:  py tools/refresh_market_cap.py

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
from datetime import datetime

from core.logger import decision, diagnostic, warn

STORE = os.path.join("data", "market_cap.json")

# A few broad index lists reach most of what trades. Ordered widest
# first so the fewest calls cover the most names, and every one that
# fails simply contributes nothing.
INDICES = (
    "NIFTY 500",
    "NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 250",
    "NIFTY MICROCAP 250",
    "NIFTY 50",
)

# NSE gives ffmc in RUPEES. Everything this bot talks about is crore.
_RUPEES_PER_CRORE = 1e7

# Older than this and it is not refused -- a company's size does not
# move much in a week -- but it is reported, so a stale reading is
# visible rather than silently believed.
STALE_AFTER_DAYS = 7


def refresh(store=None, indices=None):
    """Fetch free-float market caps and write them. Returns how many.

    Never raises. A size lookup that fails costs a sentence on a
    screen; nothing here is on the trading path.
    """
    path = store or STORE
    got = {}
    try:
        from nse import NSE
    except Exception as exc:                               # noqa: BLE001
        warn(f"[MCAP] the nse package is not available ({exc}). "
             f"Nothing refreshed.")
        return 0
    try:
        with NSE(download_folder="data") as api:
            for name in (indices or INDICES):
                try:
                    payload = api.listEquityStocksByIndex(name) or {}
                except Exception as exc:                   # noqa: BLE001
                    diagnostic(f"[MCAP] {name}: {str(exc)[:60]}")
                    continue
                added = 0
                for row in (payload.get("data") or []):
                    symbol = str(row.get("symbol") or "").strip().upper()
                    ffmc = row.get("ffmc")
                    if not symbol or not ffmc or symbol in got:
                        continue
                    try:
                        crore = float(ffmc) / _RUPEES_PER_CRORE
                    except (TypeError, ValueError):
                        continue
                    if crore <= 0:
                        continue
                    got[symbol] = round(crore, 1)
                    added += 1
                diagnostic(f"[MCAP] {name}: {added} new")
    except Exception as exc:                               # noqa: BLE001
        warn(f"[MCAP] Could not reach NSE ({str(exc)[:70]}). "
             f"Keeping what is already stored.")

    if not got:
        return 0
    # ---- A PARTIAL FETCH MUST NOT DELETE WHAT IS KNOWN. ----
    # One index failing is normal; losing every size because of it is
    # not. The new reading is merged over the old.
    held = load(path)
    merged = dict(held.get("caps") or {})
    merged.update(got)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"at": datetime.now().isoformat(timespec="seconds"),
                       "source": "NSE index lists, free float (ffmc)",
                       "unit": "crore rupees",
                       "caps": merged}, fh, indent=1, sort_keys=True)
    except Exception as exc:                               # noqa: BLE001
        warn(f"[MCAP] Could not write {path}: {exc}")
        return 0
    decision(f"[MCAP] {len(got)} company sizes refreshed, "
             f"{len(merged)} on file.")
    return len(got)


_CACHE = {}


def load(path=None):
    """{"at", "caps": {symbol: crore}}. Empty when nothing is stored."""
    p = path or STORE
    try:
        stamp = os.path.getmtime(p)
    except OSError:
        return {"at": None, "caps": {}}
    held = _CACHE.get(p)
    if held and held[0] == stamp:
        return held[1]
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MCAP] {p} unreadable: {exc}")
        return {"at": None, "caps": {}}
    if not isinstance(data.get("caps"), dict):
        data["caps"] = {}
    _CACHE[p] = (stamp, data)
    return data


def of(symbol, path=None):
    """This company's free-float size in crore, or None.

    None is a real answer and means "not known" -- never zero, never a
    guess. A caller that cannot get a size must say nothing rather than
    imply the company is tiny.
    """
    caps = (load(path).get("caps") or {})
    return caps.get(str(symbol or "").strip().upper())


def share_of_company(symbol, value_cr, path=None):
    """What share of the company this rupee figure is, as a percent.

    None when the size is unknown or the figure is missing. Values
    above 100 are returned as they are, NOT clipped: an "order" larger
    than the whole company is the store telling you the row is wrong,
    and hiding that would be hiding the most useful thing it says.
    """
    if not value_cr:
        return None
    cap = of(symbol, path)
    if not cap or cap <= 0:
        return None
    try:
        return round(float(value_cr) / float(cap) * 100.0, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def age_days(path=None):
    """How old the stored reading is, in days, or None."""
    at = load(path).get("at")
    if not at:
        return None
    try:
        return max(0, (datetime.now()
                       - datetime.fromisoformat(str(at))).days)
    except Exception:                                      # noqa: BLE001
        return None


def status(path=None):
    """What the board can say about this store without guessing."""
    data = load(path)
    caps = data.get("caps") or {}
    old = age_days(path)
    return {
        "available": bool(caps),
        "symbols": len(caps),
        "at": data.get("at"),
        "age_days": old,
        "stale": bool(old is not None and old > STALE_AFTER_DAYS),
        "basis": "free float",
    }
