"""
Tests for core/gate_log.py -- why the bot did NOT take a trade.

The one that matters is
test_a_candidate_is_counted_once_at_its_deepest_gate: these gates fire
on every candle close while their condition holds, so counting EVENTS
would produce a funnel that measures how long conditions lasted rather
than which gate is binding.
"""

from core.gate_log import (
    GATE_INDEX, GATES, GateLog, NullGateLog,
)


def log():
    g = GateLog()
    g.start_day("2026-07-27")
    return g


def by_gate(rows):
    return {r["gate"]: r for r in rows}


# ----------------------------------------------------------
# the counting rule
# ----------------------------------------------------------

def test_a_candidate_is_counted_once_at_its_deepest_gate():
    g = log()
    g.reject("PARAS", "LONG", "RS_BAND")      # 09:31
    g.reject("PARAS", "LONG", "SECTOR")       # 10:15, got further
    rows = by_gate(g.funnel())
    assert rows["RS_BAND"]["died"] == 0
    assert rows["SECTOR"]["died"] == 1
    assert g.summary()["candidates"] == 1


def test_a_shallower_gate_later_does_not_demote_a_candidate():
    """Order of arrival must not matter -- only how far it ever got."""
    g = log()
    g.reject("PARAS", "LONG", "SECTOR")
    g.reject("PARAS", "LONG", "REGIME")
    assert by_gate(g.funnel())["SECTOR"]["died"] == 1
    assert by_gate(g.funnel())["REGIME"]["died"] == 0


def test_repeat_firings_do_not_inflate_the_funnel():
    """350 candles of the same rejection is ONE candidate."""
    g = log()
    for _ in range(350):
        g.reject("PARAS", "LONG", "RS_BAND")
    rows = by_gate(g.funnel())
    assert rows["RS_BAND"]["died"] == 1
    assert rows["RS_BAND"]["events"] == 350        # raw count kept


def test_long_and_short_are_separate_candidates():
    g = log()
    g.reject("PARAS", "LONG", "RS_BAND")
    g.reject("PARAS", "SHORT", "SECTOR")
    assert g.summary()["candidates"] == 2


def test_an_unknown_gate_is_ignored_not_trusted():
    """A typo must not silently invent a bucket."""
    g = log()
    g.reject("PARAS", "LONG", "TYPO_GATE")
    assert g.summary()["candidates"] == 0


# ----------------------------------------------------------
# entries
# ----------------------------------------------------------

def test_an_entry_is_counted_and_never_demoted():
    g = log()
    g.reject("PARAS", "LONG", "RS_BAND")
    g.accept("PARAS", "LONG")
    g.reject("PARAS", "LONG", "SECTOR")        # a later candle
    s = g.summary()
    assert s["entries"] == 1
    assert s["rejected"] == 0
    assert all(r["died"] == 0 for r in g.funnel())


def test_the_same_entry_twice_counts_once():
    g = log()
    g.accept("PARAS", "LONG")
    g.accept("PARAS", "LONG")
    assert g.summary()["entries"] == 1


# ----------------------------------------------------------
# the funnel itself
# ----------------------------------------------------------

def test_the_funnel_is_in_engine_gate_order():
    assert [r["gate"] for r in log().funnel()] == [c for c, _ in GATES]


def test_survivors_step_down_and_end_at_the_entries():
    g = log()
    g.reject("A", "LONG", "REGIME")
    g.reject("B", "LONG", "RS_BAND")
    g.reject("C", "LONG", "SECTOR")
    g.accept("D", "LONG")
    rows = by_gate(g.funnel())
    assert g.summary()["candidates"] == 4
    assert rows["REGIME"]["survived"] == 3
    assert rows["RS_BAND"]["survived"] == 2
    assert rows["SECTOR"]["survived"] == 1
    assert rows["SIZING"]["survived"] == 1        # the one that traded


def test_deaths_plus_entries_account_for_every_candidate():
    g = log()
    for i in range(7):
        g.reject(f"S{i}", "LONG", "RS_BAND")
    for i in range(3):
        g.accept(f"E{i}", "LONG")
    total_died = sum(r["died"] for r in g.funnel())
    s = g.summary()
    assert total_died + s["entries"] == s["candidates"] == 10


def test_biggest_filter_names_the_gate_killing_the_most():
    g = log()
    for i in range(5):
        g.reject(f"S{i}", "LONG", "TREND_RANK")
    for i in range(2):
        g.reject(f"T{i}", "LONG", "SECTOR")
    s = g.summary()
    assert s["biggest_filter"] == "TREND_RANK"
    assert s["biggest_filter_died"] == 5


def test_biggest_filter_is_none_on_an_empty_session():
    assert log().summary()["biggest_filter"] is None


# ----------------------------------------------------------
# near misses -- passed every selection rule, died on mechanics
# ----------------------------------------------------------

def test_near_misses_only_cover_the_execution_gates():
    g = log()
    g.reject("EARLY", "LONG", "RS_BAND")            # a selection gate
    g.reject("LATE", "LONG", "BREAKOUT_MARGIN")     # mechanics
    g.reject("THIN", "LONG", "VOLUME")
    gates = {m["gate"] for m in g.recent_near_misses()}
    assert gates == {"BREAKOUT_MARGIN", "VOLUME"}


def test_near_misses_are_newest_first_and_carry_the_numbers():
    g = log()
    g.reject("A", "LONG", "BREAKOUT_MARGIN", detail="cleared by 0.02%",
             at="09:34:00")
    g.reject("B", "LONG", "VOLUME", detail="0.6x average", at="10:02:00")
    misses = g.recent_near_misses()
    assert misses[0]["symbol"] == "B"
    assert misses[0]["detail"] == "0.6x average"
    assert misses[1]["at"] == "09:34:00"


def test_near_misses_are_bounded():
    g = GateLog(recent_limit=10)
    g.start_day("2026-07-27")
    for i in range(50):
        g.reject(f"S{i}", "LONG", "VOLUME")
    assert len(g.recent_near_misses(limit=99)) == 10


# ----------------------------------------------------------
# day handling
# ----------------------------------------------------------

def test_a_new_day_clears_the_record():
    g = log()
    g.reject("PARAS", "LONG", "RS_BAND")
    g.start_day("2026-07-28")
    assert g.summary()["candidates"] == 0


def test_a_restart_on_the_same_day_does_not_wipe_it():
    """main.py restarts mid-session more often than anyone likes."""
    g = log()
    g.reject("PARAS", "LONG", "RS_BAND")
    g.start_day("2026-07-27")
    assert g.summary()["candidates"] == 1


# ----------------------------------------------------------
# the no-op
# ----------------------------------------------------------

def test_null_log_accepts_every_call_and_reports_nothing():
    n = NullGateLog()
    n.start_day("2026-07-27")
    n.reject("PARAS", "LONG", "RS_BAND", detail="x", at="09:30")
    n.accept("PARAS", "LONG")
    assert n.funnel() == []
    assert n.summary()["candidates"] == 0
    assert n.recent_near_misses() == []
    assert n.snapshot()["funnel"] == []


def test_null_log_has_the_same_surface_as_the_real_one():
    """Any method the engine calls must exist on both, or switching
    logging off would crash the tick path."""
    for name in ("start_day", "reject", "accept", "funnel", "summary",
                 "recent_near_misses", "snapshot"):
        assert callable(getattr(NullGateLog(), name))
        assert callable(getattr(GateLog(), name))


# ----------------------------------------------------------
# the gate table
# ----------------------------------------------------------

def test_gate_codes_are_unique():
    codes = [c for c, _ in GATES]
    assert len(codes) == len(set(codes))


def test_every_gate_has_a_plain_english_explanation():
    assert all(help_text and len(help_text) > 10 for _, help_text in GATES)


def test_selection_gates_come_before_execution_gates():
    """The near-miss split depends on this ordering being real."""
    assert GATE_INDEX["RS_BAND"] < GATE_INDEX["BREAKOUT_MARGIN"]
    assert GATE_INDEX["SECTOR"] < GATE_INDEX["VOLUME"]
    assert GATE_INDEX["TREND_RANK"] < GATE_INDEX["SIZING"]
