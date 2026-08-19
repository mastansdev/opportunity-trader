"""
==========================================================
The alert said "order win". The record said no news.
==========================================================

    "fix the news_kind gap"     -- operator, 19 August 2026

13,174 of 13,272 recorded signals carried no news_kind, so the whole
"does news predict" half of his thesis could not be measured in
either direction.

TWO FAULTS, AND NEITHER WAS A MISSING FEED

1. TWO NEWS SOURCES, AND THE JOURNAL SAW THE THIN ONE

       self.news_feed          RSS headlines, symbol-resolved
       data/stock_events.db    the PRO Telegram channels --
                               15,289 events across 1,727 symbols

   core/why_moving.py reads the SECOND to build the sentence on his
   alert. _capture_reason() read only the FIRST. So on 19 August the
   RAILTEL alert quoted a Rs 166.80 crore EPFO work order -- straight
   out of stock_events -- while the row recorded for that same signal
   said news_kind = NULL.

   The thing he reads said the stock had news. The thing that would
   prove it said it did not.

2. THE STORE IS UTC AND THE MARKET IS IST

   stock_events stamps "2026-08-18T13:41:11+00:00". That is 19:11 IST
   on the 18th -- an EVENING filing, made after the close, which is
   exactly the kind that drives the next morning's move.

   The first version of the fix filtered on the same calendar day and
   returned None for RAILTEL on the morning RAILTEL was the pick of
   the day. A same-day filter does not miss a few events; it misses
   the ones that matter most.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
from datetime import datetime

from core.engine import Engine

ROOT = pathlib.Path(__file__).resolve().parents[1]

NOW = datetime(2026, 8, 19, 11, 0)


def _engine(rows):
    eng = Engine.__new__(Engine)
    eng._events_rows = rows
    return eng


def _patch(monkeypatch, rows):
    monkeypatch.setattr("core.why_moving._events_for", lambda s: rows)
    return Engine.__new__(Engine)


# ---------------------------------------------------------------
# THE EVENING FILING IS THE WHOLE POINT
# ---------------------------------------------------------------

def test_an_evening_filing_reaches_the_record(monkeypatch):
    """THE RAILTEL CASE. 13:41 UTC on the 18th is 19:11 IST on the
    18th -- filed after the close, and it is why the stock broke out
    on the 19th."""
    eng = _patch(monkeypatch, [
        {"at": "2026-08-18T13:41:11+00:00", "kind": "ORDER"}])
    assert eng._channel_event_kind("RAILTEL", NOW) == "ORDER"


def test_a_filing_from_this_morning_reaches_it_too(monkeypatch):
    eng = _patch(monkeypatch, [
        {"at": "2026-08-19T03:20:00+00:00", "kind": "NEWS"}])
    assert eng._channel_event_kind("EMSLIMITED", NOW) == "NEWS"


def test_last_week_is_not_why_it_is_moving_today(monkeypatch):
    """An order win from three weeks ago would make the column look
    full while meaning nothing."""
    eng = _patch(monkeypatch, [
        {"at": "2026-08-01T09:00:00+00:00", "kind": "ORDER"}])
    assert eng._channel_event_kind("X", NOW) is None


def test_a_filing_from_BEFORE_yesterdays_close_is_excluded(monkeypatch):
    """08:00 UTC on the 18th is 13:30 IST -- during the 18th's
    session, so it belongs to the 18th's move, not the 19th's."""
    eng = _patch(monkeypatch, [
        {"at": "2026-08-18T08:00:00+00:00", "kind": "ORDER"}])
    assert eng._channel_event_kind("X", NOW) is None


def test_it_cannot_read_an_event_that_has_not_happened_yet(monkeypatch):
    """A replay of a past morning must not see tomorrow's news."""
    eng = _patch(monkeypatch, [
        {"at": "2026-08-19T12:00:00+00:00", "kind": "ORDER"}])
    assert eng._channel_event_kind("X", datetime(2026, 8, 19, 9, 30)) is None


# ---------------------------------------------------------------
# MARKET-WIDE NEWS IS NOT THIS STOCK'S NEWS
# ---------------------------------------------------------------

def test_a_macro_event_never_fills_the_column(monkeypatch):
    """"RBI holds rates" would otherwise stamp the same word on every
    stock that moved, and the column would look answered."""
    for kind in ("MACRO", "MARKET_ANSWER", "AI_VERDICT"):
        eng = _patch(monkeypatch, [
            {"at": "2026-08-19T03:00:00+00:00", "kind": kind}])
        assert eng._channel_event_kind("X", NOW) is None


def test_a_company_event_beside_a_macro_one_still_counts(monkeypatch):
    eng = _patch(monkeypatch, [
        {"at": "2026-08-19T03:00:00+00:00", "kind": "MACRO"},
        {"at": "2026-08-19T03:05:00+00:00", "kind": "ORDER"}])
    assert eng._channel_event_kind("X", NOW) == "ORDER"


# ---------------------------------------------------------------
# RSS STILL WINS WHERE IT SPEAKS
# ---------------------------------------------------------------

def test_the_channel_only_fills_in_when_RSS_has_nothing():
    """RSS carries a stance the channels do not, so nothing that
    already worked may change."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _capture_reason"):
               src.find("def _channel_event_kind")]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'if out["news_kind"] is None:' in code, (
        "the channel event is overwriting a stance-carrying RSS item")


def test_it_reads_the_same_store_the_alert_reads():
    """One reader, one cache, one answer. A second lookup would drift
    from the alert within a week and the record would contradict the
    message again -- which is the bug this file exists for."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _channel_event_kind"):
               src.find("def _no_reason_refusal")]
    assert "from core.why_moving import _events_for" in body


# ---------------------------------------------------------------
# IT MUST NEVER COST A TICK
# ---------------------------------------------------------------

def test_it_never_raises_on_junk(monkeypatch):
    for rows in (None, [], [{}], [{"at": None}], [{"at": "x", "kind": "O"}],
                 [{"at": "2026-08-19", "kind": "ORDER"}],
                 [{"kind": "ORDER"}], "not-a-list"):
        eng = _patch(monkeypatch, rows)
        assert eng._channel_event_kind("X", NOW) in (None, "ORDER")


def test_a_broken_reader_answers_None_not_an_exception(monkeypatch):
    def _explode(symbol):
        raise RuntimeError("events store is locked")
    monkeypatch.setattr("core.why_moving._events_for", _explode)
    assert Engine.__new__(Engine)._channel_event_kind("X", NOW) is None


# ---------------------------------------------------------------
# AND THE RANKED LANE HAS TO WRITE A ROW AT ALL
# ---------------------------------------------------------------

def test_the_ranked_lane_records_its_picks():
    """The second half of the same gap. Only the STRUCTURAL lane wrote
    to the journal, so RAILTEL -- a RANKED pick -- had no row on
    19 August for any column to be filled in."""
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_journal_pick(engine, row" in code
    assert code.count("_journal_pick(engine, row") >= 3, (
        "a ranked pick can still finish without leaving a record")


def test_it_reads_the_real_events_store():
    """Against data/stock_events.db itself. If the schema or the
    timestamp format moves under this, it fails here rather than
    quietly returning None for every stock again."""
    from core.why_moving import _events_for

    rows = _events_for("RAILTEL")
    assert isinstance(rows, list)
    if rows:
        assert "at" in rows[0] and "kind" in rows[0]
