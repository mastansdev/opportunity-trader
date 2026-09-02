"""
==========================================================
High-conviction news -- only what can move a stock
==========================================================

WHY THIS EXISTS, AND WHY THE LAST ONE WAS DELETED
--------------------------------------------------
The previous news subsystem (~3,200 lines) was deleted on 2026-07-26 on
the operator's instruction:

    "NO PLACE FOR ANY ITEM/FILE WHICH DOESN'T PROVIDE ENOUGH TOWARDS
     GOAL REACHING BY BOT."

It compiled 750 symbols into regex indices and ran a background thread
through every live session, and nothing read the result. CPU spent
during trading for zero decisions.

Then, the same day, the operator asked for it back with a far tighter
brief: news, but ONLY key events that can move a stock.

THE GAP THIS FILLS -- measured on the real session of 2026-07-27
-----------------------------------------------------------------
core/announcement_watcher.py reads EXCHANGE FILINGS. It would not have
seen either of the day's two biggest single moves:

    GANDHAR    -11.6%   flood damage at its Silvassa plant
    CARTRADE   +10.8%   UBS initiated Buy, target Rs 4,000 vs Rs 2,700

Neither is a regulatory disclosure. The first is a news story, the
second is a broker note. The best and worst movers of the day were both
invisible to a filings-only feed.

WHAT COUNTS AS HIGH CONVICTION
------------------------------
A named company, plus a concrete event that changes what the business is
worth. Nine categories, all drawn from real moves:

    DISASTER      fire, flood, blast, accident, plant shutdown
    BROKER        initiation, target price, upgrade/downgrade
    REGULATORY    ban, penalty, SEBI/RBI action, USFDA warning letter
    ORDER_WIN     contract or order of a stated size
    DEAL          acquisition, merger, stake sale, block deal
    MANAGEMENT    CEO/MD/CFO exit, promoter selling
    FUND_RAISE    QIP, preferential issue, rights
    GUIDANCE      raises/cuts outlook
    LEGAL         court ruling, arbitration award, insolvency

WHAT IS DELIBERATELY THROWN AWAY
--------------------------------
"Stock in focus today", "should you buy", "technical view", "multibagger",
"top picks", anything without a named company and a concrete event. The
previous system's failure was volume without decisions; the filter here
is severe on purpose. Missing a marginal story costs nothing. Filling
the panel with noise costs the panel.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import re
import threading
from datetime import datetime, timedelta
from urllib.parse import urlparse
from xml.etree import ElementTree

from core.logger import decision, diagnostic, warn

MASTER_CSV = os.path.join("data", "master_stocks.csv")

# RSS, because it is public, cheap, needs no key, and every Indian
# financial desk publishes it. Deliberately a small list -- more sources
# means more duplicates, not more signal.
DEFAULT_FEEDS = [
    "https://www.moneycontrol.com/rss/buzzingstocks.xml",
    "https://www.moneycontrol.com/rss/results.xml",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
]

# ---------------------------------------------------------------
# WHAT MOVES A STOCK. Ordered -- first match wins, so specific first.
# ---------------------------------------------------------------
IMPACT = [
    ("DISASTER", re.compile(
        r"\bfire\b|\bblaze\b|\bflood|\bblast\b|explosion|\bmishap\b|"
        r"\baccident\b|plant\s+(shut|halt|clos)|production\s+(halt|suspend)|"
        r"\bearthquake\b|\bcyclone\b|damage\s+to\s+(plant|factory|unit)", re.I)),
    ("REGULATORY", re.compile(
        r"\bSEBI\b|\bRBI\b\s+(action|bars|penal|restrict)|\bban(s|ned|)\b|"
        r"penalt|show\s+cause|licen[cs]e\s+(cancel|suspend|revok)|"
        r"USFDA\s+(observation|warning|Form\s*483|import\s+alert)|"
        r"warning\s+letter|\bimport\s+alert\b|regulatory\s+action", re.I)),
    # A broker NAME alone is not a broker call. Live on 2026-07-28 this
    # tagged "Kotak Mahindra Bank taps HSBC and CTBC for $600-million
    # overseas loan" as BROKER -- HSBC was the LENDER. So the house must
    # appear beside an analyst action, or the action must stand alone.
    ("BROKER", re.compile(
        r"initiat(es|ed|ing)\s+coverage|target\s+price|price\s+target|"
        r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|raises?\s+target|cuts?\s+target|"
        r"\b(?:UBS|Jefferies|Morgan\s+Stanley|Goldman|CLSA|Nomura|Citi|"
        r"Macquarie|Bernstein|HSBC|JP\s*Morgan|Motilal|ICICI\s+Securities|"
        r"Kotak\s+Institutional|Emkay|Axis\s+Capital)\b"
        r"(?=.{0,60}?\b(?:buy|sell|hold|neutral|outperform|underperform|"
        r"overweight|underweight|rating|rates?|target|initiat|upgrad|"
        r"downgrad|coverage|reiterat|maintains?)\b)", re.I)),
    ("LEGAL", re.compile(
        r"\bNCLT\b|insolvenc|arbitration\s+award|court\s+(rules|orders|"
        r"verdict)|tribunal|\bwins?\s+(case|appeal)\b|adverse\s+(order|ruling)",
        re.I)),
    ("ORDER_WIN", re.compile(
        r"\b(bags?|wins?|secures?|receives?|awarded)\b.{0,40}"
        r"\b(order|contract|project|tender|LOI|letter\s+of\s+intent)\b|"
        r"order\s+(worth|book)\s+", re.I)),
    ("DEAL", re.compile(
        r"acqui(re|res|red|sition)|\bmerger\b|amalgamat|stake\s+(sale|buy|"
        r"purchase)|block\s+deal|bulk\s+deal|divest|joint\s+venture|"
        r"\bopen\s+offer\b|takeover", re.I)),
    ("MANAGEMENT", re.compile(
        r"\b(CEO|MD|CFO|Chairman|Managing\s+Director)\b.{0,30}"
        r"\b(resign|quits?|steps?\s+down|exits?|appoint)|"
        r"promoter[s]?\s+(sell|sold|offload|pledge)", re.I)),
    ("FUND_RAISE", re.compile(
        r"\bQIP\b|qualified\s+institutional|preferential\s+(issue|allot)|"
        r"rights\s+issue|fund\s*rais|raises?\s+Rs\s*[\d,]+\s*(cr|crore)", re.I)),
    ("GUIDANCE", re.compile(
        r"\b(raises?|cuts?|lowers?|hikes?|trims?)\b.{0,20}?"
        r"\b(guidance|outlook|forecast|estimate)\b|profit\s+warning", re.I)),
]

# Opinion, listicles, and daily filler. Checked FIRST -- a headline that
# matches any of these is discarded whatever else it contains, because
# "Stock in focus: XYZ bags order" is a column, not an event.
NOISE = re.compile(
    r"stocks?\s+(to\s+watch|in\s+focus|in\s+news)|should\s+you\s+(buy|sell)|"
    r"technical\s+(view|call|pick)|multibagger|top\s+\d+\s+(picks?|stocks?|bets?)|"
    r"\bwhy\s+(you|to)\b|here'?s\s+what|\bexpert[s]?\s+(say|view)|"
    r"trading\s+(strategy|idea|call)|\bF&O\b|\bmuhurat\b|\bhoroscope\b|"
    r"\bopinion\b|\bcolumn\b|market\s+(wrap|close|open|live\s+updates)|"
    r"sensex|nifty\s+(today|closes|opens)", re.I)

# Capitalised words that routinely START a headline or a clause and so
# do NOT indicate the following word is part of a longer company name.
_LEAD_WORDS = {
    "the", "a", "an", "why", "how", "after", "as", "on", "in", "at", "for",
    "and", "but", "with", "from", "india", "indian", "shares", "stock",
    "stocks", "buy", "sell", "hold", "up", "down", "q1", "q2", "q3", "q4",
}

# Company suffixes that never help a match.
_SUFFIX = re.compile(
    r"\b(limited|ltd|private|pvt|corporation|corp|company|co|india|"
    r"industries|enterprises|holdings|group|the)\b\.?", re.I)


def _clean_name(name):
    n = re.sub(r"\(.*?\)", " ", str(name or ""))
    n = _SUFFIX.sub(" ", n)
    n = re.sub(r"[^A-Za-z0-9&\s]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def build_name_index(csv_path=MASTER_CSV):
    """{searchable phrase -> SYMBOL}, longest phrase first when matching.

    'GANDHAR OIL REFINERY (INDIA) LIMITED' -> 'GANDHAR OIL REFINERY'
    so a headline saying "Gandhar Oil Refinery" resolves to GANDHAR.
    """
    index = {}
    if not os.path.exists(csv_path):
        warn(f"[NEWSFEED] {csv_path} missing -- cannot match companies.")
        return index
    try:
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                symbol = (row.get("SYMBOL") or "").strip().upper()
                name = _clean_name(row.get("COMPANY NAME"))
                if not symbol:
                    continue
                # Two-word minimum on names: single words like "ROUTE" or
                # "AXIS" appear in ordinary English and would match
                # everything.
                if name and len(name.split()) >= 2:
                    index[name.lower()] = symbol
                    first_two = " ".join(name.split()[:2]).lower()
                    index.setdefault(first_two, symbol)
                # A BARE TICKER is only safe to match case-insensitively
                # when it is long enough not to be an English word.
                # 'ROUTE' (Route Mobile) and 'AXIS' and 'TRENT' are all
                # real symbols and real words; matching them lowercase
                # would tag every headline containing "the route to...".
                # Anything shorter is still matched, but only in CAPITALS
                # in the original headline -- which is how a ticker
                # actually appears in print.
                if len(symbol) >= 7:
                    index.setdefault(symbol.lower(), symbol)
                else:
                    index.setdefault(symbol, symbol)      # case-sensitive
    except Exception as exc:                               # noqa: BLE001
        warn(f"[NEWSFEED] Could not read the master list: {exc}")
    return index


# ---------------------------------------------------------------
# WHICH WAY DOES IT CUT?
# ---------------------------------------------------------------
# 31 July 2026. The operator's own dashboard, row 8:
#
#     BAJFINANCE  up 8.10%  score 20.1
#       NEWS BROKER: UBS issues 'sell' tag on Bajaj Finance
#
# UBS said SELL. The bot read it, matched it to the right company,
# printed it on screen -- and added +4.0, because BROKER was a flat
# score. An upgrade and a downgrade were worth exactly the same.
#
# Four of the nine categories have this defect, and all four are
# categories where the SAME event type can be good news or bad:
#
#     BROKER      upgrade  <-> downgrade          was +4.0 either way
#     GUIDANCE    raises   <-> cuts               was +3.0 either way
#     LEGAL       wins case <-> insolvency        was -4.0 either way
#     MANAGEMENT  appoints <-> CEO resigns        was -2.0 either way
#
# "Tata Power cuts FY27 guidance" scored the same as raising it.
# "Company wins arbitration award" scored NEGATIVE, because the LEGAL
# category assumed courts are bad news.
#
# The category says WHAT happened. This says which way it points. The
# two are separate questions and were being answered by one number.
#
# ORDER IS DELIBERATE. The explicit analyst ACTION is read before any
# rating word, because "downgrades to Hold from Buy" contains "Buy" --
# the old rating, not the new one. Checking rating words first would
# read that as good news.
_BROKER_STANCE = [
    (re.compile(r"\bdowngrade", re.I), "NEGATIVE"),
    (re.compile(r"\bupgrade", re.I), "POSITIVE"),
    (re.compile(r"\b(cuts?|lowers?|trims?|slashe[sd]?|reduces?)\b.{0,30}?"
                r"\b(target|price\s+target|\bPT\b)", re.I), "NEGATIVE"),
    (re.compile(r"\b(raises?|hikes?|lifts?|ups|boosts?)\b.{0,30}?"
                r"\b(target|price\s+target|\bPT\b)", re.I), "POSITIVE"),
    (re.compile(r"\b(sell|underperform|underweight|reduce)\b", re.I),
     "NEGATIVE"),
    (re.compile(r"\b(buy|outperform|overweight|accumulate|top\s+pick)\b",
                re.I), "POSITIVE"),
    (re.compile(r"\b(hold|neutral|equal\s*-?\s*weight|maintains?|"
                r"reiterat)\b", re.I), "NEUTRAL"),
]

_GUIDANCE_STANCE = [
    (re.compile(r"profit\s+warning|\b(cuts?|lowers?|trims?|slashe[sd]?|"
                r"reduces?|scales?\s+back|withdraws?)\b", re.I), "NEGATIVE"),
    (re.compile(r"\b(raises?|hikes?|lifts?|upgrades?|boosts?|"
                r"increases?)\b", re.I), "POSITIVE"),
]

# The old rule read every court story as a disaster. An arbitration
# award WON is a cash inflow and among the better things that can
# happen to a mid-cap.
_LEGAL_STANCE = [
    (re.compile(r"\b(insolvenc|NCLT\s+admits|adverse|against\s+the\s+"
                r"company|loses?\b|dismisse[sd]|penalt|contempt)", re.I),
     "NEGATIVE"),
    (re.compile(r"\b(wins?|won|favou?rable|in\s+(its|the\s+company'?s)\s+"
                r"favou?r|relief|quashe[sd]|set\s+aside|award(ed)?\s+"
                r"(Rs|damages))", re.I), "POSITIVE"),
]

# \b after "resign" does NOT match "resigns" -- there is no boundary
# between n and s. The first version of this scored "Infosys CFO
# resigns with immediate effect" as NEUTRAL, which is the exact class
# of silent miss this whole change is meant to remove. Suffixed with
# \w* wherever the verb inflects.
_MANAGEMENT_STANCE = [
    (re.compile(r"\b(resign\w*|quit\w*|steps?\s+down|stepping\s+down|"
                r"exit\w*|ousted|sacked|terminated|offload\w*|"
                r"pledg\w*|sells?\s+stake|stake\s+sale)\b", re.I),
     "NEGATIVE"),
    (re.compile(r"\b(appoint\w*|elevat\w*|names?\s+new|hire[sd]?|"
                r"inducts?)\b", re.I), "POSITIVE"),
]

STANCE_RULES = {
    "BROKER": _BROKER_STANCE,
    "GUIDANCE": _GUIDANCE_STANCE,
    "LEGAL": _LEGAL_STANCE,
    "MANAGEMENT": _MANAGEMENT_STANCE,
}


def classify_stance(kind, headline):
    """POSITIVE, NEGATIVE or NEUTRAL for the four two-way categories.

    Returns None for the five categories whose sign is fixed by the
    category itself -- a fire is never good news, an order win is never
    bad -- so the caller knows to use the flat score for those.

    NEUTRAL is a real answer, not a failure. "Jefferies maintains Hold"
    is a genuine non-event and must score near zero rather than being
    guessed either way.
    """
    rules = STANCE_RULES.get(kind)
    if rules is None:
        return None
    text = str(headline or "")
    for pattern, stance in rules:
        if pattern.search(text):
            return stance
    return "NEUTRAL"


def classify_impact(headline):
    """Which of the nine categories, or None for anything that is not a
    concrete event. Noise is checked first and wins."""
    text = str(headline or "")
    if not text.strip() or NOISE.search(text):
        return None
    for kind, pattern in IMPACT:
        if pattern.search(text):
            return kind
    return None


_CAMEL_TAG = re.compile(r"#([A-Za-z][A-Za-z0-9]*)")
_HAS_CAMEL = re.compile(r"#[A-Za-z]*[a-z][A-Z]")


def expand_hashtags(headline):
    """#PersistentSystems -> " Persistent Systems ".

    The feeds write the company as one camelCase word behind a hash.
    match_symbols() strips the hash and is left with a single token no
    index key can equal, so the stock is named in plain sight and the
    event is stored with no ticker at all.
    """
    return _CAMEL_TAG.sub(
        lambda m: " " + re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(1)) + " ",
        str(headline or ""))


def match_symbols(headline, index, limit=3):
    """Symbols named in a headline. Longest phrases first so 'TATA POWER'
    beats 'TATA'.

    Keys that are already UPPERCASE are matched case-SENSITIVELY -- they
    are short tickers that double as English words (ROUTE, AXIS, TRENT).
    See build_name_index() for why.

    ==========================================================
    CAMELCASE HASHTAGS.  2 September 2026.
    ==========================================================

        "fix the ticker matching first"          -- the operator

    4,389 of 18,134 stored events carry no ticker. Most of that is
    correct -- Trump, the Strait of Hormuz, the RBI governor, a
    windfall-tax cut -- news with no single listed company in it.

    But the feeds also write "#EicherMotorsRE", "#AurobindoPharma",
    "#GardenReachShipbuilders", and those ARE the company. Stripping
    the hash leaves one token that equals no index key, so the stock
    is named in plain sight and stored as unmatched.

    MEASURED BEFORE IT WAS WRITTEN, across all 4,389:

        70 headlines gain a match from the expansion
        69 of them resolve to exactly ONE symbol -- all correct on
           inspection: EICHERMOT, AUROPHARMA, GRSE, BAJAJ-AUTO,
           NORTHARC, MFSL, FINOPB, APOLLOPIPE, CGCL, PARKHOSPS...
         1 resolves to two, and that one is the false positive:
           "#KalyanJewellers Gets #TamilNadu Contract" matched
           KALYANKJIL and TNPL -- Tamil Nadu Newsprint, a state name
           read as a company

    So the expansion is trusted ONLY when it names exactly one stock.
    That takes the 69 and drops the 1, and the error rate is a
    measurement rather than a hope -- which is what was missing from
    the last attempt at this.

    A headline that already matched is untouched: the expansion only
    runs when the ordinary pass found nothing, so nothing that works
    today can change.
    """
    raw = " " + re.sub(r"[^A-Za-z0-9&\s]", " ", str(headline or "")) + " "
    text = raw.lower()
    hits, used = [], []
    for phrase in sorted(index, key=len, reverse=True):
        if len(phrase) < 4:
            continue
        if any(phrase in u for u in used):
            continue
        haystack = raw if phrase.isupper() else text
        pos = haystack.find(f" {phrase} ")
        if pos < 0:
            continue
        # A SINGLE-WORD match that is preceded by another capitalised
        # word belongs to a longer proper noun, not to us. Live on
        # 2026-07-28: "Gujarat State Petronet falls sharply" matched
        # PETRONET -- Petronet LNG -- because Gujarat State Petronet
        # (GSPL) is not in this universe at all. Acting on that would
        # have meant buying the wrong company.
        if " " not in phrase:
            before = raw[:pos].rstrip().split()
            if before and before[-1][:1].isupper() and before[-1].lower() not in _LEAD_WORDS:
                continue
        symbol = index[phrase]
        if symbol not in hits:
            hits.append(symbol)
            used.append(phrase)
        if len(hits) >= limit:
            break

    if not hits and _HAS_CAMEL.search(str(headline or "")):
        widened = match_symbols(expand_hashtags(headline), index, limit=limit)
        # Exactly one, or not at all. See the note above: the only
        # multi-match in 4,389 events was the only wrong one.
        if len(widened) == 1:
            return widened
    return hits


def parse_rss(xml_text):
    """[(title, link, published)] from an RSS or Atom document."""
    out = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return out
    for item in root.iter():
        tag = item.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = pub = ""
        for child in item:
            ctag = child.tag.split("}")[-1]
            if ctag == "title":
                title = (child.text or "").strip()
            elif ctag == "link":
                link = (child.text or child.attrib.get("href") or "").strip()
            elif ctag in ("pubDate", "published", "updated"):
                pub = (child.text or "").strip()
        if title:
            out.append((title, link, pub))
    return out


class NewsWatcher:
    """Poll RSS, keep only high-conviction items about our symbols."""

    def __init__(self, feeds=None, poll_seconds=180, fetcher=None,
                 csv_path=MASTER_CSV, known_symbols=None, store=None):
        # See core/feed_store.py. The collector passes one; main.py
        # passes nothing and nothing about this class changes.
        self.store = store
        self.feeds = list(feeds or DEFAULT_FEEDS)
        self.poll_seconds = poll_seconds
        self._fetcher = fetcher or self._fetch_http
        self.index = build_name_index(csv_path)
        if known_symbols:
            keep = {str(s).upper() for s in known_symbols}
            self.index = {k: v for k, v in self.index.items() if v in keep}
        self._lock = threading.Lock()
        self._seen = set()
        self._items = []
        self._by_symbol = {}
        self._last_poll_at = None
        self._last_error = None
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _fetch_http(url):
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0 Safari/537.36")})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")

    def poll_once(self):
        fresh, errors = [], []
        now = datetime.now()
        for url in self.feeds:
            try:
                xml_text = self._fetcher(url)
            except Exception as exc:                       # noqa: BLE001
                errors.append(f"{urlparse(url).netloc}: {str(exc)[:40]}")
                continue
            for title, link, pub in parse_rss(xml_text):
                key = title.strip().lower()[:160]
                with self._lock:
                    if key in self._seen:
                        continue
                    self._seen.add(key)
                kind = classify_impact(title)
                if kind is None:
                    continue
                symbols = match_symbols(title, self.index)
                if not symbols:
                    continue                    # no named company we trade
                fresh.append({
                    "symbols": symbols, "symbol": symbols[0], "kind": kind,
                    "stance": classify_stance(kind, title),
                    "headline": title[:240], "link": link,
                    "source": urlparse(url).netloc.replace("www.", ""),
                    "seen_at": now.strftime("%H:%M:%S"), "published": pub[:31],
                })
        if fresh and self.store is not None:
            self.store.save("news", fresh,
                            lambda r: r.get("link")
                                      or f"{r.get('symbol')}|"
                                         f"{(r.get('headline') or '')[:90]}")
        with self._lock:
            # ---- NEWEST FIRST, ACROSS ALL FEEDS. 3 August 2026. ----
            #
            #   "news & FILED not arranged properly"
            #
            # Prepending each poll's batch made the BATCHES newest-first
            # and left the items INSIDE a batch in whatever order the
            # feeds were walked. Several sources are polled together, so
            # a 09:12 item from the third feed sat above a 09:41 item
            # from the first, and the panel looked shuffled.
            #
            # core/announcement_watcher.py already did this correctly --
            # it sorts on _filed_dt after prepending. This is the same
            # two lines, which is what makes the omission worse.
            self._items = fresh + self._items
            self._items.sort(key=lambda r: (r.get("published") or "",
                                            r.get("seen_at") or ""),
                             reverse=True)
            self._items = self._items[:200]
            for r in fresh:
                for s in r["symbols"]:
                    self._by_symbol.setdefault(s, r)
            self._last_poll_at = now
            self._last_error = "; ".join(errors) if errors else None
        for r in fresh:
            # The stance is printed because the operator reads this log
            # live. "BROKER" told him a broker said something;
            # "BROKER/NEGATIVE" tells him what.
            tag = (f"{r['kind']}/{r['stance']}" if r.get("stance")
                   else r["kind"])
            decision(f"[NEWSFEED] {'/'.join(r['symbols'])} -- {tag}: "
                     f"{r['headline'][:100]}")
        return fresh

    # --- thread ---------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="news-watcher",
                                        daemon=True)
        self._thread.start()
        decision(f"[NEWSFEED] Watching {len(self.feeds)} feeds every "
                 f"{self.poll_seconds}s for high-impact events.")

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:                       # noqa: BLE001
                warn(f"[NEWSFEED] Loop error (continuing): {exc}")
            self._stop.wait(self.poll_seconds)
        diagnostic("[NEWSFEED] Stopped.")

    def stop(self, timeout=3):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # --- read -----------------------------------------------------

    def for_symbol(self, symbol):
        with self._lock:
            return self._by_symbol.get(str(symbol).upper())

    def snapshot(self, limit=25):
        with self._lock:
            return {"rows": list(self._items[:limit]),
                    "count_today": len(self._items),
                    "last_poll_at": (self._last_poll_at.strftime("%H:%M:%S")
                                     if self._last_poll_at else None),
                    "error": self._last_error,
                    "available": True}
