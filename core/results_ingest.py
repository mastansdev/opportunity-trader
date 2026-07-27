"""
==========================================================
Filing lands -> numbers on the dashboard, same minute
==========================================================

THE CHAIN THIS CLOSES
---------------------
    core/announcement_watcher.py   "MOLDTKPAC filed, 12 minutes ago"
    core/results_ingest.py         <- this: fetch the PDF, read the table
    core/quarterly_results.py      "STRONG: sales +26% QoQ, PAT +24% QoQ"
    core/shortlist.py              the row the operator actually reads

Before this, the middle step was a human downloading a PDF by hand. On
2026-07-27 the operator did exactly that at 14:09 and the file sat on
disk unused.

WHY THE PDF AND NOT THE OTHER TWO SOURCES
-----------------------------------------
Measured that day, all three:

  - the announcement text carries NO figures. Seven real filings that
    evening had 109-168 characters of boilerplate and nothing else.
  - bse.resultsSnapshot() lags (TMB reported and it still showed Mar-26)
    and returns two quarters, so YoY is impossible from it alone.
  - the PDF has the current quarter, the previous quarter AND the
    year-ago quarter, at full precision, attached to the filing itself.

WHY IT RUNS ON ITS OWN THREAD
-----------------------------
The filing PDFs are large -- MOLD-TEK's was 7 MB. Downloading one inside
the announcement poll loop would stall the news feed for seconds at
exactly the moment news is arriving. So the poller only enqueues a
symbol and a URL; everything slow happens here.

FAIL-OPEN, EVERYWHERE
---------------------
A download that 404s, a scanned PDF with no text layer, a statement in
an unrecognised format: all of these produce nothing and log it. The
dashboard then shows the filing without a grade, which is exactly where
this bot was yesterday. Never an exception into the trading path.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import queue
import re
import threading
from datetime import datetime

from core.logger import decision, diagnostic, warn
from core.results_pdf import parse_pdf

FILING_DIR = os.path.join("data", "filings")

# Field names an announcement row might carry the attachment in. NSE has
# used more than one; unverified against a live row, so all are tried and
# whichever hits is logged.
URL_FIELDS = ("attchmntFile", "attachmentFile", "attchmntfile",
              "fileName", "file", "attachment", "pdfLink", "seqNo")

NSE_ARCHIVE = "https://nsearchives.nseindia.com/corporate/"


def find_attachment_url(row):
    """The PDF link out of an announcement row, or None.

    A bare filename is prefixed with NSE's archive path; anything that
    already looks like a URL is left alone.
    """
    if not isinstance(row, dict):
        return None
    for field in URL_FIELDS:
        value = str(row.get(field) or "").strip()
        if not value or not value.lower().endswith(".pdf"):
            continue
        if value.lower().startswith(("http://", "https://")):
            return value
        return NSE_ARCHIVE + value.lstrip("/")
    return None


def _safe_name(symbol, url):
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(url))[-80:]
    return f"{symbol}_{datetime.now():%Y%m%d}_{stem}"


class ResultsIngestor:
    """Queue in, quarters stored out. One worker thread."""

    def __init__(self, store, downloader=None, filing_dir=FILING_DIR,
                 keep_files=True):
        self.store = store
        # Injectable so tests never touch the network. The live path is
        # set from main.py, where the nse session (with its cookies) is
        # already available.
        self.downloader = downloader
        self.filing_dir = filing_dir
        self.keep_files = keep_files
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._done = {}          # symbol -> what happened, for the panel
        self._failures = 0

    # ------------------------------------------------------------

    def submit(self, symbol, url):
        """Called from the announcement poll loop. Returns immediately."""
        if not symbol or not url:
            return False
        self._q.put((str(symbol).upper(), url))
        return True

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop,
                                        name="results-ingest", daemon=True)
        self._thread.start()
        decision("[FILING] Reading results PDFs as they arrive.")

    def _loop(self):
        while not self._stop.is_set():
            try:
                symbol, url = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.ingest(symbol, url)
            except Exception as exc:                       # noqa: BLE001
                warn(f"[FILING] {symbol}: ingest failed ({exc})")
            finally:
                self._q.task_done()

    def stop(self, timeout=3):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------

    def _download(self, symbol, url):
        if self.downloader is None:
            diagnostic(f"[FILING] {symbol}: no downloader wired, skipping.")
            return None
        os.makedirs(self.filing_dir, exist_ok=True)
        path = os.path.join(self.filing_dir, _safe_name(symbol, url))
        if os.path.exists(path) and os.path.getsize(path) > 1024:
            return path                      # already have it
        try:
            self.downloader(url, path)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[FILING] {symbol}: download failed ({str(exc)[:90]})")
            return None
        if not os.path.exists(path) or os.path.getsize(path) < 1024:
            warn(f"[FILING] {symbol}: downloaded file is empty or tiny.")
            return None
        return path

    def ingest(self, symbol, url):
        """Download -> parse -> store. Returns a short status string."""
        path = self._download(symbol, url)
        if path is None:
            return self._record(symbol, "download failed")

        rows = parse_pdf(path, symbol=symbol)
        if not rows:
            return self._record(symbol, "no readable statement")

        counts = {"new": 0, "updated": 0, "unchanged": 0}
        for r in rows:
            outcome = self.store.remember(
                symbol=symbol, period_end=r["period_end"],
                period_label=r.get("period_label"), sales=r.get("sales"),
                pat=r.get("pat"), eps=r.get("eps"),
                other_income=r.get("other_income"),
                operating_profit=r.get("operating_profit"),
                opm_pct=r.get("opm_pct"), source="filing_pdf")
            counts[outcome] = counts.get(outcome, 0) + 1

        if not self.keep_files:
            try:
                os.remove(path)
            except OSError:
                pass

        # The line the operator actually wants to see.
        summary = ""
        try:
            cmp_ = self.store.compare(symbol)
            if cmp_ and cmp_.get("grade"):
                summary = f" -- {cmp_['grade']}: {cmp_['summary']}"
        except Exception:                                  # noqa: BLE001
            pass
        decision(f"[FILING] {symbol}: read {len(rows)} quarters "
                 f"({counts['new']} new){summary}")
        return self._record(symbol, f"{len(rows)} quarters{summary}")

    def _record(self, symbol, status):
        with self._lock:
            self._done[symbol] = {
                "symbol": symbol, "status": status,
                "at": datetime.now().strftime("%H:%M:%S"),
            }
            if "failed" in status or "no readable" in status:
                self._failures += 1
        return status

    def snapshot(self, limit=20):
        with self._lock:
            rows = sorted(self._done.values(), key=lambda r: r["at"],
                          reverse=True)[:limit]
            return {"rows": rows, "queued": self._q.qsize(),
                    "failures": self._failures}


def requests_downloader(session=None, timeout=30):
    """A downloader backed by `requests`.

    NSE rejects requests without a browser-ish User-Agent and a prior
    cookie, which is why a session from the already-authenticated nse
    client is preferred when one is available.
    """
    def _get(url, path):
        import requests
        s = session or requests.Session()
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0 Safari/537.36"),
            "Referer": "https://www.nseindia.com/companies-listing/"
                       "corporate-filings-announcements",
        }
        r = s.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
    return _get
