"""
"Reported" is not the same as "reported WELL".

Operator, 2026-07-27, on what makes a trade worth taking:

    "results genuinely better than the previous quarter, with better
     management guidance"

The bot could already answer "who reports today" (results_calendar) and
"something just filed" (announcement_watcher). Neither could answer the
only question that mattered on 2026-07-27:

    KFINTECH    filed, revenue +30% YoY, profit beat    +9.2%
    TMB         update, total advances +27% YoY        +12.1%
    SENCO       update, revenue +60% YoY                +7.4%
    ACUTAAS     filed the same week                    -Rs 1,593 for us
    CREDITACC   filed the same week                    -Rs   241 for us

Six of the nine stocks the bot bought that day had a results event in
the calendar. So did seven of the day's fourteen biggest winners. The
calendar cannot separate them.

WHAT IS DELIBERATELY NOT TESTED HERE
------------------------------------
Whether a STRONG grade predicts a rising price. It has never been
measured -- that needs years of stored results matched against daily
bars, and this store begins empty. These tests pin down the ARITHMETIC
and the refusals. They are not evidence that the grade makes money, and
nothing in this file should be read that way.
"""

from datetime import date

import pytest

from core.quarterly_results import (QuarterlyResults, grade, summarise,
                                    MATERIAL_GROWTH_PCT)


@pytest.fixture
def store(tmp_path):
    return QuarterlyResults(url=f"sqlite:///{tmp_path}/q.db")


def _q(store, symbol, period, sales, pat, eps=None, opm=None):
    return store.remember(symbol=symbol, period_end=period, sales=sales,
                          pat=pat, eps=eps, opm_pct=opm,
                          period_label=period.strftime("%b-%y"))


# ----------------------------------------------------------------
# Storing
# ----------------------------------------------------------------

def test_a_quarter_is_stored_and_read_back(store):
    assert _q(store, "MOLDTKPAC", date(2026, 6, 30), 300.0, 26.0) == "new"
    assert store.latest("MOLDTKPAC")["sales"] == 300.0


def test_restating_the_same_quarter_updates_it(store):
    """Companies revise. The row must move, not duplicate."""
    _q(store, "MOLDTKPAC", date(2026, 6, 30), 300.0, 26.0)
    assert _q(store, "MOLDTKPAC", date(2026, 6, 30), 305.0, 26.0) == "updated"
    assert store.count() == 1


def test_re_reading_identical_numbers_reports_unchanged(store):
    """'0 new' is ambiguous between 'nothing arrived' and 'nothing was
    different'. This project has already been bitten by that once."""
    _q(store, "MOLDTKPAC", date(2026, 6, 30), 300.0, 26.0)
    assert _q(store, "MOLDTKPAC", date(2026, 6, 30), 300.0, 26.0) == "unchanged"


def test_quarters_come_back_newest_first(store):
    for d, s in ((date(2025, 6, 30), 240.0), (date(2026, 3, 31), 238.0),
                 (date(2026, 6, 30), 300.0)):
        _q(store, "MOLDTKPAC", d, s, 20.0)
    assert [h["period_end"] for h in store.history("MOLDTKPAC")][0] == \
        date(2026, 6, 30)


def test_ordering_uses_dates_not_labels(store):
    """'Dec-25' sorts before 'Jun-26' alphabetically but comes AFTER it
    in the wrong direction -- a whole family of quiet bugs."""
    _q(store, "X", date(2025, 12, 31), 100.0, 10.0)
    _q(store, "X", date(2026, 6, 30), 200.0, 20.0)
    assert store.latest("X")["sales"] == 200.0


# ----------------------------------------------------------------
# The comparison -- the actual point
# ----------------------------------------------------------------

def test_the_real_moldtkpac_card_is_reproduced(store):
    """The operator's own earnings-pulse card, MOLDTKPAC Q1 FY27, which
    states: sales +26% QoQ / +25% YoY, PAT +24% QoQ / +14% YoY.

    Uses the figures from the card's CHARTS, not its summary table. The
    table prints 300 / 238 / 241; the charts carry 300.5 / 237.86 /
    240.56. Computing from the rounded display values gives 24% YoY
    against the card's 25% -- the arithmetic was right and the input was
    a rounded number. Worth keeping as a warning: whatever feeds this
    store must carry full precision, not what fits on a card.
    """
    _q(store, "MOLDTKPAC", date(2025, 6, 30), 240.56, 22.40)
    _q(store, "MOLDTKPAC", date(2026, 3, 31), 237.86, 20.64)
    _q(store, "MOLDTKPAC", date(2026, 6, 30), 300.50, 25.60)

    c = store.compare("MOLDTKPAC")
    assert round(c["qoq"]["sales"]) == 26
    assert round(c["qoq"]["pat"]) == 24
    assert round(c["yoy"]["sales"]) == 25
    assert round(c["yoy"]["pat"]) == 14
    assert c["grade"] in ("STRONG", "GOOD")


def test_one_quarter_alone_refuses_to_compare(store):
    """One stored quarter is a fact, not a trend. Inventing a comparison
    from it is exactly the confident-and-wrong output this project has
    already paid for."""
    _q(store, "SOLO", date(2026, 6, 30), 300.0, 26.0)
    assert store.compare("SOLO") is None


def test_yoy_is_matched_by_date_not_by_counting_back_four(store):
    """A missing quarter would silently make 'YoY' mean five quarters."""
    _q(store, "GAPPY", date(2025, 6, 30), 100.0, 10.0)
    _q(store, "GAPPY", date(2026, 3, 31), 150.0, 14.0)
    _q(store, "GAPPY", date(2026, 6, 30), 200.0, 20.0)
    c = store.compare("GAPPY")
    assert c["yoy"]["period"] == "Jun-25"


def test_no_year_ago_quarter_gives_qoq_only(store):
    _q(store, "NEWCO", date(2026, 3, 31), 100.0, 10.0)
    _q(store, "NEWCO", date(2026, 6, 30), 130.0, 14.0)
    c = store.compare("NEWCO")
    assert c["qoq"] is not None and c["yoy"] is None


def test_growth_from_a_loss_is_refused_not_invented(store):
    """A swing from -10 to +5 is not '150% growth'. A percentage off a
    negative base is arithmetic that means nothing, and printing one is
    worse than printing nothing."""
    _q(store, "TURNAROUND", date(2026, 3, 31), 100.0, -10.0)
    _q(store, "TURNAROUND", date(2026, 6, 30), 120.0, 5.0)
    assert store.compare("TURNAROUND")["qoq"]["pat"] is None


# ----------------------------------------------------------------
# Grading
# ----------------------------------------------------------------

def test_growth_on_both_lines_grades_well():
    g = grade({"sales": 26.0, "pat": 24.0}, {"sales": 25.0, "pat": 18.0})
    assert g in ("STRONG", "GOOD")


def test_shrinking_on_both_lines_grades_weak():
    assert grade({"sales": -12.0, "pat": -20.0}, None) == "WEAK"


def test_sales_up_but_profit_down_is_mixed():
    """The trap. Revenue growth bought with margin is not a good quarter,
    and a grader that only reads the top line would call it strong."""
    assert grade({"sales": 30.0, "pat": -18.0}, None) == "MIXED"


def test_small_moves_are_not_treated_as_growth():
    """Indian quarterly numbers swing on seasonality and one-offs. A 2%
    'rise' in sales is not a signal."""
    tiny = MATERIAL_GROWTH_PCT / 2
    assert grade({"sales": tiny, "pat": tiny}, None) == "MIXED"


def test_no_numbers_means_no_grade():
    assert grade(None, None) is None
    assert grade({"sales": None, "pat": None}, None) is None


def test_the_summary_reads_like_a_human_wrote_it():
    s = summarise({"sales": 26.0, "pat": 24.0}, {"sales": 25.0, "pat": 14.0})
    assert "sales +26% QoQ" in s and "PAT +24% QoQ" in s


def test_the_summary_omits_noise():
    assert summarise({"sales": 1.0, "pat": 0.5}, None) == ""


# ----------------------------------------------------------------
# Reaching the shortlist
# ----------------------------------------------------------------

def _rows():
    return [{"symbol": "KFINTECH", "ltp": 950.0, "change_pct": 9.2, "volume": 1},
            {"symbol": "ACUTAAS", "ltp": 100.0, "change_pct": 9.2, "volume": 1}]


def test_a_strong_quarter_outranks_a_weak_one_on_the_same_move(tmp_path, store):
    """THE 2026-07-27 case. Both filed, both moved the same. Only the
    numbers separate them, and the bot bought the wrong one."""
    from core.shortlist import ShortlistBuilder

    _q(store, "KFINTECH", date(2026, 3, 31), 275.0, 70.0)
    _q(store, "KFINTECH", date(2026, 6, 30), 360.0, 90.0)
    _q(store, "ACUTAAS", date(2026, 3, 31), 300.0, 40.0)
    _q(store, "ACUTAAS", date(2026, 6, 30), 240.0, 25.0)

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         quarterly_results=store)
    out = b.rank(_rows())
    assert out["rows"][0]["symbol"] == "KFINTECH"
    assert out["rows"][0]["grade"] in ("STRONG", "GOOD")
    assert out["rows"][-1]["grade"] == "WEAK"


def test_the_numbers_appear_in_the_reason(tmp_path, store):
    from core.shortlist import ShortlistBuilder
    _q(store, "KFINTECH", date(2026, 3, 31), 275.0, 70.0)
    _q(store, "KFINTECH", date(2026, 6, 30), 360.0, 90.0)
    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         quarterly_results=store)
    why = " ".join(b.rank(_rows())["rows"][0]["why"])
    assert "sales +" in why and "PAT +" in why


def test_an_empty_store_changes_nothing(tmp_path, store):
    """Where this bot has been all along. Not a failure."""
    from core.shortlist import ShortlistBuilder
    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         quarterly_results=store)
    out = b.rank(_rows())
    assert len(out["rows"]) == 2
    assert all(r["grade"] is None for r in out["rows"])


def test_a_broken_store_cannot_break_the_panel(tmp_path):
    from core.shortlist import ShortlistBuilder

    class Broken:
        def compare(self, symbol):
            raise RuntimeError("store exploded")

    b = ShortlistBuilder(daily_db=str(tmp_path / "a.db"),
                         results_db=str(tmp_path / "b.db"),
                         memory_db=str(tmp_path / "c.db"),
                         quarterly_results=Broken())
    assert len(b.rank(_rows())["rows"]) == 2
