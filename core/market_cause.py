"""
==========================================================
Why the whole market is moving
==========================================================

---- 15 September 2026. ----

    "as of now market is in sell mode. lets see . does bot knows any
     specific reason triggered all markets are falling ? if bot doesn't
     know then its still needs upgrade"
    "Yes, thats real build & it must not slow down my bot trading"
                                                    -- the operator

The bot already HOLDS every piece of this and never put them together:

    index ticks      NIFTY, BANKNIFTY, VIX            core/index_monitor
    sector moves     every sector's average today     dashboard sectors_all
    market stories   MACRO / FLOW rows, scope MARKET  core/stock_events
                     (3,700+ stored, no stock attached -- the Fed, crude,
                     the rupee, bond yields, war news)
    FII / DII        the day's institutional flow     core/market_flows

That morning the stories were all on disk: "Indian Rupee weakened ...
rising crude oil prices and anticipation of a US Fed rate hike", "global
bond market selloff, persistent inflation, and rising oil prices". The
bot was reading them one stock at a time and had no question to ask of
them about the market.

WHAT THIS DOES. Groups the last few hours of market stories by the
driver they name (crude, US Fed, bond yields, rupee, FII selling, global
markets, geopolitics, inflation, RBI, government policy), counts how many
separate stories name each, and hands back the top drivers with their
latest headline -- next to what the market is actually doing.

WHAT IT DOES NOT DO. It never changes a trade. It is a reading for the
desk. It is also not a verdict on cause: a driver named by five stories
while NIFTY falls is the best available explanation, not a proof, and the
sentence says "the stories today point to", not "because".

COST. Pure function over data already in memory plus ONE read-only
SQLite query, cached for 60 seconds by the caller. It never runs on the
tick path or in the entry loop.

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import datetime, timedelta, timezone

#: How far back a market story is still "today's reason". Stories older
#: than this describe a morning that has already been priced.
LOOK_BACK_HOURS = 4

#: Driver -> the words that name it. Matched on word boundaries,
#: case-insensitive. Kept to what Indian market channels actually write.
DRIVERS = {
    "Crude oil": (r"crude", r"brent", r"oil prices?", r"opec"),
    "US Fed / US rates": (r"fed\b", r"federal reserve", r"fomc", r"powell",
                          r"us rates?", r"rate hike", r"rate cut"),
    "Bond yields": (r"bond yields?", r"bond market", r"treasur(y|ies)",
                    r"bonds? (fell|sell ?off|slump)", r"yields? (rise|rose|jump|surge)"),
    "Rupee / dollar": (r"rupee", r"dollar index", r"usd ?/ ?inr", r"dxy"),
    "FII selling / flows": (r"fii", r"fpi", r"foreign (institutional )?investors?",
                            r"foreign outflows?", r"dii"),
    "Global markets": (r"wall street", r"dow jones", r"\bdow\b", r"nasdaq",
                       r"s&p ?500", r"nikkei", r"hang seng", r"asian markets?",
                       r"global markets?", r"gift nifty", r"sgx nifty",
                       r"global (cues|selloff|sell-off)"),
    "War / geopolitics": (r"\bwar\b", r"missile", r"drone strikes?", r"attack",
                          r"sanctions?", r"geopolitical", r"ceasefire",
                          r"military", r"airstrikes?"),
    "Inflation": (r"inflation", r"\bcpi\b", r"\bwpi\b"),
    "RBI": (r"\brbi\b", r"repo rate", r"monetary policy"),
    "Government policy / tax": (r"\bgst\b", r"tariffs?", r"\bbudget\b", r"\bsebi\b",
                                r"\bstt\b", r"capital gains tax"),
}

_COMPILED = {name: [re.compile(r"(?<![a-z])" + p, re.I) for p in pats]
             for name, pats in DRIVERS.items()}

_FALL_WORDS = re.compile(
    r"\b(fall|fell|falls|falling|slump|slumps|selloff|sell-off|sell off|"
    r"decline|declines|declined|drop|drops|dropped|plunge|plunged|crash|"
    r"weak|weaken|weakened|tumble|tumbled|slide|slid|outflow|outflows|"
    r"hike|concern|concerns|fears?|pressure)\b", re.I)
_RISE_WORDS = re.compile(
    r"\b(rise|rose|rises|rising|rally|rallied|gain|gains|gained|surge|"
    r"surged|jump|jumped|recover|recovered|strong|strengthen|inflow|"
    r"inflows|cut|eases?|eased|record high)\b", re.I)


def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _parse_at(value):
    """Stored 'at' is ISO, usually UTC with +00:00. Returns aware UTC."""
    if not value:
        return None
    try:
        got = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if got.tzinfo is None:
        # A naive stamp in this store is the local (IST) clock.
        got = got.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return got.astimezone(timezone.utc)


def _clean(headline):
    text = re.sub(r"[^\w\s%$.,:&/-]", " ", str(headline or ""))
    return re.sub(r"\s+", " ", text).strip()


def market_now(indices=None, sectors=None, flows=None):
    """What the market is doing, in plain facts. Never raises."""
    out = {"nifty_pct": None, "banknifty_pct": None, "vix_pct": None,
           "sectors_up": 0, "sectors_down": 0, "direction": None,
           "fii": None, "dii": None}
    indices = indices or {}
    for key, name in (("nifty_pct", "nifty"), ("banknifty_pct", "banknifty"),
                      ("vix_pct", "vix")):
        row = indices.get(name) or {}
        # A REST close (before the open, after the close) is not a live
        # move: on 15 Sep at 23:08 it read NIFTY +0.00% beside 29 sectors
        # down, and the card said "mixed". Only a live tick is today's move.
        if row.get("from_rest") or not row.get("available", True):
            continue
        out[key] = _f(row.get("pct"))
    for row in (sectors or []):
        move = _f((row or {}).get("avg_change_pct"))
        if move is None:
            continue
        if move < 0:
            out["sectors_down"] += 1
        elif move > 0:
            out["sectors_up"] += 1
    # FII / DII is an END-OF-DAY figure (NSE publishes after the close),
    # so it is always a finished session, never today's live flow.
    if isinstance(flows, dict) and flows.get("available"):
        out["fii"] = _f(flows.get("fii_cr"))
        out["dii"] = _f(flows.get("dii_cr"))
        out["flows_as_of"] = flows.get("as_of")

    nifty = out["nifty_pct"]
    up, down = out["sectors_up"], out["sectors_down"]
    # Direction only -- no threshold. NIFTY and the majority of sectors
    # must agree; when they do not, the market is mixed.
    if nifty is not None and nifty < 0 and down > up:
        out["direction"] = "FALLING"
    elif nifty is not None and nifty > 0 and up > down:
        out["direction"] = "RISING"
    elif nifty is None and down > up:
        out["direction"] = "FALLING"       # no live index: the sectors say
    elif nifty is None and up > down:
        out["direction"] = "RISING"
    elif nifty is not None or up or down:
        out["direction"] = "MIXED"
    return out


def drivers(stories, now=None, look_back_hours=LOOK_BACK_HOURS,
            direction=None, top=3):
    """[{driver, stories, latest_at, headline}] strongest first.

    `stories`: rows with "at" and "headline" (stock_events MARKET rows).
    Duplicates across channels count once. When `direction` is FALLING
    or RISING, a story whose words point the same way counts double --
    "rupee weakened on crude" explains a fall better than "crude eases".
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=look_back_hours)

    seen = set()
    tally = {}
    for row in (stories or []):
        at = _parse_at((row or {}).get("at"))
        if at is None or at < cutoff or at > now.astimezone(timezone.utc) + timedelta(minutes=5):
            continue
        text = _clean(row.get("headline"))
        if len(text) < 12:
            continue
        key = text.lower()[:70]
        if key in seen:
            continue
        seen.add(key)
        weight = 1.0
        if direction == "FALLING" and _FALL_WORDS.search(text):
            weight = 2.0
        elif direction == "RISING" and _RISE_WORDS.search(text):
            weight = 2.0
        for name, patterns in _COMPILED.items():
            if any(p.search(text) for p in patterns):
                got = tally.setdefault(name, {"driver": name, "stories": 0,
                                              "weight": 0.0, "latest_at": None,
                                              "headline": None})
                got["stories"] += 1
                got["weight"] += weight
                got.setdefault("seen", []).append((at, text[:220]))
                if got["latest_at"] is None or at > got["latest_at"]:
                    got["latest_at"] = at
    ranked = sorted(tally.values(),
                    key=lambda d: (-d["weight"], -d["stories"],
                                   -(d["latest_at"].timestamp() if d["latest_at"] else 0)))
    out, shown = [], set()
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    for d in ranked[:top]:
        # One story often names three drivers ("bond selloff, inflation
        # and rising oil"). Show each driver its own latest story when it
        # has one, so the desk is not the same sentence three times.
        stories_for = sorted(d["seen"], key=lambda x: x[0], reverse=True)
        at, headline = next(((a, h) for a, h in stories_for if h not in shown),
                            stories_for[0])
        shown.add(headline)
        out.append({"driver": d["driver"], "stories": d["stories"],
                    "latest_at": at.astimezone(ist_zone).strftime("%H:%M"),
                    "headline": headline})
    return out


def explain(indices=None, sectors=None, flows=None, stories=None, now=None):
    """The whole reading for the desk. Never raises."""
    try:
        market = market_now(indices, sectors, flows)
        found = drivers(stories, now=now, direction=market["direction"])
        facts = []
        if market["nifty_pct"] is not None:
            facts.append(f"NIFTY {market['nifty_pct']:+.2f}%")
        if market["banknifty_pct"] is not None:
            facts.append(f"BANKNIFTY {market['banknifty_pct']:+.2f}%")
        if market["vix_pct"] is not None:
            facts.append(f"VIX {market['vix_pct']:+.1f}%")
        if market["sectors_up"] or market["sectors_down"]:
            facts.append(f"{market['sectors_down']} sectors down, "
                         f"{market['sectors_up']} up")
        if market["fii"] is not None:
            facts.append(f"FII {market['fii']:+,.0f} cr, DII "
                         + (f"{market['dii']:+,.0f} cr" if market["dii"] is not None else "?")
                         + f" (end of day{', ' + str(market['flows_as_of']) if market.get('flows_as_of') else ''})")
        if found:
            names = ", ".join(d["driver"] for d in found)
            verb = {"FALLING": "falling", "RISING": "rising"}.get(
                market["direction"], "moving")
            sentence = (f"Market {verb}. Today's market stories point to: "
                        f"{names}.")
        elif market["direction"]:
            sentence = (f"Market {market['direction'].lower()}. No market-wide "
                        f"story in the last {LOOK_BACK_HOURS} hours names a "
                        f"cause -- the bot does not know why yet.")
        else:
            sentence = "No market reading yet."
        return {"available": True, "direction": market["direction"],
                "facts": facts, "sentence": sentence, "drivers": found,
                "market": market}
    except Exception as exc:                               # noqa: BLE001
        return {"available": False, "direction": None, "facts": [],
                "sentence": f"market reading failed ({exc})", "drivers": []}
