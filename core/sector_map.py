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


# ==========================================================
#  THE CHAIN: who is linked to what
# ==========================================================
#
#     "which company is linked what sector, theme, which raw material
#      provider, end user of the products every thing in as same as
#      bloomberg"                   -- operator, 16 August 2026
#
# Bloomberg calls this SPLC -- supply chain -- and builds it from
# DISCLOSED supplier and customer relationships: contracts, filings,
# revenue concentration. That dataset is not in this repo and cannot be
# derived from what is. Saying otherwise would be inventing a fact.
#
# WHAT IS HERE IS REAL AND IS NOT NOTHING. data/master_stocks.csv
# classifies all 1,314 tradeable names on five axes, and a reverse
# index over them answers the question that actually matters to an
# opportunity bot:
#
#     COMMODITY_EXPOSURE    1,807 tags   STEEL 241, CRUDE OIL 89,
#                                        ALUMINIUM 69, COPPER 61
#     THEMES                3,370 tags   966 distinct
#     ECONOMIC_SENSITIVITY  1,442 tags   EXPORT ORIENTED, IMPORT
#                                        DEPENDENT, GOVERNMENT SPENDING
#     BUSINESS_TYPE         1,314 tags   MANUFACTURER 754, DISTRIBUTOR
#                                        51, EPC / CONTRACTOR 77
#     INDUSTRY                635 distinct
#
# "Crude spikes -- who does that reach?" is answerable exactly.
# "Who supplies Tata Steel?" is not, and this says so rather than
# guessing. BUSINESS_TYPE is the closest thing to a position in the
# chain: a MANUFACTURER exposed to STEEL consumes it, a METALS & MINING
# manufacturer produces it.

# The columns that carry a LIST of tags, separated by | or comma.
TAG_COLUMNS = ("THEMES", "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY",
               "KEYWORDS")
# The columns that carry exactly one value.
SINGLE_COLUMNS = ("SECTOR", "INDUSTRY", "BUSINESS_TYPE", "OWNERSHIP")

_TAG_CACHE = None


def _split_tags(raw):
    if not raw:
        return []
    out = []
    for part in str(raw).replace("|", ",").split(","):
        part = part.strip().upper()
        # NONE is a real answer to "what commodity does this touch" and
        # it is not a group worth listing 665 members for.
        if part and part != "NONE":
            out.append(part)
    return out


def _tag_index(path=MASTER_CSV):
    """{column: {tag: [symbols]}} over tradeable rows. Cached."""
    global _TAG_CACHE
    with _LOCK:
        if _TAG_CACHE is not None:
            return _TAG_CACHE
        index = {c: {} for c in TAG_COLUMNS + SINGLE_COLUMNS}
        for row in _rows(path):
            symbol = (row.get("SYMBOL") or "").strip().upper()
            if not symbol or not _tradeable(row):
                continue
            for column in SINGLE_COLUMNS:
                value = (row.get(column) or "").strip().upper()
                if value and value != "NONE":
                    index[column].setdefault(value, []).append(symbol)
            for column in TAG_COLUMNS:
                for tag in _split_tags(row.get(column)):
                    index[column].setdefault(tag, []).append(symbol)
        _TAG_CACHE = {c: {t: sorted(set(s)) for t, s in tags.items()}
                      for c, tags in index.items()}
        return _TAG_CACHE


def carrying(tag, path=MASTER_CSV):
    """Every tradeable symbol carrying `tag`, and where it was found.

    [{"column", "tag", "symbols"}], biggest group first. Searched
    across every axis, because he does not have to know whether STEEL
    is a commodity or a theme -- it is both, on different rows.
    """
    needle = str(tag or "").strip().upper()
    if not needle:
        return []
    out = []
    for column, tags in _tag_index(path).items():
        for value, symbols in tags.items():
            if value == needle:
                out.append({"column": column, "tag": value,
                            "symbols": symbols})
    out.sort(key=lambda r: -len(r["symbols"]))
    return out


def like(fragment, limit=20, path=MASTER_CSV):
    """Tags CONTAINING the fragment -- for "crude" finding "CRUDE OIL".

    Exact matches first, then by group size. Without this he has to
    know the master's own spelling before he can ask a question.
    """
    needle = str(fragment or "").strip().upper()
    if len(needle) < 2:
        return []
    hits = []
    for column, tags in _tag_index(path).items():
        for value, symbols in tags.items():
            if needle in value:
                hits.append({"column": column, "tag": value,
                             "count": len(symbols),
                             "exact": value == needle})
    hits.sort(key=lambda r: (not r["exact"], -r["count"]))
    return hits[:limit]


def links_of(symbol, path=MASTER_CSV):
    """Every group this symbol belongs to, with its fellow members.

    The answer to "what is this company connected to" -- its sector,
    its industry, every theme, every raw material it is exposed to,
    and what kind of business it is. Peers are the other members of
    each group, so a crude spike names its own list.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"symbol": "", "found": False, "groups": []}
    index = _tag_index(path)
    groups = []
    for column in SINGLE_COLUMNS + TAG_COLUMNS:
        for value, symbols in index.get(column, {}).items():
            if sym in symbols:
                peers = [s for s in symbols if s != sym]
                groups.append({"column": column, "tag": value,
                               "peers": peers, "count": len(peers)})
    # Narrowest first: sharing a 3-member theme says far more about two
    # companies than sharing a 151-member sector.
    groups.sort(key=lambda g: (g["count"], g["column"]))
    return {"symbol": sym, "found": bool(groups), "groups": groups}


def tag_counts(column=None, path=MASTER_CSV):
    """{column: [(tag, n)]} biggest first -- the map of the whole board."""
    index = _tag_index(path)
    wanted = [column] if column else list(index)
    return {c: sorted(((t, len(s)) for t, s in index.get(c, {}).items()),
                      key=lambda r: -r[1])
            for c in wanted}
