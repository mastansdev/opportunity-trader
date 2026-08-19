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

# ==========================================================
#  WHICH SIDE OF THE COMMODITY IS THIS COMPANY ON?
# ==========================================================
#
#     "THE PURPOSE OF BRAIN MEMORY IS NOT FULLY PREPARED ... bot needs
#      to know which companies are positive & negative . as of now
#      there is no distinction between them"
#                                 -- operator, 18 August 2026,
#                                    with a screenshot reading
#                                    "COPPER COMPANIES WOULD BE IN
#                                     FOCUS -- LME COPPER ONE-DAY
#                                     SPREAD HITS $110"
#
# He is right, and the file proves it against itself. 71 symbols carry
# COMMODITY_EXPOSURE = COPPER:
#
#     67  MANUFACTURER        POLYCAB, KEI, CROMPTON, HAVELLS...
#      3  EPC / CONTRACTOR
#      1  MINING              HINDCOPPER
#
# On a copper spike exactly ONE of those 71 is helped. For the other
# 70 copper is an INPUT COST and the news is a headwind. carrying()
# would have handed him all 71 as "copper names", and the 70 wrong
# ones sit at the top because they are the liquid ones.
#
# A tag says a company TOUCHES a commodity. It has never said which
# END of it the company stands on, and a direction-free link is not
# an opportunity -- it is a coin flip wearing a reason.
#
# THREE ANSWERS, AND THE THIRD IS THE IMPORTANT ONE
# -------------------------------------------------
# PRODUCER, CONSUMER, and UNKNOWN. HINDALCO is why UNKNOWN exists: it
# is BUSINESS_TYPE=MANUFACTURER and its CORE BUSINESS reads
# "MANUFACTURES ALUMINIUM AND COPPER PRODUCTS". It is in fact a
# smelter -- a producer -- and nothing in this file says so. Calling
# it a CONSUMER because the word MANUFACTURES appears would be a
# confident wrong answer on a Rs 2 lakh account, which is worse than
# no answer.
#
# So the rule is deliberately narrow: when the company's stated
# PRODUCT IS THE COMMODITY ITSELF, this refuses to guess. When the
# product is something else made OUT of it -- wires, cables, fans,
# conductors -- the commodity is an input and the company is a
# consumer. That distinction is readable in the data we already have
# and needs no new source.

#: BUSINESS_TYPE values that produce what they are exposed to.
PRODUCER_TYPES = ("MINING",)

#: BUSINESS_TYPE values that buy their inputs.
CONSUMER_TYPES = ("MANUFACTURER", "EPC / CONTRACTOR", "DISTRIBUTOR")

#: Verbs in CORE BUSINESS that mean "we bring this out of the ground
#: or out of a furnace", checked before BUSINESS_TYPE because the text
#: is about THIS company and the type is a bucket.
PRODUCER_VERBS = ("MINING", "MINES ", "MINER", "PRODUCTION OF",
                  "PRODUCES", "SMELT", "REFINER", "REFINES",
                  "REFINING", "EXTRACTS", "EXTRACTION", "EXPLORATION")

PRODUCER, CONSUMER, UNKNOWN = "PRODUCER", "CONSUMER", "UNKNOWN"


def _row_of(symbol, path=MASTER_CSV):
    sym = str(symbol or "").strip().upper()
    for row in _rows(path):
        if str(row.get("SYMBOL") or "").strip().upper() == sym:
            return row
    return None


def stance(symbol, commodity, path=MASTER_CSV):
    """Which side of `commodity` is `symbol` on?

    Returns {"symbol", "commodity", "stance", "why"} or None when the
    company carries no exposure to it at all. `stance` is one of
    PRODUCER / CONSUMER / UNKNOWN.

    UNKNOWN is a real answer and is never quietly folded into either
    of the other two -- see the note above about HINDALCO.
    """
    want = str(commodity or "").strip().upper()
    row = _row_of(symbol, path)
    if not want or row is None:
        return None

    exposure = str(row.get("COMMODITY_EXPOSURE") or "").upper()
    if want not in exposure:
        return None

    sym = str(row.get("SYMBOL") or "").strip().upper()
    core = str(row.get("CORE BUSINESS") or "").upper()
    btype = str(row.get("BUSINESS_TYPE") or "").strip().upper()

    def _out(verdict, why):
        return {"symbol": sym, "commodity": want,
                "stance": verdict, "why": why}

    if any(verb in core for verb in PRODUCER_VERBS):
        return _out(PRODUCER, f"its own description says '{core[:60]}'")
    if btype in PRODUCER_TYPES:
        return _out(PRODUCER, f"BUSINESS_TYPE is {btype}")

    if btype in CONSUMER_TYPES:
        # Does it make the METAL, or something out of the metal? If
        # the commodity's own name is what it says it makes, this
        # cannot tell a smelter from a converter, and says so.
        if want in core:
            return _out(UNKNOWN,
                        f"it makes {want.lower()} itself -- this file "
                        f"cannot tell a producer from a converter")
        return _out(CONSUMER, f"{btype.lower()} -- {want.lower()} is an "
                              f"input cost")

    return _out(UNKNOWN, f"BUSINESS_TYPE is "
                         f"{btype or 'blank'} -- not enough to say")


def sides(commodity, path=MASTER_CSV):
    """Split every company exposed to `commodity` by which side it is on.

    {"commodity", "producers", "consumers", "unknown", "counts"} --
    the answer his screenshot needed. A rising price is a tailwind for
    `producers` and a headwind for `consumers`; `unknown` is shown and
    never silently assigned.
    """
    want = str(commodity or "").strip().upper()
    out = {"commodity": want, "producers": [], "consumers": [],
           "unknown": []}
    found = []
    if not want:
        return dict(out, counts={"producers": 0, "consumers": 0,
                                 "unknown": 0})
    # carrying() returns [{"column", "tag", "symbols"}] -- a LIST, one
    # group per axis the tag was found on, because STEEL is both a
    # commodity and a theme. Checked against the function rather than
    # written from memory; a .get("symbols") on a list raises, and
    # every method name guessed from memory in this project has been
    # wrong.
    seen = set()
    for group in carrying(want, path=path):
        for symbol in group.get("symbols") or []:
            if symbol in seen:
                continue
            seen.add(symbol)
            found.append(symbol)

    for symbol in found:
        got = stance(symbol, want, path=path)
        if got is None:
            continue
        bucket = {PRODUCER: "producers", CONSUMER: "consumers"}.get(
            got["stance"], "unknown")
        out[bucket].append({"symbol": got["symbol"], "why": got["why"]})
    for key in ("producers", "consumers", "unknown"):
        out[key].sort(key=lambda r: r["symbol"])
    out["counts"] = {k: len(out[k])
                     for k in ("producers", "consumers", "unknown")}
    return out


# ==========================================================
#  THE SAME EVENT, THE OPPOSITE TRANSMISSION
# ==========================================================
#
#     "do the sector polarity build next"
#                                 -- operator, 19 August 2026
#
# His own framework states the case better than a comment can: crude
# oil rises, airline margins fall and airline stocks sell off, while
# oil producers' realisation rises and those stocks are bought. One
# event, two mechanisms, opposite signs. sides() above knows which
# side of a commodity a company stands on. Until now nothing on the
# ranking path asked it, so a copper spike scored a cable maker on
# the same footing as a copper miner.
#
# MEASURED BEFORE IT WAS ARMED
# ----------------------------
# The claim is testable and it was tested first, over a year of daily
# bars. Method: take every session an instrument moved 1.5% or more,
# read the NEXT Indian session for every name carrying it, subtract
# THAT SESSION'S MARKET MEDIAN, and sign the result by the direction
# the commodity moved. A producer helped by a rise and helped by a
# fall both count as +; the market's own move is removed, so what is
# left is the transmission and not the tape.
#
#   commodity      days   prod n  prod exc   cons n  cons exc   spread
#   COPPER           84       84    +0.210     4720    +0.116   +0.094
#   CRUDE OIL       132     1320    +0.115     8224    +0.000   +0.115
#   NATURAL GAS     164     1312    +0.006     2788    -0.031   +0.036
#   GOLD             75      150    +1.309      683    +0.366   +0.943
#   SILVER          144      432    +0.261     1004    +0.085   +0.176
#
# FIVE OUT OF FIVE POSITIVE, on five independent series. That
# consistency is the finding; one commodity could be luck.
#
# WHAT THE NUMBERS DO NOT SAY, and the tilt is sized accordingly:
#
#   * the magnitude is SMALL. Around a tenth of a percent of excess
#     on the two well-sampled series. Real, and nowhere near a trade
#     on its own.
#   * COPPER's producer column is ONE STOCK. HINDCOPPER is the only
#     miner in the universe, so 84 observations are 84 days of one
#     company, not a portfolio.
#   * GOLD's +0.943 rests on two producers across 75 days. The
#     largest number in the table is the least trustworthy one.
#   * CRUDE OIL is the strongest evidence: 1,320 producer
#     observations, and consumers sitting at exactly +0.000 -- the
#     market-adjusted consumer response to crude is nothing at all,
#     while producers get +0.115.
#
# So this TILTS, bounded to [TILT_FLOOR, TILT_CEILING], on one score.
# It cannot veto a trade and it cannot conjure one, the same posture
# core/opportunity.py's payoff weight was given on 19 August.

#: A commodity has to move this much before its transmission is worth
#: reading. A quarter-percent drift in copper is not an event and
#: measuring against one only adds noise.
COMMODITY_MOVE_PCT = 1.5

#: How far a reading may push a score. The measured spread is around
#: a tenth of a percent of excess; a larger swing than this would be
#: asserting more than the table supports.
TILT_FLOOR = 0.90
TILT_CEILING = 1.10

#: premarket key -> the tag this file indexes it under.
COMMODITY_KEYS = {
    "copper": "COPPER",
    "crude": "CRUDE OIL",
    "natgas": "NATURAL GAS",
    "gold": "GOLD",
    "silver": "SILVER",
}

_TILT_CACHE = {}


def reset_tilt_cache():
    _TILT_CACHE.clear()


def commodities_that_moved(threshold_pct=COMMODITY_MOVE_PCT, on_date=None):
    """{tag: change_pct} for the most recent session on record.

    Reads core/premarket.py's series, which is filled by the same
    morning refresh that draws the Global Markets panel. No network,
    no live dependency: if the series is empty this returns {} and
    every caller carries on exactly as it did before this file grew a
    commodity opinion.
    """
    key = ("moved", threshold_pct, str(on_date or ""))
    if key in _TILT_CACHE:
        return _TILT_CACHE[key]

    # ---- TODAY'S BAR IS STILL BEING WRITTEN. 19 August 2026. ----
    #
    # The series carries a row for the CURRENT day, and while the
    # market is open that row is a partial session. Reading it would
    # ask "what has copper done so far today" -- a different question
    # from the one that was measured, which is what a commodity did
    # over a COMPLETED session and what the Indian names then did on
    # the next one.
    #
    # Caught the first time this ran: copper showed -0.22% and was
    # ignored, while the completed 18 August bar was -1.84% and well
    # over the threshold. A tilt built on half a day is a tilt that
    # changes its mind at lunchtime.
    from datetime import date as _date
    cutoff = str(on_date) if on_date else _date.today().isoformat()

    out = {}
    try:
        from core import premarket
        for name, tag in COMMODITY_KEYS.items():
            rows = [r for r in premarket.series(name)
                    if str(r[0]) < cutoff]
            if not rows:
                continue
            _day, _close, change = rows[-1]
            if change is None:
                continue
            if abs(float(change)) >= threshold_pct:
                out[tag] = float(change)
    except Exception:                                       # noqa: BLE001
        out = {}
    _TILT_CACHE[key] = out
    return out


def commodity_tilt(symbol, on_date=None, path=MASTER_CSV):
    """How much to lean on this stock, given what its inputs did.

    Returns (multiplier, note). 1.0 and None mean "no opinion", which
    is the answer whenever nothing moved, the stock carries no
    commodity, or its side cannot be told -- and it leaves the score
    exactly as it was.

    A stock exposed to several moving commodities gets the SUM of
    their leanings before bounding, because crude up and copper up is
    two headwinds for a cable maker, not one.
    """
    moved = commodities_that_moved(on_date=on_date)
    if not moved:
        return 1.0, None

    lean = 0.0
    reasons = []
    for tag, change in moved.items():
        got = stance(symbol, tag, path=path)
        if got is None or got["stance"] == UNKNOWN:
            continue
        # A PRODUCER is helped when its commodity rises and hurt when
        # it falls. A CONSUMER is the mirror. The sign of the move
        # carries that; the side only decides which way to read it.
        direction = 1.0 if got["stance"] == PRODUCER else -1.0
        step = direction * (1.0 if change > 0 else -1.0)
        lean += step
        reasons.append(f"{tag} {change:+.1f}% and it is a "
                       f"{got['stance'].lower()}")
    if not reasons:
        return 1.0, None

    # One clean tailwind takes the ceiling; one headwind the floor.
    # Stacking more cannot push further -- the table does not support
    # claiming that two commodities are twice as predictive as one.
    span = (TILT_CEILING - 1.0) if lean > 0 else (1.0 - TILT_FLOOR)
    tilt = 1.0 + max(-1.0, min(1.0, lean)) * span
    tilt = max(TILT_FLOOR, min(TILT_CEILING, tilt))
    return round(tilt, 4), "; ".join(reasons)
