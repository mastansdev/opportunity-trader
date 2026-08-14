"""
==========================================================
Measuring the chips instead of arguing about them
==========================================================

    "the bot is good at showing you evidence and has never been
     measured at predicting anything"
                    -- the honest audit, 1 August 2026

Every layer describes the PAST: quarterly_results reads what was
reported, Earnings Pulse grades it, the tally counts which metrics
cleared the bar, the AI explains one story. None of it had ever been
checked against what the stock then DID.

FIRST RUN, ON FOUR DAYS OF EVENTS
---------------------------------
    CHIP                 N    EDGE     UP%
    PULSE EXCELLENT     74   +1.72%   85.1%
    CLEAN brief         89   +1.56%   66.3%
    vs estimate         60   +0.82%   66.7%
    PULSE GOOD         341   +0.45%   60.4%
    BEAT/MISS tally    115   +0.01%   50.4%     <- nothing
    AI NEGATIVE         36   +0.14%   55.6%     <- WRONG WAY
    PULSE WEAK         227   -0.21%   44.9%
    ONE-OFF             27   -0.47%   33.3%     <- the warning works

THE THREE THINGS THIS FILE DEFENDS
----------------------------------
1. A BASELINE, ALWAYS. "ORDER WIN averaged +0.8%" says nothing on a
   day the market rose 0.8%. Every number is an edge against the
   median move of everything that traded.

2. AND A SECOND ONE, BECAUSE THE FIRST FLATTERS. A stock the channels
   wrote about is not the same animal as one nobody mentioned.
   Measured: stocks with any chip +0.19%, stocks with none -0.07%.
   0.26 percentage points of every edge above is "being in the news",
   not the panel.

3. AN UNANSWERED EVENT IS NOT A ZERO. 228 events had no session after
   them. Counting those as no-change would drag every bucket toward
   nothing and make the newest, most useful evidence look worthless.

WHAT IT MUST NOT DO
-------------------
Change a score. Nothing in the trading path may import this: acting on
a week of data is the mistake tools/refused_review.py already warns
about in as many words.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.outcomes import MIN_SAMPLE, Baseline, chips_for, contrast, measure


# ---------------------------------------------------------------
# 1. WHICH CHIP DID THIS EVENT PRODUCE?
# ---------------------------------------------------------------
@pytest.mark.parametrize("event,expected", [
    ({"kind": "RESULT", "grade": "EXCELLENT", "headline": "x"},
     ["PULSE EXCELLENT"]),
    ({"kind": "ORDER", "headline": "NBCC secures USD 75M"}, ["ORDER WIN"]),
    ({"kind": "EXPECTATION", "headline": "EXPECTED BULLISH: steady volume"},
     ["EXPECTED BULLISH"]),
    ({"kind": "NEWS", "headline": "ONE-OFF: Dividend income Rs 39.5 Cr"},
     ["ONE-OFF"]),
    ({"kind": "NEWS", "headline": "WATCH: margins Compressing"},
     ["WATCH gauge"]),
    ({"kind": "NEWS", "headline": "CLEAN | Rising, Expanding, Healthy"},
     ["CLEAN brief"]),
    ({"kind": "NEWS", "headline": "BEAT Revenue, PAT | MISS Volume"},
     ["BEAT/MISS tally"]),
    ({"kind": "NEWS", "headline": "PAT +203% vs est, OP +210% vs est"},
     ["vs estimate"]),
])
def test_a_chip_is_recognised_from_the_stored_event(event, expected):
    assert chips_for(event) == expected


def test_one_card_can_earn_more_than_one_chip():
    """A brief carrying a grade AND a flagged one-off is two separate
    claims about the same quarter. They are measured separately."""
    got = chips_for({"kind": "RESULT", "grade": "GREAT",
                     "headline": "ONE-OFF: Dividend income Rs 39.5 Cr",
                     "ai_direction": "POSITIVE"})
    assert set(got) == {"PULSE GREAT", "ONE-OFF", "AI POSITIVE"}


def test_an_event_with_no_chip_is_measured_as_nothing():
    assert chips_for({"kind": "NEWS", "headline": "Some ordinary sentence"}) \
        == []
    assert chips_for({}) == []


def test_only_a_directional_ai_verdict_counts():
    """UNRELATED and NEUTRAL say nothing, so they cannot be scored
    right or wrong."""
    for direction in ("UNRELATED", "NEUTRAL", "", None):
        got = chips_for({"kind": "NEWS", "headline": "x",
                         "ai_direction": direction})
        assert not [c for c in got if c.startswith("AI ")]


# ---------------------------------------------------------------
# 2. THE BASELINE
# ---------------------------------------------------------------
@pytest.fixture
def bars(tmp_path):
    path = str(tmp_path / "daily.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "close REAL, prev_close REAL)")
    # 150 stocks all up exactly 1%, so the median is unambiguous.
    for n in range(150):
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?)",
                     ("2026-07-30", f"S{n}", 101.0, 100.0))
    conn.commit()
    conn.close()
    return path


def test_the_baseline_is_the_median_move_of_the_session(bars):
    assert Baseline(db_path=bars).median_move("2026-07-30") == 1.0


def test_a_thin_session_produces_no_baseline_rather_than_a_guess(bars):
    """Fewer than a hundred stocks is a broken bhavcopy, not a market.
    An edge computed against it would be noise wearing a number."""
    assert Baseline(db_path=bars).median_move("2026-07-29") is None


def test_a_missing_database_does_not_raise():
    assert Baseline(db_path="/nonexistent/x.db").median_move("2026-07-30") \
        is None


# ---------------------------------------------------------------
# 3. THE MEASUREMENT ITSELF
# ---------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    """One event per chip, against a session whose median is +1%."""
    daily = str(tmp_path / "daily.db")
    conn = sqlite3.connect(daily)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "series TEXT, open REAL, high REAL, low REAL, "
                 "close REAL, prev_close REAL)")
    for n in range(150):
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                     ("2026-07-30", f"S{n}", "EQ", 100, 101, 100, 101.0, 100.0))
    # WINNER beats the market, LOSER trails it.
    conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                 ("2026-07-30", "WINNER", "EQ", 100, 106, 100, 105.0, 100.0))
    conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                 ("2026-07-30", "LOSER", "EQ", 100, 100, 94, 96.0, 100.0))
    conn.commit()
    conn.close()

    events = str(tmp_path / "events.db")
    conn = sqlite3.connect(events)
    conn.execute("CREATE TABLE events (symbol TEXT, at TEXT, kind TEXT, "
                 "grade TEXT, headline TEXT, ai_direction TEXT)")
    conn.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        [("WINNER", "2026-07-30T10:00", "RESULT", "EXCELLENT", "x", None),
         ("LOSER", "2026-07-30T10:00", "RESULT", "WEAK", "y", None)])
    conn.commit()
    conn.close()
    return events, daily


def test_the_edge_is_the_move_minus_the_market(store):
    events, daily = store
    got = measure(events_db=events, daily_db=daily)
    # WINNER +5%, market +1% -> edge +4. LOSER -4%, market +1% -> -5.
    assert got["PULSE EXCELLENT"]["edge_median"] == 4.0
    assert got["PULSE WEAK"]["edge_median"] == -5.0


def test_an_event_with_no_session_after_it_is_excluded_not_zeroed(store):
    """228 of the real events were in this state. Counting them as
    no-change would drag every bucket toward nothing and make the
    newest evidence look worthless."""
    events, daily = store
    conn = sqlite3.connect(events)
    conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                 ("WINNER", "2030-01-01T10:00", "RESULT", "EXCELLENT",
                  "future", None))
    conn.commit()
    conn.close()
    got = measure(events_db=events, daily_db=daily)
    assert got["PULSE EXCELLENT"]["n"] == 1
    assert got["_unanswered"] == 1


def test_a_thin_bucket_is_reported_but_flagged(store):
    events, daily = store
    got = measure(events_db=events, daily_db=daily)
    assert got["PULSE EXCELLENT"]["enough"] is False
    assert MIN_SAMPLE >= 20, "a bucket of five has no lesson in it"


def test_a_missing_event_store_returns_nothing_rather_than_raising():
    assert measure(events_db="/nonexistent/e.db",
                   daily_db="/nonexistent/d.db") == {}


# ---------------------------------------------------------------
# 4. THE SECOND BASELINE
# ---------------------------------------------------------------
@pytest.fixture
def wide_store(tmp_path):
    """Enough chipped stocks for the contrast to be worth computing.

    The `store` fixture above has two, which is deliberately too few:
    contrast() refuses a sample that small, and comparing two stocks
    against a hundred and fifty would be a number with no meaning
    dressed up as a finding.
    """
    daily = str(tmp_path / "d.db")
    conn = sqlite3.connect(daily)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "series TEXT, open REAL, high REAL, low REAL, "
                 "close REAL, prev_close REAL)")
    for n in range(150):                     # the market, flat
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                     ("2026-07-30", f"S{n}", "EQ", 100, 100, 100, 100.0, 100.0))
    for n in range(25):                      # the chipped ones, +2%
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                     ("2026-07-30", f"W{n}", "EQ", 100, 102, 100, 102.0, 100.0))
    conn.commit()
    conn.close()

    events = str(tmp_path / "e.db")
    conn = sqlite3.connect(events)
    conn.execute("CREATE TABLE events (symbol TEXT, at TEXT, kind TEXT, "
                 "grade TEXT, headline TEXT, ai_direction TEXT)")
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)",
                     [(f"W{n}", "2026-07-30T10:00", "RESULT", "GOOD",
                       "x", None) for n in range(25)])
    conn.commit()
    conn.close()
    return events, daily


def test_the_contrast_separates_the_panel_from_being_in_the_news(wide_store):
    """The number that puts every other number in context. Measured on
    the real store: +0.19% with a chip, -0.07% without, a gap of
    0.26 percentage points that is "being in the news" and not the
    panel."""
    events, daily = wide_store
    got = contrast(events_db=events, daily_db=daily)
    assert got is not None
    assert got["with_chip_n"] == 25
    assert got["no_chip_n"] == 150
    assert got["with_chip_median"] == 2.0
    assert got["no_chip_median"] == 0.0
    assert got["gap"] == 2.0


def test_the_contrast_refuses_a_chipped_sample_that_is_too_small(store):
    """Two stocks against a hundred and fifty is not a comparison."""
    events, daily = store
    assert contrast(events_db=events, daily_db=daily) is None


def test_the_contrast_refuses_a_sample_too_small_to_mean_anything():
    assert contrast(events_db="/nonexistent/e.db",
                    daily_db="/nonexistent/d.db") is None


# ---------------------------------------------------------------
# 5. IT MUST NOT REACH THE TRADING PATH
# ---------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "core/shortlist.py", "core/engine.py", "main.py",
    "trading/execution.py", "dashboard/state.py",
])
def test_nothing_that_decides_a_trade_imports_the_measurement(path):
    """Acting on a week of data is the mistake refused_review.py
    already warns about in as many words. When this DOES earn its way
    into a score it should be a decision someone made on purpose, not
    an import that crept in."""
    try:
        src = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        pytest.skip(f"{path} not present")
    assert "core.outcomes" not in src
    assert "import outcomes" not in src


# ---------------------------------------------------------------
# 6. THE LENDER CLAIM, LEFT OPEN INSTEAD OF ACTED ON
# ---------------------------------------------------------------
#     "the grader has no concept of provisions or asset quality --
#      which for a lender IS the result"
#                          -- claimed in the audit, 1 August 2026
#
# That claim came from ONE case. APTUS was graded STRONG on +19% YoY
# profit and fell 5.77% because provisions had doubled, and it was
# treated ever after as proof that lenders need their own grader.
#
# The moment the machinery existed to check it:
#
#     A GOOD-or-better grade      N     EDGE     UP%
#     lenders (broad, 120 names)  50   +0.60    74.0
#     everything else            394   +0.79    62.9
#
# Lenders did FINE -- a BETTER hit rate than everything else. Narrowed
# to banks the edge turns negative, on EIGHT samples.
#
# So no lender grader was built. These tests defend that restraint.
from core.outcomes import by_sector, sector_of                # noqa: E402


class Loader:
    def __init__(self, rows):
        self.rows = rows

    def get_by_symbol(self, symbol):
        return self.rows.get(symbol)


@pytest.mark.parametrize("record,expected", [
    ({"INDUSTRY": "Private Sector Bank"}, "BANK"),
    ({"COMPANY NAME": "AXIS BANK LTD"}, "BANK"),
    ({"INDUSTRY": "Housing Finance"}, "NBFC / HFC"),
    ({"CORE BUSINESS": "microfinance lending to rural women"}, "NBFC / HFC"),
    ({"INDUSTRY": "Asset Management"}, "BROKER / AMC"),
    ({"INDUSTRY": "Specialty Chemicals"}, "everything else"),
    ({}, "everything else"),
    (None, "everything else"),
])
def test_a_business_is_put_in_the_right_group(record, expected):
    assert sector_of(record) == expected


def test_the_sector_split_needs_a_master_file_and_says_so(store):
    """Guessing the sector from the ticker would be worse than not
    answering the question."""
    events, daily = store
    assert by_sector(None, events_db=events, daily_db=daily) == {}


def test_the_sector_split_separates_lenders_from_everything_else(store):
    events, daily = store
    loader = Loader({"WINNER": {"INDUSTRY": "Private Sector Bank"},
                     "LOSER": {"INDUSTRY": "Specialty Chemicals"}})
    got = by_sector(loader, events_db=events, daily_db=daily)
    assert got["BANK"]["n"] == 1
    assert got["everything else"]["n"] == 1
    assert got["BANK"]["edge_median"] == 4.0


def test_a_lender_bucket_below_the_threshold_is_flagged_not_believed():
    """BANK came back n=8 on the real store. Eight is an anecdote
    wearing a decimal point, and building a grader on it is how a bot
    acquires a rule nobody can ever justify removing."""
    assert MIN_SAMPLE >= 20


def _code_only(src):
    """The file with comments and docstrings removed.

    Written after the THIRD test today that failed against prose. The
    first version of this one tripped on core/shortlist.py line 1071,
    which is a COMMENT explaining the APTUS case:

        # and GNPA 1.42% against 1.29% -- asset quality, which for a
        # lender IS the result

    Explaining why a rule does not exist is not the same as having it,
    and a test that cannot tell the difference fails on the day
    somebody improves a comment.
    """
    import io
    import tokenize

    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.line.strip().startswith(
                    ('"""', "'''", 'r"""', 'f"""')):
                continue
            out.append(tok[:2] + (tok.start, tok.end, tok.line))
    except tokenize.TokenError:
        return src
    return tokenize.untokenize(out)


def test_no_lender_specific_grading_rule_was_added():
    """The restraint, defended. If a provisions rule ever lands it
    should be because tools/outcome_report.py earned it over a
    fortnight, not because of the memory of one bad day."""
    for path in ("core/quarterly_results.py", "core/shortlist.py"):
        try:
            src = _code_only(open(path, encoding="utf-8").read()).lower()
        except FileNotFoundError:
            continue
        for word in ("gnpa", "gross npa", "provision_coverage",
                     "asset_quality"):
            assert word not in src, (
                f"{path} GRADES on {word!r} -- that rule needs evidence "
                f"from tools/outcome_report.py first")


# ---------------------------------------------------------------
# 7. WHAT WAS LEFT WHEN THE CHIP ACTUALLY REACHED HIM
# ---------------------------------------------------------------
#     "before the movement i need to trust as early bird not in a over
#      crowded place after rally done then i will become volume to
#      early entries right? in simple if i bought even a good stock at
#      near Upper Circuit whats the use?"
#                                    -- operator, 1 August 2026
#
# measure() above answers the wrong question for him: it reads the
# whole session, which credits a chip with a rally that finished
# before he could click. Measured the first time this ran:
#
#     CHIP               open->close     chip->close
#     PULSE EXCELLENT      +1.32%          +0.66%
#     CLEAN brief          +1.02%          +0.52%
#     vs estimate          +0.69%          -0.09%
#
# Half the edge, and on one of them all of it.
from core.outcomes import IST_OFFSET, from_chip_time            # noqa: E402


@pytest.fixture
def minute_store(tmp_path):
    """One session of minute bars, and one event landing inside it.

    The stock opens at 100, runs to 110 by 12:00, and closes at 104.
    A chip that lands at 09:20 sees the whole run. One landing at
    12:00 catches the top and rides it down -- which is exactly the
    trap the operator described.
    """
    daily = str(tmp_path / "daily.db")
    conn = sqlite3.connect(daily)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "series TEXT, open REAL, high REAL, low REAL, "
                 "close REAL, prev_close REAL)")
    for n in range(150):
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                     ("2026-07-30", f"S{n}", "EQ", 100, 100, 100, 100.0, 100.0))
    conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                 ("2026-07-30", "RUNNER", "EQ", 100, 110, 100, 104.0, 100.0))
    conn.commit()
    conn.close()

    minute = str(tmp_path / "minute.db")
    conn = sqlite3.connect(minute)
    conn.execute("CREATE TABLE candles (date TEXT, symbol TEXT, "
                 "minute TEXT, o REAL, h REAL, l REAL, c REAL)")
    # 09:20 at 100, rising to 110 at 12:00, back to 104 at 15:29.
    path = [("09:20", 100.0), ("10:00", 104.0), ("11:00", 108.0),
            ("12:00", 110.0), ("13:00", 107.0), ("15:29", 104.0)]
    for hhmm, price in path:
        conn.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?)",
                     ("2026-07-30", "RUNNER", f"2026-07-30T{hhmm}:00",
                      price, price, price, price))
    conn.commit()
    conn.close()
    return minute, daily


def _events(tmp_path, ist_hhmm):
    """One RESULT event stamped at the given IST time, stored in UTC."""
    from datetime import datetime
    ist = datetime.strptime(f"2026-07-30T{ist_hhmm}:00", "%Y-%m-%dT%H:%M:%S")
    utc = (ist - IST_OFFSET).isoformat()
    path = str(tmp_path / f"e{ist_hhmm.replace(':','')}.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (symbol TEXT, at TEXT, kind TEXT, "
                 "grade TEXT, headline TEXT, ai_direction TEXT)")
    conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                 ("RUNNER", utc, "RESULT", "EXCELLENT", "x", None))
    conn.commit()
    conn.close()
    return path


def test_an_early_chip_sees_the_whole_run(tmp_path, minute_store):
    minute, daily = minute_store
    got = from_chip_time(events_db=_events(tmp_path, "09:20"),
                         daily_db=daily, minute_db=minute)
    s = got["PULSE EXCELLENT"]
    assert s["to_close"] == 4.0        # 100 -> 104
    assert s["best"] == 10.0           # it touched 110
    assert s["worst"] == 0.0


def test_a_chip_at_the_top_measures_the_give_back(tmp_path, minute_store):
    """THE ONE THAT MATTERS. Same stock, same day, same chip -- and
    buying when it arrives at 12:00 is a losing trade. The session
    measurement would have called this +4%."""
    minute, daily = minute_store
    got = from_chip_time(events_db=_events(tmp_path, "12:00"),
                         daily_db=daily, minute_db=minute)
    s = got["PULSE EXCELLENT"]
    assert s["to_close"] < 0           # 110 -> 104
    assert s["best"] == 0.0            # nothing left above it
    assert s["win_pct"] == 0.0


def test_the_timestamp_is_read_as_utc_and_compared_in_ist():
    """The store keeps UTC; the market runs on IST. Off by 5h30m and
    every chip is priced against the wrong minute."""
    assert IST_OFFSET.total_seconds() == 5.5 * 3600


def test_no_minute_store_says_nothing_rather_than_guessing(tmp_path,
                                                           minute_store):
    """Falling back to the session open and calling it the same
    measurement is how the earlier number came to overstate what was
    available to him."""
    _minute, daily = minute_store
    assert from_chip_time(events_db=_events(tmp_path, "09:20"),
                          daily_db=daily,
                          minute_db="/nonexistent/m.db") == {}


def test_a_symbol_with_no_minute_bars_is_counted_not_dropped_silently(
        tmp_path, minute_store):
    """770 of the real events were in this state -- the intraday store
    covers the subscribed universe only. The report has to say so."""
    minute, daily = minute_store
    events = str(tmp_path / "nobars.db")
    conn = sqlite3.connect(events)
    conn.execute("CREATE TABLE events (symbol TEXT, at TEXT, kind TEXT, "
                 "grade TEXT, headline TEXT, ai_direction TEXT)")
    conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                 ("NOBARS", "2026-07-30T04:00:00", "RESULT", "EXCELLENT",
                  "x", None))
    conn.commit(); conn.close()
    # NOBARS needs a daily bar so Reaction can answer it at all.
    conn = sqlite3.connect(daily)
    conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                 ("2026-07-30", "NOBARS", "EQ", 100, 105, 100, 103.0, 100.0))
    conn.commit(); conn.close()
    got = from_chip_time(events_db=events, daily_db=daily, minute_db=minute)
    assert got.get("_unpriced") == 1
    assert "PULSE EXCELLENT" not in got
