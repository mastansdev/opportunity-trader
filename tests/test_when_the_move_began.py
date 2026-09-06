"""
==========================================================
Both answers written down, neither one deciding anything
==========================================================

    "not even min or time is answer ; volume settles this & reason
     behind that volumes ; any news, events, or any other reason or
     purely price action"

    "no rupee will go into trade unless there is potential to move
     (markets price in the stocks in future perspective while raising
     recent example - Welcorp ... in falling it falls instantly on
     business outlook fear recent ex - wires & cabales)"

    "yes both will settle the answer i guess"
                                -- the operator, 6 September 2026

HE CORRECTED ME AND HE WAS RIGHT. I had proposed a clock -- refuse a
stock whose move began too long ago. He answered that time is not the
mechanism: VOLUME settles it, and the reason behind the volume, because
the market prices a company on what it is about to earn. A Rs 15,840
crore order is potential. A business update is not.

The bot's own measurement agrees with him, and disagrees with the hand
typed weights it was ranking on:

    COMMODITY_CYCLE   +0.67       ORDER_WIN        +0.15
    GUIDANCE          +0.38       GOVT_SCHEME      +0.11
    CAPACITY_EXPANSION+0.29       TARIFF_DUTY      +0.01
    GEOPOLITICS       +0.22       BUSINESS_UPDATE  -0.32
                                  FDA_APPROVAL     -0.80

WHAT THE CLOCK IS STILL FOR. Friday 4 September, every trade measured
against the minute its own volume first jumped:

    arrived within 30 min of the start   17 trades  11 up  6 down  +21,052
    arrived MORE than 30 minutes late     7 trades   0 up  7 down  -15,083

Seven trades, not one winner -- and Friday's book cannot say so,
because the field is blank on all 27 rows. So he settled it: record
both, decide neither. Seven trades is not a rule, and every parameter
fitted on 18-27 August died on the eleven sessions it had not seen.

NOTHING HERE REFUSES A TRADE. No gate imports move_clock, and the four
new columns are written and read by nobody.

AND IT COSTS NOTHING, which he asked for in the same breath:

    "but make sure all these never slow down the bot or process the
     trades"

Measured warm, 400 symbols, a full cycle of all of it: 1.23 ms at best
and 2.47 ms at worst, against a 1,000 ms budget. No file, no database,
no network -- one dict lookup and one field already on the row. The
1,642 ms sqlite read found on this same path this morning is exactly
what that rule exists to prevent.

Author : H&M Opportunity Trader
==========================================================
"""

import io
from datetime import datetime, timedelta

import pytest

from core import move_clock


@pytest.fixture(autouse=True)
def _clean():
    move_clock.reset()
    yield
    move_clock.reset()


NINE_THIRTY = datetime(2026, 9, 7, 9, 30)


def _row(symbol, recent=0.4, volume=2.0):
    return {"symbol": symbol, "recent_pct": recent, "volume_x": volume}


# ------------------------------------------------------------------
# it remembers when a move began
# ------------------------------------------------------------------

def test_it_remembers_the_first_time_it_saw_the_move():
    move_clock.note([_row("PURVA")], now=NINE_THIRTY)
    assert move_clock.began("PURVA", NINE_THIRTY) == NINE_THIRTY


def test_the_first_sighting_wins_not_the_latest():
    """The whole point is WHEN IT BEGAN. Overwriting it every cycle
    would report every move as brand new at the moment of entry."""
    move_clock.note([_row("PURVA")], now=NINE_THIRTY)
    later = NINE_THIRTY + timedelta(hours=3)
    move_clock.note([_row("PURVA")], now=later)
    assert move_clock.began("PURVA", later) == NINE_THIRTY
    assert move_clock.age_minutes("PURVA", later) == 180.0


def test_a_quiet_stock_is_not_on_the_clock():
    move_clock.note([_row("SLEEPY", recent=0.01, volume=2.0)],
                    now=NINE_THIRTY)
    move_clock.note([_row("THIN", recent=0.4, volume=1.0)], now=NINE_THIRTY)
    assert move_clock.began("SLEEPY", NINE_THIRTY) is None
    assert move_clock.began("THIN", NINE_THIRTY) is None


def test_unknown_is_none_and_never_zero():
    """None means the bot was not watching when it started. Read as
    zero it would say "this move is brand new", which is the opposite
    of the truth and the exact mistake this exists to catch."""
    assert move_clock.age_minutes("NOSUCH", NINE_THIRTY) is None


def test_yesterdays_clock_is_not_todays():
    move_clock.note([_row("PURVA")], now=NINE_THIRTY)
    tomorrow = NINE_THIRTY + timedelta(days=1)
    assert move_clock.age_minutes("PURVA", tomorrow) is None


def test_it_reuses_the_bots_own_definition_of_moving():
    """A second definition of "moving" would drift from the one the
    gate uses within a week."""
    from core.ranker import MIN_RECENT_PCT
    assert move_clock.MIN_RECENT_PCT == MIN_RECENT_PCT


# ------------------------------------------------------------------
# and it can never break a cycle
# ------------------------------------------------------------------

def test_rubbish_rows_do_not_raise():
    move_clock.note([None, {}, {"symbol": None}, {"symbol": "X"},
                     {"symbol": "Y", "recent_pct": "abc", "volume_x": 2},
                     "not a dict"], now=NINE_THIRTY)
    assert move_clock.watching(NINE_THIRTY) == 0


def test_no_rows_at_all_is_fine():
    assert move_clock.note(None, now=NINE_THIRTY) == 0
    assert move_clock.note([], now=NINE_THIRTY) == 0


# ------------------------------------------------------------------
# it is actually wired -- the fault this codebase keeps producing
# ------------------------------------------------------------------

def test_the_ranker_feeds_the_clock():
    src = io.open("core/ranker.py", encoding="utf-8").read()
    assert "move_clock.note(" in src, \
        "the clock exists and nothing ever tells it what happened"


def test_the_entry_writes_both_answers_down():
    src = io.open("core/auto_entry.py", encoding="utf-8").read()
    for field in ("run_up_pct", "move_age_min", "reason_kind",
                  "reason_pct_of_company"):
        assert f'"{field}"' in src, f"{field} is never stamped at entry"


def test_the_trade_record_keeps_them():
    src = io.open("core/trade_memory.py", encoding="utf-8").read()
    for field in ("run_up_pct", "move_age_min", "reason_kind",
                  "reason_pct_of_company"):
        assert f'"{field}": ' in src, \
            f"{field} is not in LATE_COLUMNS -- a live db would never "\
            f"gain the column and every insert would fail silently"
        assert f"{field}=closed_position.get" in src or \
               f"{field}=(closed_position.get" in src, \
            f"{field} has a column and record() never fills it"


# ------------------------------------------------------------------
# what it must NOT do
# ------------------------------------------------------------------

def test_every_late_column_is_also_in_the_table(tmp_path):
    """---- I MADE THIS EXACT MISTAKE. 6 September 2026. ----

    A patch that added four names to LATE_COLUMNS aborted before it
    wrote the matching Column() lines. The result passed every import,
    ALTERed the four columns onto the live database, and then refused
    every insert:

        [TRADE MEMORY] Could not record a completed trade (Unconsumed
        column names: move_age_min, reason_pct_of_company, run_up_pct,
        reason_kind). The trade HAPPENED; it is missing from
        data/trade_memory.db and from every report built on it.

    record() swallows exceptions by design, so a whole session of
    trades would have gone unrecorded with one warning line. The two
    lists must agree, and now they have to.
    """
    from core.trade_memory import TradeMemory
    memory = TradeMemory(f"sqlite:///{tmp_path / 'trade_memory.db'}")
    known = {c.name for c in memory.trades.columns}
    missing = [name for name in TradeMemory.LATE_COLUMNS if name not in known]
    assert not missing, \
        "in LATE_COLUMNS but not in the table -- every insert will be "\
        "refused with 'Unconsumed column names': %s" % ", ".join(missing)


def test_no_gate_reads_the_clock():
    """It records. If it is ever allowed to refuse a trade that should
    be a decision he makes out of his own book, not a drift."""
    for path in ("core/rules.py", "core/engine.py", "core/results_gate.py",
                 "core/why_moving.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "move_clock" not in src, \
            f"{path} reads the move clock -- that was never decided"


def test_the_lookups_touch_no_disk():
    """---- 1,642 ms AT 09:15. 6 September 2026, this morning. ----

        "but make sure all these never slow down the bot or process
         the trades"                              -- the operator

    A single sqlite read added to this path cost 1,642 ms on its first
    call, which would have landed inside the entry loop at the open.
    So these two read a dict held in memory and a field already on the
    row, and nothing else.
    """
    src = io.open("core/auto_entry.py", encoding="utf-8").read()
    block = src[src.index("def _move_age"):src.index("def _reason_size")]
    block += src[src.index("def _reason_size"):][:1200]
    for banned in ("sqlite3", "open(", "read_excel", "requests",
                   "json.load"):
        assert banned not in block, \
            f"_move_age/_reason_size reaches for {banned} on the tick path"


def test_the_entry_gates_are_untouched():
    from core.rules import (MIN_MOVE_FROM_PREV_CLOSE_PCT, MIN_VOLUME_RATIO,
                            REQUIRE_A_REASON_ALWAYS, SURGE_REASON_MIN_RATIO)
    assert MIN_MOVE_FROM_PREV_CLOSE_PCT == 3.0
    assert MIN_VOLUME_RATIO == 2.5
    assert SURGE_REASON_MIN_RATIO == 10.0
    assert REQUIRE_A_REASON_ALWAYS is True
