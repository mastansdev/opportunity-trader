"""Cause and effect. The memory the bot did not have.

    "what about welspun corp? rally after its order win. check our bots
     memory to recall the cause & effect after. this is the reason i
     asked you to build brain memory but still not done as i wanted"
    "sector map will never match this as we hard coded their sectors
     which is 100% correct but in this case this sector leader is
     expanding into new sector business"
    "which is direct threat to their core business"
                                   -- the operator, 5 September 2026

WELSPUN CORP. On 21 August the store held the largest single order in
the company's history, Rs 15,840 crore. On 3, 4 and 5 September the
bot refused the stock -- up 4.7 to 5.9% on four to six times normal
volume -- saying "nothing published". The cause was in its own store
and nothing joined it to what followed.

ULTRATECH. On 1 September it announced commercial production of wires
and cables. It is a CEMENT company and the sector map is right about
that. The effect landed on KEI, POLYCAB and RRKABEL -- and by
4 September on KEI at -8.95%, RRKABEL -6.10%, POLYCAB -5.76% -- while
ULTRACEMCO itself closed UP. A cause filed under one symbol, an effect
on the businesses it threatens.

So this measures three things separately and never blends them:

    subject   the company that filed it
    peers     that company's OWN sector
    threat    companies whose CORE BUSINESS the event is about,
              whoever filed it

Nothing here votes on a trade. No entry or exit path imports this
module; that is a decision he has not made yet.
"""

import os
import sqlite3

import pytest

from core import cause_effect as ce


# ------------------------------------------------ the subject of an event

def test_a_cement_company_announcing_cables_names_the_cable_makers():
    """THE case. The link is the business the event is ABOUT, not the
    sector of whoever filed it."""
    index = {"INDUSTRY": {"CABLES": ["POLYCAB", "KEI", "RRKABEL", "APARINDS"]},
             "THEMES": {"CEMENT": ["ACC", "AMBUJACEM", "SHREECEM"]}}
    got = dict(ce.subjects_in(
        "ULTRATECH CEMENT: COMMENCES COMMERCIAL PRODUCTION OF WIRES & "
        "CABLES PLANT", tag_index=index))
    assert "CABLES" in got
    assert set(got["CABLES"]) == {"POLYCAB", "KEI", "RRKABEL", "APARINDS"}


def test_a_tag_that_describes_everyone_is_not_a_business():
    """MANUFACTURER has 687 members and GOVERNMENT SPENDING has 292.
    Nothing is threatened out of an attribute."""
    index = {"INDUSTRY": {"MANUFACTURER": [f"S{i}" for i in range(200)]}}
    assert ce.subjects_in("A MANUFACTURER SAID SOMETHING",
                          tag_index=index) == []


def test_a_tag_with_almost_no_members_is_not_a_business_either():
    index = {"INDUSTRY": {"NICHE": ["ONLYONE"]}}
    assert ce.subjects_in("NICHE news", tag_index=index) == []


def test_an_event_naming_no_business_returns_nothing():
    """Most events name none. Empty is a real answer, not a failure."""
    index = {"INDUSTRY": {"CABLES": ["POLYCAB", "KEI", "RRKABEL"]}}
    assert ce.subjects_in("CO APPOINTS NEW CHIEF FINANCIAL OFFICER",
                          tag_index=index) == []


def test_attribute_columns_are_not_searched():
    """OWNERSHIP and BUSINESS_TYPE say what a company IS, not what it
    does for a living."""
    index = {"OWNERSHIP": {"PRIVATE": ["A", "B", "C", "D"]},
             "BUSINESS_TYPE": {"MANUFACTURER": ["A", "B", "C", "D"]}}
    assert ce.subjects_in("A PRIVATE MANUFACTURER", tag_index=index) == []


# ------------------------------------------------------ what followed

def test_a_median_ignores_the_one_peer_that_had_its_own_news():
    """The median, not the mean -- one peer up 40% on its own result
    must not speak for the four that did nothing."""
    assert ce._median([0.1, 0.2, 0.3, 40.0]) == pytest.approx(0.25)


def test_an_unknown_effect_is_not_a_zero_effect():
    assert ce._median([None, None]) is None
    assert ce._forward({}, ["2026-09-01"], "2026-09-01", 1) is None


def test_a_forward_return_is_counted_in_SESSIONS_not_days():
    """An event on a Friday is measured against Monday. Counting
    calendar days would read a weekend as a flat market."""
    sessions = ["2026-08-28", "2026-08-31", "2026-09-01"]
    closes = {"2026-08-28": 100.0, "2026-08-31": 110.0}
    assert ce._forward(closes, sessions, "2026-08-28", 1) == pytest.approx(10.0)


def test_it_will_not_measure_past_the_end_of_what_is_known():
    sessions = ["2026-09-01", "2026-09-02"]
    closes = {"2026-09-01": 100.0, "2026-09-02": 105.0}
    assert ce._forward(closes, sessions, "2026-09-02", 1) is None


# ------------------------------------------------------- the read side

def test_what_followed_says_nothing_when_it_knows_nothing(tmp_path):
    assert ce.what_followed(kind="NOSUCHKIND",
                            db_path=str(tmp_path / "ce.db")) is None


def test_it_reports_counts_and_a_median_never_a_mean(tmp_path):
    path = str(tmp_path / "ce.db")
    conn = ce._connect(path)
    for i, move in enumerate([1.0, 2.0, 3.0, 40.0]):
        conn.execute(
            "INSERT INTO cause_effect (date, symbol, kind, subject_1d) "
            "VALUES (?,?,?,?)", (f"2026-09-0{i + 1}", f"S{i}", "ORDER", move))
    conn.commit()
    conn.close()
    got = ce.what_followed(kind="ORDER", db_path=path)
    assert got["n"] == 4
    assert got["subject"]["up"] == 4
    assert got["subject"]["median"] == pytest.approx(2.5)


def test_recall_answers_the_welspun_question(tmp_path):
    """"Nothing published" was wrong. This is how it can be asked."""
    path = str(tmp_path / "ce.db")
    conn = ce._connect(path)
    conn.execute(
        "INSERT INTO cause_effect (date, symbol, kind, value_cr, "
        "subject_1d, headline) VALUES (?,?,?,?,?,?)",
        ("2026-08-21", "WELCORP", "ORDER", 15840.0, 4.21,
         "SECURES LARGEST-EVER SINGLE ORDER IN COMPANY HISTORY"))
    conn.commit()
    conn.close()
    got = ce.recall("WELCORP", db_path=path)
    assert len(got) == 1
    assert got[0]["value_cr"] == 15840.0
    assert got[0]["subject_1d"] == pytest.approx(4.21)


def test_recall_of_an_unknown_stock_is_empty_not_an_error(tmp_path):
    assert ce.recall("NOSUCH", db_path=str(tmp_path / "ce.db")) == []


def test_nothing_in_the_trading_path_imports_this_yet():
    """It is a record, not a rule. Wiring it into a decision is his
    call and he has not made it."""
    import inspect

    from core import auto_entry, engine
    for module in (auto_entry, engine):
        assert "cause_effect" not in inspect.getsource(module), (
            f"{module.__name__} now reads the cause-effect memory -- that "
            f"is a trading change and needs his approval")
