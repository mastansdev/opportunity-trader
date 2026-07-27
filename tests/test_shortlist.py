"""
The shortlist must surface the names that mattered, and say why.

Operator, 2026-07-27:

    "as a human i cannot read all 750/960/1500 stocks daily, i created
     bot to trade beside me not replacing me"

core/momentum_universe.py ranks on one number -- % change vs day open --
and locks the top 25 at 09:30. That day it surfaced SWIGGY (-Rs 2,128)
and AWFIS (-Rs 1,152), neither with any event behind it, and never showed
the operator TMB (+12.1%, advances +27% YoY), KFINTECH (+9.2%, revenue
+30% YoY), CARTRADE (+10.8%, UBS target Rs 4,000) or SENCO (+7.4%,
revenue +60% YoY). All four were public before 09:15.

THE MISTAKE THESE TESTS EXIST TO PREVENT
----------------------------------------
The first version of this file scored "quiet volume" as a POSITIVE. That
came from a real 7.5-year study (631,736 stock-days) showing a big up-day
on 6x+ volume underperforms over the next 20 days. But that study answers
"will this keep running for a month" -- a HOLDING question. The shortlist
answers "does this deserve thirty seconds of attention right now".

Wiring one into the other pushed TMB to rank 45 for trading 39x its
normal volume on the day it reported, and SENCO to 424. Volume is now a
printed NOTE, never a score, and test_crowded_volume_does_not_demote
below is what stops it coming back.
"""

import sqlite3

import pytest

from core.shortlist import ShortlistBuilder, MIN_TURNOVER


# At Rs 100 a share, 1,000,000 shares/day = Rs 10 crore turnover, which
# clears MIN_TURNOVER (Rs 5 crore). The first version of this fixture
# used 100,000 shares -- Rs 1 crore -- so every test stock was filtered
# out as unfillable and six tests failed for the wrong reason.
NORMAL_VOLUME = 1_000_000


def _row(symbol, change_pct, ltp=100.0, volume=NORMAL_VOLUME):
    return {"symbol": symbol, "sector": "X", "ltp": ltp,
            "prev_close": ltp, "change_pct": change_pct, "volume": volume}


@pytest.fixture
def builder(tmp_path):
    """A builder with real, tiny databases -- not mocks. The failure this
    module fixes was about what the databases contained, so the tests
    exercise the actual SQL."""
    daily = str(tmp_path / "daily.db")
    results = str(tmp_path / "results.db")
    memory = str(tmp_path / "memory.db")

    c = sqlite3.connect(daily)
    c.execute("create table daily_bars (date text, symbol text, close real, volume real)")
    for sym, vol in (("TMB", NORMAL_VOLUME), ("SWIGGY", NORMAL_VOLUME),
                     ("SPLITTER", NORMAL_VOLUME), ("THIN", 10)):
        for d in range(1, 41):
            c.execute("insert into daily_bars values (?,?,?,?)",
                      (f"2026-06-{d:02d}" if d <= 30 else f"2026-07-{d-30:02d}",
                       sym, 100.0, vol))
    c.commit(); c.close()

    c = sqlite3.connect(results)
    c.execute("create table results_events "
              "(symbol text, results_date text, purpose text)")
    c.execute("insert into results_events values ('TMB','2026-07-27','Financial Results')")
    c.commit(); c.close()

    c = sqlite3.connect(memory)
    c.execute("create table stock_actions "
              "(symbol text, action_type text, ex_date text)")
    c.execute("insert into stock_actions values ('SPLITTER','SPLIT','2026-07-27')")
    c.commit(); c.close()

    b = ShortlistBuilder(daily_db=daily, results_db=results, memory_db=memory)
    b.ensure_loaded("2026-07-27")
    return b


# ----------------------------------------------------------------
# The 2026-07-27 case, which is the whole reason this exists
# ----------------------------------------------------------------

def test_a_big_mover_with_results_outranks_a_mover_without(builder):
    """TMB reported and rose 12.1%. SWIGGY had no event. TMB must win."""
    out = builder.rank([_row("SWIGGY", 12.1), _row("TMB", 12.1)],
                       today="2026-07-27")
    assert out["rows"][0]["symbol"] == "TMB"


def test_crowded_volume_does_not_demote(builder):
    """THE regression test. TMB traded 39x its normal volume on the day
    it announced advances +27% YoY. The first version penalised that and
    buried it at rank 45."""
    quiet = builder.rank([_row("TMB", 12.1, volume=NORMAL_VOLUME)],
                         today="2026-07-27")["rows"][0]
    loud = builder.rank([_row("TMB", 12.1, volume=NORMAL_VOLUME * 39)],
                        today="2026-07-27")["rows"][0]
    assert loud["score"] == quiet["score"], (
        "volume changed the SCORE -- it must only ever change the note"
    )


def test_crowded_volume_is_still_reported_to_the_operator(builder):
    """Demoting on volume is wrong; hiding it is also wrong. The operator
    decides what to do with 'the crowd is already here'."""
    loud = builder.rank([_row("TMB", 12.1, volume=NORMAL_VOLUME * 39)],
                        today="2026-07-27")["rows"][0]
    assert any("CROWDED" in w for w in loud["why"])


def test_every_row_carries_a_reason(builder):
    """A ranked list with no WHY is the old dashboard. The entire point
    is that the operator can judge a name in seconds."""
    out = builder.rank([_row("TMB", 12.1), _row("SWIGGY", 5.0)],
                       today="2026-07-27")
    assert out["rows"]
    for r in out["rows"]:
        assert r["why"], f"{r['symbol']} has no reason attached"


def test_reporting_today_is_called_out_by_name(builder):
    out = builder.rank([_row("TMB", 12.1)], today="2026-07-27")
    assert "REPORTING TODAY" in out["rows"][0]["why"]


# ----------------------------------------------------------------
# Not missing things
# ----------------------------------------------------------------

def test_a_thin_mover_is_surfaced_not_silently_dropped(builder):
    """DPABHUSHAN rose 6.7% on 2026-07-27 and vanished without a word
    from the first version, because it trades under Rs 5 crore a day.
    Unfillable is not the same as unimportant."""
    out = builder.rank([_row("THIN", 6.7)], today="2026-07-27")
    assert out["rows"] == []
    assert [t["symbol"] for t in out["thin"]] == ["THIN"]


def test_a_quiet_stock_that_did_nothing_is_not_listed(builder):
    """The opposite failure: the first version gave points for existing.
    Fifteen stocks tied at 6.0 having moved 0.2%, crowding out real
    movers."""
    out = builder.rank([_row("SWIGGY", 0.2)], today="2026-07-27")
    assert out["rows"] == []


def test_ranking_is_by_score_descending(builder):
    out = builder.rank([_row("SWIGGY", 3.0), _row("TMB", 12.1)],
                       today="2026-07-27")
    scores = [r["score"] for r in out["rows"]]
    assert scores == sorted(scores, reverse=True)
    assert [r["s_no"] for r in out["rows"]] == list(range(1, len(scores) + 1))


# ----------------------------------------------------------------
# Safety -- this runs inside the dashboard the operator watches live
# ----------------------------------------------------------------

def test_a_price_distorting_action_is_flagged(builder):
    """The JLHL 2:10 split, read by this bot as -80%. The % move against
    an unadjusted close is a lie, and the operator must see that."""
    out = builder.rank([_row("SPLITTER", -80.0)], today="2026-07-27")
    listed = {r["symbol"]: r for r in out["rows"]}
    assert "SPLITTER" not in listed or listed["SPLITTER"]["veto"] == ["SPLIT"]


def test_missing_databases_degrade_to_movement_only(tmp_path):
    """A screener going quiet must never take the dashboard down with it
    while the operator has money on the screen."""
    b = ShortlistBuilder(daily_db=str(tmp_path / "no.db"),
                         results_db=str(tmp_path / "no2.db"),
                         memory_db=str(tmp_path / "no3.db"))
    out = b.rank([_row("TMB", 12.1)], today="2026-07-27")
    assert out["rows"][0]["symbol"] == "TMB"
    assert out["rows"][0]["why"]


def test_a_row_with_no_change_pct_is_skipped_not_fatal(builder):
    out = builder.rank([{"symbol": "BROKEN"}, _row("TMB", 12.1)],
                       today="2026-07-27")
    assert [r["symbol"] for r in out["rows"]] == ["TMB"]


def test_reference_data_is_loaded_once_per_day(builder):
    """The 50-day normals read the daily store. Doing that on every
    dashboard refresh would put a multi-second query on the operator's
    own loop."""
    before = builder._loaded_for
    builder.ensure_loaded("2026-07-27")
    assert builder._loaded_for == before == "2026-07-27"


def test_a_new_day_reloads_the_reference(builder):
    builder.ensure_loaded("2026-07-28")
    assert builder._loaded_for == "2026-07-28"


def test_top_limit_is_honoured(builder):
    rows = [_row(f"S{i}", 5.0 + i) for i in range(40)]
    assert len(builder.rank(rows, top=10, today="2026-07-27")["rows"]) == 10
