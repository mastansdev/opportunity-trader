"""
The bot must learn about a filing while the market is still open.

main.py refreshed the results calendar exactly ONCE, at startup, and
never again. There was no timer.

    Canara Bank filed around noon on 2026-07-27.
    At 13:50 the bot still had no idea.

    TMB the same day:  09:15-13:00  +2%, a few hundred shares a minute
                       13:00-close  +12.1%, 7.0m of its 7.17m shares
                       busiest minute of the whole session: 15:17

The exchange is not the slow part. tools/watch_results.py measured the
gap between NSE publishing and us seeing it at about ONE SECOND. The
entire delay was our own polling.

These tests use an injected fetcher -- no network, ever. What they pin
down is the behaviour around the feed: what counts as news, what counts
as noise, that a filing reaches the shortlist, and that a broken feed
says so out loud instead of looking like a quiet day.
"""

from datetime import datetime, timedelta

import pytest

from core.announcement_watcher import AnnouncementWatcher, classify


def _row(symbol, subject, when=None):
    when = when or datetime.now()
    return {"symbol": symbol, "desc": subject,
            "an_dt": when.strftime("%d-%b-%Y %H:%M:%S")}


def _watcher(rows, **kw):
    return AnnouncementWatcher(fetcher=lambda: rows, **kw)


# ----------------------------------------------------------------
# What counts as news
# ----------------------------------------------------------------

@pytest.mark.parametrize("subject,kind", [
    ("Financial Results for the quarter ended June 30, 2026", "RESULTS"),
    ("Outcome of Board Meeting - Unaudited Financial Results", "RESULTS"),
    ("Company bags order worth Rs 269 crore from North Western Railway",
     "ORDER_WIN"),
    ("Receipt of Letter of Intent from Indian Navy", "ORDER_WIN"),
    ("USFDA approval for generic product", "APPROVAL"),
    ("Acquisition of 51% stake in subsidiary", "DEAL"),
    ("Interim Dividend declared", "PAYOUT"),
    ("Credit Rating revision by CRISIL", "RATING"),
])
def test_real_announcement_subjects_are_classified(subject, kind):
    assert classify(subject) == kind


@pytest.mark.parametrize("subject", [
    "Closure of Trading Window",
    "Newspaper Publication of Financial Results",
    "Shareholding Pattern for the quarter",
    "Compliance Certificate under Reg. 74(5)",
    "Loss of Share Certificate",
    "Corporate Governance Report",
])
def test_routine_filings_are_ignored(subject):
    """Operator's own rule, 2026-07-25: only major, quality events, not
    every routine filing. A panel that fills with trading-window notices
    is a panel nobody reads."""
    assert classify(subject) is None


def test_newspaper_publication_is_noise_even_though_it_says_results():
    """The trap: it contains 'Financial Results' verbatim. It is an
    advertisement about results that were already announced."""
    assert classify("Newspaper Publication of Financial Results") is None


# ----------------------------------------------------------------
# Polling
# ----------------------------------------------------------------

def test_a_filing_is_picked_up():
    w = _watcher([_row("TMB", "Financial Results for Q1 FY27")])
    fresh = w.poll_once()
    assert [r["symbol"] for r in fresh] == ["TMB"]
    assert fresh[0]["kind"] == "RESULTS"


def test_the_same_filing_is_not_reported_twice():
    """NSE returns the whole recent window on every call, so without
    dedupe the operator would see the same row every 60 seconds."""
    rows = [_row("TMB", "Financial Results for Q1 FY27")]
    w = _watcher(rows)
    assert len(w.poll_once()) == 1
    assert w.poll_once() == []


def test_how_long_ago_it_was_filed_is_computed():
    """'Filed 20 minutes ago' is the fact that matters. TMB's move began
    after 13:00 -- a calendar date could never have said to look then."""
    w = _watcher([_row("TMB", "Financial Results",
                       when=datetime.now() - timedelta(minutes=20))])
    r = w.poll_once()[0]
    assert 19 <= r["minutes_ago"] <= 22


def test_symbols_outside_our_universe_are_dropped():
    w = _watcher([_row("TMB", "Financial Results"),
                  _row("NOTOURS", "Financial Results")],
                 known_symbols={"TMB"})
    assert [r["symbol"] for r in w.poll_once()] == ["TMB"]


def test_yesterdays_filing_is_not_shown_as_today():
    w = _watcher([_row("TMB", "Financial Results",
                       when=datetime.now() - timedelta(days=1))])
    assert w.poll_once() == []


# ----------------------------------------------------------------
# A broken feed must SAY so
# ----------------------------------------------------------------

def test_a_failing_feed_does_not_raise():
    """The bot must never stop trading because a news feed went down."""
    def boom():
        raise RuntimeError("NSE unreachable")
    w = AnnouncementWatcher(fetcher=boom)
    assert w.poll_once() == []


def test_a_failing_feed_is_visible_in_the_snapshot():
    """'Nothing filed yet' and 'we cannot see the news' must never look
    the same to someone deciding whether to buy."""
    def boom():
        raise RuntimeError("NSE unreachable")
    w = AnnouncementWatcher(fetcher=boom)
    w.poll_once()
    assert "NSE unreachable" in (w.snapshot()["error"] or "")


def test_a_recovered_feed_clears_the_error():
    state = {"fail": True}

    def flaky():
        if state["fail"]:
            raise RuntimeError("down")
        return [_row("TMB", "Financial Results")]

    w = AnnouncementWatcher(fetcher=flaky)
    w.poll_once()
    assert w.snapshot()["error"]
    state["fail"] = False
    w.poll_once()
    assert w.snapshot()["error"] is None


def test_a_malformed_row_does_not_break_the_pass():
    w = _watcher(["not a dict", {}, {"symbol": ""},
                  _row("TMB", "Financial Results")])
    assert [r["symbol"] for r in w.poll_once()] == ["TMB"]


# ----------------------------------------------------------------
# Reaching the shortlist -- the whole point
# ----------------------------------------------------------------

def test_a_fresh_filing_lifts_the_stock_up_the_shortlist(tmp_path):
    """TMB filed and the operator never saw it. With the watcher wired
    in, a stock that filed minutes ago must outrank an identical stock
    that did not."""
    from core.shortlist import ShortlistBuilder

    w = _watcher([_row("TMB", "Financial Results",
                       when=datetime.now() - timedelta(minutes=10))])
    w.poll_once()

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         announcement_watcher=w)
    rows = [{"symbol": "TMB", "ltp": 909.0, "change_pct": 5.0, "volume": 1},
            {"symbol": "QUIETCO", "ltp": 100.0, "change_pct": 5.0, "volume": 1}]
    out = b.rank(rows)
    assert out["rows"][0]["symbol"] == "TMB"
    assert any("FILED" in reason for reason in out["rows"][0]["why"])


def test_the_shortlist_works_with_no_watcher_at_all(tmp_path):
    from core.shortlist import ShortlistBuilder
    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"))
    out = b.rank([{"symbol": "TMB", "ltp": 909.0, "change_pct": 5.0,
                   "volume": 1}])
    assert out["rows"][0]["symbol"] == "TMB"


def test_a_broken_watcher_cannot_break_the_shortlist(tmp_path):
    """The panel with money on it outranks the news panel."""
    from core.shortlist import ShortlistBuilder

    class Broken:
        def for_symbol(self, symbol):
            raise RuntimeError("watcher exploded")

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         announcement_watcher=Broken())
    out = b.rank([{"symbol": "TMB", "ltp": 909.0, "change_pct": 5.0,
                   "volume": 1}])
    assert out["rows"][0]["symbol"] == "TMB"


# ----------------------------------------------------------------
# Snapshot shape the dashboard depends on
# ----------------------------------------------------------------

def test_snapshot_is_json_safe():
    """_filed_dt is a datetime and must not reach the websocket."""
    w = _watcher([_row("TMB", "Financial Results")])
    w.poll_once()
    import json
    json.dumps(w.snapshot())


def test_newest_filing_is_listed_first():
    now = datetime.now()
    w = _watcher([_row("OLD", "Financial Results", when=now - timedelta(hours=3)),
                  _row("NEW", "Financial Results", when=now - timedelta(minutes=2))])
    w.poll_once()
    assert [r["symbol"] for r in w.snapshot()["rows"]] == ["NEW", "OLD"]
