"""
==========================================================
Announcement Watcher -- news while the market is still open
==========================================================

WHY THIS EXISTS
---------------
main.py refreshes the results calendar exactly ONCE, at startup, and
never again. There is no timer. On a day when 68 companies report, the
bot learns about a 12:12 filing the following morning.

Measured on 2026-07-27:

    TMB     09:15-13:00   +2%, a few hundred shares a minute
            13:00-close   +12.1%, 7.0m of its 7.17m shares
            busiest minute of the entire session: 15:17

    Canara Bank filed around noon. At 13:50 the bot still had no idea.

The exchange is not slow. tools/watch_results.py measured the gap
between NSE publishing and us seeing it at about ONE SECOND. The entire
delay was our own polling.

WHAT IT DOES
------------
A daemon thread polls NSE's announcements feed every
ANNOUNCEMENT_POLL_SECONDS during market hours, dedupes on
(symbol, timestamp), classifies what kind of announcement it is, and
keeps today's list in memory for two readers:

    core/shortlist.py    a stock that filed 20 minutes ago jumps to the
                         top of the operator's panel, with "FILED 20m
                         ago" as the reason
    dashboard/state.py   the announcements panel itself

WHAT IT DOES NOT DO
-------------------
It does not trade, and it does not decide. It classifies by SUBJECT
LINE only -- "results filed" not "results were good". Grading impact
needs the actual numbers, which is a separate piece of work. On
2026-07-27 both KFINTECH (+9.2%) and ACUTAAS (-1,593 for us) filed
results the same week; nothing in the subject line separates them.

Treat KIND as "what happened", never as "this is worth buying".

SAFETY
------
Runs on its own daemon thread. Every network call is wrapped. A failure
sets a visible error string and the thread keeps going -- the bot must
never stop trading because a news feed went down, and the operator must
never be told "no news" when the truth is "we cannot see the news".

Author : H&M Opportunity Trader
==========================================================
"""

import re
import threading
import time
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn
from core.results_ingest import find_attachment_url

# ---------------------------------------------------------------
# CLASSIFICATION -- by subject line, and honest about that
# ---------------------------------------------------------------
# Ordered: the first pattern that matches wins, so the more specific
# ones come first. Every one of these is a category of event the
# operator named on 2026-07-27 -- "results better than previous
# quarter", "order wins, approvals, deals".

KIND_PATTERNS = [
    ("RESULTS", re.compile(
        r"financial\s+result|unaudited\s+result|audited\s+result|"
        r"quarterly\s+result|outcome\s+of\s+board\s+meeting.*result", re.I)),
    ("ORDER_WIN", re.compile(
        r"\border(s)?\b|\bcontract(s)?\b|letter\s+of\s+(intent|award)|\bLOI\b|"
        r"work\s+order|bags\b|secures\b|awarded", re.I)),
    ("APPROVAL", re.compile(
        r"approval|USFDA|\bFDA\b|\bCDSCO\b|licen[cs]e|patent|"
        r"certification|clearance", re.I)),
    ("DEAL", re.compile(
        r"acquisition|acquire|merger|amalgamation|joint\s+venture|"
        r"\bJV\b|divest|stake\s+(sale|purchase)|strategic\s+partnership", re.I)),
    ("FUND_RAISE", re.compile(
        r"fund\s+rais|preferential\s+issue|\bQIP\b|rights\s+issue|"
        r"debenture|allotment\s+of\s+(equity|shares)", re.I)),
    ("PAYOUT", re.compile(r"dividend|buyback|bonus\s+issue|stock\s+split", re.I)),
    ("CONCALL", re.compile(r"investor\s+meet|analysts?\s*/?\s*institutional"
                            r"|con\.?\s*call|earnings\s+call|investor\s+"
                            r"presentation", re.I)),
    ("RATING", re.compile(r"credit\s+rating|rating\s+(action|revision)", re.I)),
    ("GOVERNANCE", re.compile(
        r"resignation|appointment|cessation|change\s+in\s+(management|"
        r"directorate)|auditor", re.I)),
]

# Routine filings that arrive constantly and move nothing. Excluded
# BEFORE classification so the panel doesn't fill with noise -- the
# operator's own rule: "only major, quality events, not every routine
# filing".
NOISE = re.compile(
    r"trading\s+window|newspaper\s+publication|investor\s+(meet|presentation)\s"
    r"*schedul|analyst\s+meet|record\s+date\s+intimation|"
    r"compliance\s+certificate|reg\.?\s*74|shareholding\s+pattern|"
    r"corporate\s+governance\s+report|loss\s+of\s+(share\s+)?certificate|"
    r"duplicate\s+share", re.I)


def classify(subject, body=""):
    """What KIND of announcement this is. None means routine noise, or
    nothing recognisable.

    BODY MATTERS, and the first version of this ignored it. Live output
    from 2026-07-27 evening, seven consecutive real filings:

        desc: Outcome of Board Meeting
        attachment: "Bharat Electronics Limited has submitted to the
                     Exchange, the financial results for the period
                     ended Jun 30, 2026..."

    The subject was "Outcome of Board Meeting" for BEL, TATAPOWER,
    SAGCEM, NORTHARC, KANPRPLA, TOKYOPLAST and BKMINDST alike. Subject
    alone classified all seven as None -- the watcher would have thrown
    away every results filing of the evening. The words that identify it
    are in the attachment text.

    core/results_calendar.py's is_results_announcement() already took
    both for exactly this reason; this one did not, and real data found
    it within hours.

    Noise is still judged on the SUBJECT only. A body mentioning
    "financial results" inside a newspaper-publication notice must not
    resurrect it.
    """
    subject = str(subject or "")
    if not subject.strip() or NOISE.search(subject):
        return None
    text = f"{subject}\n{body or ''}"
    for kind, pattern in KIND_PATTERNS:
        if pattern.search(text):
            return kind

    # ---- 468 OF 602 WERE BEING THROWN AWAY. 21 August 2026 ----
    #
    #     "even 100 qty on today top gainers 5 stocks would have bring
    #      profit of 10-20 k today . check that."     -- operator
    #
    # It was Rs 30,556, and WELCORP was Rs 11,420 of it. Its filing:
    #
    #     "Analysts/Institutional Investor Meet/Con. Call Updates"
    #     classify() -> None
    #
    # No KIND_PATTERN matches an investor call, so the biggest gainer
    # of the day had its filing fetched, classified as nothing, and
    # DISCARDED -- after which the ranker refused the stock for having
    # "no event behind it".
    #
    # Measured the same afternoon against NSE's own feed: of 602
    # filings in 24 hours, 134 classified and 468 were dropped. The
    # bot was seeing 22% of what the exchange published.
    #
    # UNRECOGNISED IS NOT NOISE. NOISE has its own test above and is
    # still refused. Everything else is now KEPT as OTHER, which
    # core/why_moving.FILING_WEIGHT scores below the reason bar -- so
    # this changes what the bot can SEE without changing what it will
    # BUY, and the subjects can be measured before any of them are
    # promoted.
    return "OTHER"


def _parse_stamp(value):
    """NSE hands back several formats depending on the field."""
    raw = str(value or "").strip()[:19]
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d-%m-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


class AnnouncementWatcher:
    """Poll, dedupe, classify, remember. Read from any thread."""

    def __init__(self, known_symbols=None, poll_seconds=60, lookback_hours=8,
                 fetcher=None, ingestor=None, store=None):
        # Shared on-disk home for what this collects, so the polling can
        # live in the collector and main.py can just read. Optional --
        # None keeps the old in-memory-only behaviour exactly.
        self.store = store
        self.known_symbols = {str(s).upper() for s in (known_symbols or ())}
        self.poll_seconds = poll_seconds
        self.lookback_hours = lookback_hours
        # Injectable so tests never touch the network.
        self._fetcher = fetcher or self._fetch_nse
        # core/results_ingest.py. A RESULTS filing is handed over with
        # its PDF link; everything slow happens on the ingestor's own
        # thread, because the filings are large (MOLD-TEK's was 7 MB) and
        # blocking the poll loop would stall the news feed at exactly the
        # moment news is arriving.
        self.ingestor = ingestor

        self._lock = threading.Lock()
        self._seen = set()               # (symbol, stamp) -- dedupe key
        self._today = []                 # newest first
        self._by_symbol = {}             # symbol -> newest record
        self._last_poll_at = None
        self._last_error = None
        self._poll_count = 0
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------

    def _fetch_nse(self):
        from nse import NSE
        now = datetime.now()
        with NSE(download_folder="data") as n:
            return n.announcements(
                index="equities",
                from_date=now - timedelta(hours=self.lookback_hours),
                to_date=now) or []

    def poll_once(self):
        """One pass. Returns the list of NEW records. Never raises."""
        try:
            rows = self._fetcher()
            self._last_error = None
        except Exception as exc:                          # noqa: BLE001
            # Visible, not silent. "No news" and "we cannot see the news"
            # must never look the same to the operator.
            self._last_error = str(exc)[:160]
            warn(f"[NEWS] Announcement poll failed: {exc}")
            return []

        now = datetime.now()
        today = now.date()
        fresh = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if self.known_symbols and symbol not in self.known_symbols:
                continue

            subject = str(row.get("desc") or row.get("subject") or "")
            # attchmntText carries the sentence that actually names the
            # event -- see classify()'s docstring for the seven filings
            # that were silently dropped without it.
            body = str(row.get("attchmntText") or row.get("attchmntFile") or "")
            kind = classify(subject, body)
            if kind is None:
                continue

            stamp_raw = (row.get("an_dt") or row.get("sort_date")
                         or row.get("exchdisstime") or "")
            key = (symbol, str(stamp_raw))
            with self._lock:
                if key in self._seen:
                    continue
                self._seen.add(key)

            filed = _parse_stamp(stamp_raw)
            if filed and filed.date() != today:
                continue                                  # yesterday's news

            attachment = find_attachment_url(row)
            record = {
                "symbol": symbol,
                "kind": kind,
                "subject": subject[:220],
                "attachment": attachment,
                "filed_at": filed.strftime("%H:%M:%S") if filed else "",
                "seen_at": now.strftime("%H:%M:%S"),
                "minutes_ago": (round((now - filed).total_seconds() / 60.0, 1)
                                if filed else None),
                "delay_seconds": (round((now - filed).total_seconds(), 1)
                                  if filed else None),
                "_filed_dt": filed,
            }
            fresh.append(record)

        if fresh:
            # ---- SO main.py CAN STOP POLLING. 3 August 2026. ----
            # The collector passes a FeedStore; main.py passes nothing
            # and behaves exactly as before. See core/feed_store.py.
            if self.store is not None:
                self.store.save("announcement", fresh,
                                lambda r: f"{r.get('symbol')}|"
                                          f"{r.get('filed_at')}|"
                                          f"{(r.get('subject') or '')[:80]}")
            with self._lock:
                self._today = fresh + self._today
                self._today.sort(
                    key=lambda r: r["_filed_dt"] or datetime.min, reverse=True)
                for r in self._today:
                    self._by_symbol.setdefault(r["symbol"], r)
            # Hand every RESULTS filing to the ingestor. Only RESULTS --
            # an order win or a rating change has no financial statement
            # to read, and queueing them would just fill the log with
            # "no readable statement".
            if self.ingestor is not None:
                for r in fresh:
                    if r["kind"] == "RESULTS" and r.get("attachment"):
                        try:
                            self.ingestor.submit(r["symbol"], r["attachment"])
                        except Exception as exc:           # noqa: BLE001
                            warn(f"[NEWS] Could not queue {r['symbol']} "
                                 f"for reading: {exc}")

            for r in fresh:
                decision(
                    f"[NEWS] {r['symbol']} -- {r['kind']} filed "
                    f"{r['filed_at'] or 'time unknown'}"
                    + (f" ({r['minutes_ago']:.0f} min ago)"
                       if r["minutes_ago"] is not None else "")
                    + f": {r['subject'][:90]}"
                )

        with self._lock:
            self._last_poll_at = now
            self._poll_count += 1
        return fresh

    # ------------------------------------------------------------
    # THREAD
    # ------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="announcement-watcher", daemon=True)
        self._thread.start()
        decision(f"[NEWS] Watching announcements every {self.poll_seconds}s "
                 f"across {len(self.known_symbols) or 'all'} symbols.")

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:                       # noqa: BLE001
                # poll_once already swallows everything; this is the
                # belt-and-braces layer. A news thread dying quietly is
                # how the bot goes blind without anyone noticing.
                warn(f"[NEWS] Watcher loop error (continuing): {exc}")
            self._stop.wait(self.poll_seconds)
        diagnostic("[NEWS] Watcher stopped.")

    def stop(self, timeout=3):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------
    # READ
    # ------------------------------------------------------------

    def for_symbol(self, symbol):
        """Newest announcement for one symbol today, or None."""
        with self._lock:
            return self._by_symbol.get(str(symbol).upper())

    def symbols_today(self):
        with self._lock:
            return set(self._by_symbol)

    def snapshot(self, limit=25):
        """What the dashboard renders. Plain data, safe to JSON."""
        with self._lock:
            rows = [{k: v for k, v in r.items() if not k.startswith("_")}
                    for r in self._today[:limit]]
            return {
                "rows": rows,
                "count_today": len(self._today),
                "last_poll_at": (self._last_poll_at.strftime("%H:%M:%S")
                                 if self._last_poll_at else None),
                "poll_count": self._poll_count,
                "error": self._last_error,
            }
