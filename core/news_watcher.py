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
    ("BROKER", re.compile(
        r"initiat(es|ed|ing)\s+coverage|target\s+price|price\s+target|"
        r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|raises?\s+target|cuts?\s+target|"
        r"\b(UBS|Jefferies|Morgan\s+Stanley|Goldman|CLSA|Nomura|Citi|"
        r"Macquarie|Bernstein|HSBC|JP\s*Morgan|Motilal|ICICI\s+Securities)\b",
        re.I)),
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


def match_symbols(headline, index, limit=3):
    """Symbols named in a headline. Longest phrases first so 'TATA POWER'
    beats 'TATA'.

    Keys that are already UPPERCASE are matched case-SENSITIVELY -- they
    are short tickers that double as English words (ROUTE, AXIS, TRENT).
    See build_name_index() for why.
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
        if f" {phrase} " in haystack:
            symbol = index[phrase]
            if symbol not in hits:
                hits.append(symbol)
                used.append(phrase)
            if len(hits) >= limit:
                break
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
                 csv_path=MASTER_CSV, known_symbols=None):
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
                    "headline": title[:240], "link": link,
                    "source": urlparse(url).netloc.replace("www.", ""),
                    "seen_at": now.strftime("%H:%M:%S"), "published": pub[:31],
                })
        with self._lock:
            self._items = fresh + self._items
            self._items = self._items[:200]
            for r in fresh:
                for s in r["symbols"]:
                    self._by_symbol.setdefault(s, r)
            self._last_poll_at = now
            self._last_error = "; ".join(errors) if errors else None
        for r in fresh:
            decision(f"[NEWSFEED] {'/'.join(r['symbols'])} -- {r['kind']}: "
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
