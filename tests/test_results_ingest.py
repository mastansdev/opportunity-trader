"""
Filing lands -> numbers on the dashboard, without a human in between.

On 2026-07-27 the operator downloaded MOLD-TEK's results PDF by hand at
14:09 and it sat on disk unused. This closes that gap:

    announcement_watcher   "MOLDTKPAC filed, 1 minute ago"
    results_ingest         <- fetch the PDF, read the table
    quarterly_results      "STRONG: sales +26% QoQ, PAT +24% QoQ"
    shortlist              the row the operator reads

No network in any test -- the downloader is injected and copies the real
MOLD-TEK PDF's extracted text.
"""

import os
from datetime import date, datetime, timedelta

import pytest

import core.announcement_watcher as watcher_module
from core.announcement_watcher import AnnouncementWatcher
from core.quarterly_results import QuarterlyResults
from core.results_ingest import (ResultsIngestor, find_attachment_url,
                                 NSE_ARCHIVE)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "moldtkpac_q1fy27.txt")
NOW = datetime(2026, 7, 27, 16, 4, 0)


@pytest.fixture
def store(tmp_path):
    return QuarterlyResults(url=f"sqlite:///{tmp_path}/q.db")


@pytest.fixture
def ingestor(store, tmp_path, monkeypatch):
    """Downloads nothing; parse_pdf is redirected at the real extracted
    text of MOLD-TEK's filing."""
    import core.results_ingest as ri

    def fake_download(url, path):
        with open(path, "wb") as f:
            f.write(b"x" * 2048)          # non-empty, passes the size check

    with open(FIXTURE, encoding="utf-8") as f:
        text = f.read()
    from core.results_pdf import parse_statement
    monkeypatch.setattr(ri, "parse_pdf",
                        lambda path, symbol=None, **kw: parse_statement(
                            text, symbol=symbol))
    return ResultsIngestor(store, downloader=fake_download,
                           filing_dir=str(tmp_path / "filings"),
                           keep_files=False)


# ----------------------------------------------------------------
# Finding the PDF
# ----------------------------------------------------------------

def test_a_bare_filename_becomes_an_nse_archive_url():
    url = find_attachment_url({"attchmntFile": "MOLDTKPAC_27072026160317.pdf"})
    assert url == NSE_ARCHIVE + "MOLDTKPAC_27072026160317.pdf"


def test_a_full_url_is_left_alone():
    full = "https://nsearchives.nseindia.com/corporate/X.pdf"
    assert find_attachment_url({"attchmntFile": full}) == full


def test_a_non_pdf_attachment_is_ignored():
    """XBRL and XML land in the same field. Only the PDF carries the
    statement we can read."""
    assert find_attachment_url({"attchmntFile": "data.xml"}) is None


@pytest.mark.parametrize("row", [None, {}, "nonsense", {"attchmntFile": ""}])
def test_a_row_without_an_attachment_returns_none(row):
    assert find_attachment_url(row) is None


# ----------------------------------------------------------------
# Reading it
# ----------------------------------------------------------------

def test_the_real_filing_becomes_three_stored_quarters(ingestor, store):
    ingestor.ingest("MOLDTKPAC", "http://x/y.pdf")
    assert [h["period_label"] for h in store.history("MOLDTKPAC")] == \
        ["Jun-26", "Mar-26", "Jun-25"]


def test_and_it_grades_itself(ingestor, store):
    """The line the operator actually reads, produced with no human
    step anywhere in the chain."""
    ingestor.ingest("MOLDTKPAC", "http://x/y.pdf")
    c = store.compare("MOLDTKPAC")
    assert c["grade"] == "STRONG"
    assert c["qoq"]["sales"] == pytest.approx(26.31, abs=0.1)
    assert c["yoy"]["sales"] == pytest.approx(24.90, abs=0.1)


def test_re_reading_the_same_filing_stores_nothing_new(ingestor, store):
    ingestor.ingest("MOLDTKPAC", "http://x/y.pdf")
    before = store.count()
    ingestor.ingest("MOLDTKPAC", "http://x/y.pdf")
    assert store.count() == before


# ----------------------------------------------------------------
# Failing without taking anything down
# ----------------------------------------------------------------

def test_a_failed_download_is_reported_not_raised(store, tmp_path):
    def boom(url, path):
        raise RuntimeError("404")
    ing = ResultsIngestor(store, downloader=boom,
                          filing_dir=str(tmp_path / "f"))
    assert "download failed" in ing.ingest("X", "http://x/y.pdf")
    assert store.count() == 0


def test_an_unreadable_pdf_is_reported_not_raised(store, tmp_path):
    def ok(url, path):
        with open(path, "wb") as f:
            f.write(b"x" * 2048)
    ing = ResultsIngestor(store, downloader=ok,
                          filing_dir=str(tmp_path / "f"))
    assert "no readable" in ing.ingest("X", "http://x/y.pdf")


def test_with_no_downloader_it_does_nothing_quietly(store, tmp_path):
    ing = ResultsIngestor(store, downloader=None,
                          filing_dir=str(tmp_path / "f"))
    assert ing.ingest("X", "http://x/y.pdf")
    assert store.count() == 0


def test_the_failure_is_visible_in_the_snapshot(store, tmp_path):
    def boom(url, path):
        raise RuntimeError("404")
    ing = ResultsIngestor(store, downloader=boom,
                          filing_dir=str(tmp_path / "f"))
    ing.ingest("X", "http://x/y.pdf")
    assert ing.snapshot()["failures"] == 1


# ----------------------------------------------------------------
# The watcher handing it over
# ----------------------------------------------------------------

def _row(symbol, subject, body, attachment=None):
    r = {"symbol": symbol, "desc": subject, "attchmntText": body,
         "an_dt": NOW.strftime("%d-%b-%Y %H:%M:%S")}
    if attachment:
        r["attchmntFile"] = attachment
    return r


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(watcher_module, "datetime", _Clock)


class _Recorder:
    def __init__(self):
        self.jobs = []

    def submit(self, symbol, url):
        self.jobs.append((symbol, url))
        return True


def test_a_results_filing_is_queued_for_reading():
    rec = _Recorder()
    w = AnnouncementWatcher(
        fetcher=lambda: [_row("MOLDTKPAC", "Outcome of Board Meeting",
                              "Mold-Tek Packaging Limited has submitted to "
                              "the Exchange, the financial results for the "
                              "period ended Jun 30, 2026.",
                              "MOLDTKPAC_27072026160317.pdf")],
        ingestor=rec)
    w.poll_once()
    assert rec.jobs == [("MOLDTKPAC",
                         NSE_ARCHIVE + "MOLDTKPAC_27072026160317.pdf")]


def test_a_non_results_filing_is_not_queued():
    """An order win has no financial statement to read. Queueing it would
    fill the log with 'no readable statement'."""
    rec = _Recorder()
    w = AnnouncementWatcher(
        fetcher=lambda: [_row("X", "Company bags order worth Rs 269 crore",
                              "", "X.pdf")],
        ingestor=rec)
    w.poll_once()
    assert rec.jobs == []


def test_a_results_filing_with_no_pdf_is_not_queued():
    rec = _Recorder()
    w = AnnouncementWatcher(
        fetcher=lambda: [_row("X", "Outcome of Board Meeting",
                              "X Limited has submitted the financial results "
                              "for the period ended Jun 30, 2026.")],
        ingestor=rec)
    w.poll_once()
    assert rec.jobs == []


def test_a_broken_ingestor_cannot_break_the_news_feed():
    """The news panel matters more than the numbers panel. A filing must
    still be reported even if reading it is impossible."""
    class Broken:
        def submit(self, symbol, url):
            raise RuntimeError("queue exploded")

    w = AnnouncementWatcher(
        fetcher=lambda: [_row("MOLDTKPAC", "Outcome of Board Meeting",
                              "Mold-Tek Packaging Limited has submitted to "
                              "the Exchange, the financial results for the "
                              "period ended Jun 30, 2026.", "X.pdf")],
        ingestor=Broken())
    assert len(w.poll_once()) == 1


def test_the_attachment_link_reaches_the_dashboard_row():
    """So the operator can open the filing itself in one click."""
    w = AnnouncementWatcher(
        fetcher=lambda: [_row("MOLDTKPAC", "Outcome of Board Meeting",
                              "Mold-Tek Packaging Limited has submitted to "
                              "the Exchange, the financial results for the "
                              "period ended Jun 30, 2026.", "M.pdf")])
    w.poll_once()
    assert w.snapshot()["rows"][0]["attachment"].endswith("M.pdf")
