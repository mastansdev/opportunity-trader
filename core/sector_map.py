"""
==========================================================
From a sector index to the stocks inside it
==========================================================

    "war news will move all stocks fall. & cease fire agreement done
     all stocks were positive . in this situation also some stocks get
     more benifits & some stocks will fall"
                                    -- operator, 3 August 2026

THE HOLE THIS FILLS
-------------------
core/news_impact.py fans a story out to NAMED companies. Its own
docstring is explicit that it returns [] for a story that names nobody,
"which is the honest answer for macro news".

Honest, and useless for a war headline. Nothing in a strike on the
Strait of Hormuz names an Indian company, so the whole chain produced
nothing -- no stocks, no direction, no buttons. The alert would have
fired on the tape and had an empty frame to show.

core/shock.py takes an event to a SECTOR. This takes a sector to the
stocks in it. That is the last hop.

TWO VOCABULARIES, AND NEITHER WAS INVENTED HERE
-----------------------------------------------
The bot prices FOURTEEN sector indices (config.SECTOR_INDICES, every
security id read live from Dhan's master, never remembered). The stock
master uses its own THIRTY sector names, read out of the real file:

    CAPITAL GOODS, FINANCIAL SERVICES, AUTOMOBILE, PHARMACEUTICALS,
    CHEMICALS, METALS & MINING, INFORMATION TECHNOLOGY, ...

They are different vocabularies and there is no rule that converts one
into the other. So the join is written out below, and a test walks
every entry against the real master -- a value that does not exist
there fails the suite rather than silently matching nothing.

    "NEVER ASSUME ANYTHING. SEARCH RESOURCES, GET INFORMATION"

WHERE THE MASTER IS SHARPER THAN ITS OWN SECTOR COLUMN
------------------------------------------------------
SECTOR has one bucket, BANKING, and cannot tell a public-sector bank
from a private one. The bot prices those as two separate indices, and
they routinely move opposite ways. INDUSTRY does split them --
"BANKING - PSU / OTHER" and "BANKING - PRIVATE / SMALL FINANCE" -- so
those two entries read INDUSTRY instead. Same file, finer column.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import threading

from core.liquidity import by_size
from core.logger import diagnostic, warn

MASTER_CSV = os.path.join("data", "master_stocks.csv")

# ---------------------------------------------------------------
# The join. Left side: what the bot prices. Right side: what the
# master calls it, verbatim.
# ---------------------------------------------------------------
#
# Deliberate exclusions, each one a decision rather than an oversight:
#
#   Energy      -> POWER & UTILITIES only. NIFTY Energy holds oil AND
#                  power, but Oil & Gas is priced separately below and
#                  a stock in both lists would be counted twice in the
#                  same alert.
#   Healthcare  -> HEALTHCARE SERVICES only, for the same reason:
#                  PHARMACEUTICALS is its own index.
#   IT          -> INFORMATION TECHNOLOGY only. INTERNET & DIGITAL
#                  PLATFORMS is a different business with a different
#                  driver; a rupee move does not touch it the way it
#                  touches a services exporter.
INDEX_TO_MASTER = {
    "IT":                {"SECTOR": ("INFORMATION TECHNOLOGY",)},
    "Pharma":            {"SECTOR": ("PHARMACEUTICALS",)},
    "Metal":             {"SECTOR": ("METALS & MINING",)},
    "Auto":              {"SECTOR": ("AUTOMOBILE",)},
    "Energy":            {"SECTOR": ("POWER & UTILITIES",)},
    "PSU Bank":          {"INDUSTRY": ("BANKING - PSU / OTHER",)},
    "Private Bank":      {"INDUSTRY": ("BANKING - PRIVATE / SMALL FINANCE",)},
    "FMCG":              {"SECTOR": ("FMCG",)},
    "Realty":            {"SECTOR": ("REAL ESTATE",)},
    "Media":             {"SECTOR": ("MEDIA & ENTERTAINMENT",)},
    "Infra":             {"SECTOR": ("INFRASTRUCTURE",)},
    "Oil & Gas":         {"SECTOR": ("OIL & GAS",)},
    "Healthcare":        {"SECTOR": ("HEALTHCARE SERVICES",)},
    "Consumer Durables": {"SECTOR": ("CONSUMER DURABLES",)},
}

# ---------------------------------------------------------------
# Finer groups, for fan-out only
# ---------------------------------------------------------------
#
#     "remember crude raise & fall concept?"
#
# A sector index is too coarse for the crude chain and it showed:
# NIFTY Oil & Gas holds ONGC and BPCL, crude up helps one and hurts the
# other, and core/shock.py correctly refused to have a view on the
# basket. Correct, and useless -- he asked which stocks benefit.
#
# These groups do not need a live index price, because the fan-out
# reads per-stock prices off the movers feed anyway. So they can be as
# fine as the master allows, and the master is much finer than its own
# SECTOR column:
#
#     OIL & GAS EXPLORATION   2      OIL REFINING            5
#     PAINTS / ADHESIVES      6      TYRES                   5
#     JEWELLERY / WATCHES    10      AVIATION / AIRPORTS   ...
#
# Matched as substrings, not exact values, because the column carries
# real-world variants -- "PAINTS & COATINGS" beside "PAINTS /
# ADHESIVES", "JEWELLERY" beside "JEWELLERY / WATCHES RETAIL", and rows
# where the industry reads "CONSUMER DISCRETIONARY -- GROVER JEWELLS".
# Every one of those is genuinely a jeweller and belongs in the list.
FAN_OUT_GROUPS = {
    "Oil exploration": ("OIL & GAS EXPLORATION", "OIL EXPLORATION"),
    "Oil refining":    ("OIL REFINING",),
    "Aviation":        ("AVIATION",),
    "Paints":          ("PAINT",),
    "Tyres":           ("TYRE",),
    "Jewellery":       ("JEWELL",),
    "City gas":        ("CITY GAS", "GAS DISTRIBUTION"),
    "Fertilisers":     ("FERTILIS",),
    "Defence":         ("DEFENCE",),
}

_LOCK = threading.Lock()
_CACHE = None


def _rows(path=MASTER_CSV):
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        warn(f"[SECTORS] Could not read {path}: {exc}")
        return []


def _build(path=MASTER_CSV):
    """{group name: [symbols]} -- tradeable names only.

    Holds both the fourteen priced sector indices and the finer fan-out
    groups. A stock can appear in one of each, which is intended: BPCL
    is in Oil & Gas for the awareness tile and in Oil refining for the
    crude chain.
    """
    out = {name: [] for name in INDEX_TO_MASTER}
    out.update({name: [] for name in FAN_OUT_GROUPS})

    for row in _rows(path):
        symbol = (row.get("SYMBOL") or "").strip().upper()
        if not symbol:
            continue
        # SUBSCRIBE is the master's own answer to "do we trade this".
        # A name the bot will not subscribe to must never appear on a
        # button -- "pls make sure we will trade only NSE listed
        # stocks".
        if not _tradeable(row):
            continue

        for name, wanted in INDEX_TO_MASTER.items():
            for column, values in wanted.items():
                if (row.get(column) or "").strip().upper() in values:
                    out[name].append(symbol)
                    break

        industry = (row.get("INDUSTRY") or "").strip().upper()
        if industry:
            for name, needles in FAN_OUT_GROUPS.items():
                if any(needle in industry for needle in needles):
                    out[name].append(symbol)

    return {k: sorted(set(v)) for k, v in out.items()}


def _tradeable(row):
    flag = (row.get("SUBSCRIBE") or "").strip().upper()
    if not flag:
        return True
    return flag not in ("NO", "N", "FALSE", "0", "SKIP", "DROP")


def _cache(path=MASTER_CSV):
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _CACHE = _build(path)
            empty = [k for k, v in _CACHE.items() if not v]
            if empty:
                warn(f"[SECTORS] No stocks mapped for: {', '.join(empty)}. "
                     f"The master's sector names may have changed.")
            else:
                diagnostic(f"[SECTORS] {sum(len(v) for v in _CACHE.values())} "
                           f"stocks across {len(_CACHE)} traded sectors.")
        return _CACHE


def reset():
    """Drop the cache. For tests and for a rebuilt master."""
    global _CACHE
    with _LOCK:
        _CACHE = None


def members(sector, limit=None, path=MASTER_CSV):
    """Every tradeable stock the master puts in this sector index."""
    rows = _cache(path).get(sector) or []
    return rows[:limit] if limit else list(rows)


def sector_of(symbol, path=MASTER_CSV):
    """Which priced sector index a symbol belongs to, or None."""
    target = str(symbol or "").strip().upper()
    for name, symbols in _cache(path).items():
        if target in symbols:
            return name
    return None


def counts(path=MASTER_CSV):
    return {k: len(v) for k, v in _cache(path).items()}


def spread(pushes, movers=None, per_sector=3, path=MASTER_CSV):
    """{sector: +1/-1} -> the stocks to actually put in front of him.

    Prefers names that are ALREADY MOVING, because a reason nobody is
    trading is a theory -- his own rule, "volumes supports the data".
    Falls back to the master's membership so a sector still produces
    something in the first seconds of an event, before the tape has
    caught up.
    """
    recent = {}
    for row in (movers or []):
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            recent[symbol] = row

    up, down = [], []
    for sector, way in (pushes or {}).items():
        names = members(sector, path=path)
        if not names:
            continue
        # Moving first, biggest move first. Then the rest by how much
        # money actually trades in them.
        #
        # ---- 3 August 2026 ----
        # This used to fall back to master order, which is alphabetical,
        # so the first seconds of a shock -- before anything has ticked,
        # the seconds that matter -- offered 63MOONS and AFFLE for IT
        # instead of TCS and INFY. I described that as needing an input
        # the bot did not have. It did have it:
        # data/history_candles.db carries a volume column on all
        # nineteen million rows. See core/liquidity.py.
        moving = [n for n in names if n in recent]
        moving.sort(key=lambda n: -abs(recent[n].get("recent_pct") or 0))
        rest = by_size([n for n in names if n not in recent])
        chosen = (moving + rest)[:per_sector]

        for name in chosen:
            row = recent.get(name) or {}
            entry = {"symbol": name, "sector": sector,
                     "change_pct": row.get("change_pct"),
                     "recent_pct": row.get("recent_pct"),
                     "moving": name in recent,
                     "action": "BUY" if way > 0 else "SELL"}
            (up if way > 0 else down).append(entry)
    return up, down
