"""
==========================================================
Every pick written down, before any money moves
==========================================================

    "phase-1 bot will trade (assumption) & record . after tomorrow
     market closing we will verify & start the next phase-2"
    "30K is not trading tomorrow"
                                    -- operator, 4 August 2026

core/ranker.py's weights are my judgement and have never been scored
against an outcome. So the bot picks for a day with nothing at stake,
every decision is written here with the price at the moment it was
made, and tools/verify_picks.py turns that into arithmetic instead of
an argument.

The refusals table is the half that is usually thrown away. If "no
reason found" turns away eleven names and eight of them run 4%, the
mechanism gate is blinding him rather than protecting him -- and only
the count can say which.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

import pytest

from core.decision_log import DecisionLog


def ranking(*symbols, market=1.2):
    return {"market_pct": market, "rows": [
        {"symbol": s, "action": "BUY", "score": 20.0 - i,
         "change_pct": 5.0, "excess_pct": 2.0, "volume_x": 3.0,
         "adv_cr": 120.0, "sector": "IT", "ltp": 100.0 + i,
         "mechanism": "Order win of Rs 500 cr", "why": "up 5.0%, 3x volume"}
        for i, s in enumerate(symbols)]}


@pytest.fixture
def log(tmp_path):
    return DecisionLog(db_path=str(tmp_path / "d.db"))


AT = datetime(2026, 8, 5, 10, 30, 0)


# ---------------------------------------------------------------
# 1. IT WRITES THE PRICE AT THE MOMENT OF THE DECISION
# ---------------------------------------------------------------
def test_a_cycle_is_recorded_with_prices(log):
    assert log.record(ranking("AAA", "BBB"),
                      prices={"AAA": 250.5, "BBB": 99.0}, when=AT) == 2
    rows = log.picks("2026-08-05")
    assert [r["symbol"] for r in rows] == ["AAA", "BBB"]
    assert rows[0]["price"] == 250.5
    assert rows[0]["rank"] == 1


def test_the_price_matters_more_than_anything_else_here():
    """Without the entry price the outcome cannot be measured, only
    remembered."""
    src = open("core/decision_log.py", encoding="utf-8").read()
    assert "price" in src and "prices.get(symbol)" in src


def test_it_falls_back_to_the_row_price_when_none_is_supplied(log):
    log.record(ranking("AAA"), when=AT)
    assert log.picks("2026-08-05")[0]["price"] == 100.0


# ---------------------------------------------------------------
# 2. IT DOES NOT BURY THE MOMENT SOMETHING CHANGED
# ---------------------------------------------------------------
def test_an_identical_cycle_is_not_written_twice(log):
    """The ranker is asked on a clock. Writing the same five rows every
    thirty seconds would drown the moment the list actually moved."""
    assert log.record(ranking("AAA", "BBB"), when=AT) == 2
    assert log.record(ranking("AAA", "BBB"), when=AT) == 0
    assert log.record(ranking("AAA", "BBB"), when=AT) == 0


def test_a_changed_list_is_written(log):
    log.record(ranking("AAA", "BBB"), when=AT)
    assert log.record(ranking("CCC", "AAA"), when=AT) == 2


def test_a_changed_direction_counts_as_changed(log):
    log.record(ranking("AAA"), when=AT)
    flipped = ranking("AAA")
    flipped["rows"][0]["action"] = "SELL"
    assert log.record(flipped, when=AT) == 1


# ---------------------------------------------------------------
# 3. THE FIRST TIME A NAME WAS CALLED IS THE HONEST ENTRY
# ---------------------------------------------------------------
def test_the_earliest_call_per_symbol_is_what_gets_measured(log):
    """The bot cannot claim the best fill of the day for a stock it
    named at 09:40 and again at 14:10."""
    log.record(ranking("AAA"), prices={"AAA": 100.0},
               when=datetime(2026, 8, 5, 9, 40))
    log.record(ranking("BBB"), prices={"BBB": 50.0},
               when=datetime(2026, 8, 5, 11, 0))
    log.record(ranking("AAA"), prices={"AAA": 140.0},
               when=datetime(2026, 8, 5, 14, 10))
    first = log.first_pick_per_symbol("2026-08-05")
    assert first["AAA"]["price"] == 100.0
    assert set(first) == {"AAA", "BBB"}


# ---------------------------------------------------------------
# 4. THE DECLINES ARE HALF THE SCORECARD
# ---------------------------------------------------------------
def test_refusals_are_counted(log):
    log.record_refusals({"no reason found": 11,
                         "not beating its sector": 40}, when=AT)
    got = log.refusals("2026-08-05")
    assert got["not beating its sector"] == 40
    assert got["no reason found"] == 11


def test_refusals_accumulate_across_cycles(log):
    log.record_refusals({"no reason found": 3}, when=AT)
    log.record_refusals({"no reason found": 4}, when=AT)
    assert log.refusals("2026-08-05")["no reason found"] == 7


# ---------------------------------------------------------------
# 5. IT NEVER TRADES AND NEVER BREAKS THE SESSION
# ---------------------------------------------------------------
def test_it_places_no_orders(log):
    src = open("core/decision_log.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    # "execute" is excluded on purpose -- conn.execute() is SQL, and a
    # word list crude enough to catch it catches the wrong thing.
    for banned in ("place_order", "dhan", "qty =", "order_type"):
        assert banned not in code, banned


def test_an_unwritable_path_is_survivable(tmp_path):
    """main.py builds one of these at startup. A bad path must cost the
    notebook, never the session."""
    blocker = tmp_path / "notadir"
    blocker.write_text("x", encoding="utf-8")
    bad = DecisionLog(db_path=str(blocker / "d.db"))
    assert bad.record(ranking("AAA"), when=AT) == 0
    assert bad.picks("2026-08-05") == []
    assert bad.status()["available"] is False


def test_an_empty_ranking_writes_nothing(log):
    assert log.record({"rows": []}, when=AT) == 0
    assert log.record(None, when=AT) == 0


def test_the_ranker_is_recorded_by_the_dashboard():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "self._decisions.record(got, prices=prices)" in src
    assert '"ranked": self.build_ranked(gainers_losers, open_positions),' in src


def test_the_ranking_reaches_the_order_path_and_starts_disarmed():
    """FLIPPED BACK 12 August 2026, later the same day, on his word:

        "by default bot trading = OFF (Bot Observing) when i start
         main.py . i can ON when i want bot to trade with the same
         rules"

    This assertion has now been both ways in one day, which is exactly
    what it is for -- its job is not to hold a particular value, it is
    to make sure the value was CHOSEN. The note it carried invited the
    flip in as many words: "If that was on purpose, this assertion
    should flip back."

    Why it went back: ALERT_ONLY_MODE is the STARTUP value, and the
    dashboard switch is the control. With it False, main.py came up
    already armed and the switch had nothing left to turn on. Worse,
    dashboard/server.py's own docstring had been promising the
    opposite since 5 August -- "a restart returns to ALERT_ONLY_MODE,
    which is the safe value ... it must come back watching, not
    trading" -- a guarantee that was false while the value was False.

    The gates that made arming defensible (core/why_moving.py's
    mandatory reason, core/rules.MIN_VOLUME_RATIO) are untouched. They
    decide WHAT it may buy once armed. This decides whether it starts
    armed at all, and the answer is no.
    """
    main_py = open("main.py", encoding="utf-8").read()
    assert "auto_entry.take(" in main_py, "the ranking reaches nothing"
    assert "enter=engine._enter" in main_py, "it reaches no order path"

    # And the safety is what stops it, deliberately and visibly.
    auto = open("core/auto_entry.py", encoding="utf-8").read()
    assert "alert_only" in auto
    from config import ALERT_ONLY_MODE, TRADING_MODE
    # ---- FLIPPED ON PURPOSE, AND HERE IS WHY. 31 August 2026. ----
    #
    #     "keep simple ON = REAL TRADES . OFF = PAPER TRADES . all same
    #      entry, exits, capital allotted & everything same."
    #                                              -- the operator
    #
    # ALERT_ONLY_MODE was the third state: not trading at all. The
    # assertion above defended it, and it was right to while three
    # states existed. There are two now, and neither of them is
    # "watch". OFF is a full paper day; ON sends the same decisions to
    # Dhan.
    #
    # What that third state actually cost: on 31 August the bot
    # produced 65 alerts and 0 trades, capping ten sessions with no
    # completed trade of its own. It was never the gates refusing --
    # it was this flag, which he had not asked for.
    #
    # The safety that assertion was protecting has not gone anywhere.
    # ALERT_ONLY_MODE could only say "do not trade at all". The switch
    # says something better: whose money. It starts OFF, it moves only
    # when he clicks it, and the process refuses to go live without a
    # Dhan client and I_UNDERSTAND_THIS_PLACES_REAL_ORDERS.
    assert ALERT_ONLY_MODE is False, (
        "ALERT_ONLY_MODE is True -- the bot is back to watching, which "
        "is the state he did not ask for and which produced ten "
        "sessions without a trade. OFF must mean a full paper day.")
    assert TRADING_MODE == "PAPER", (
        "TRADING_MODE is not PAPER. This is what the bot comes up in "
        "before he touches anything, and it must be paper.")
    from trading.execution import Execution
    assert Execution.live is False, (
        "The switch does not start OFF. Every session begins on paper "
        "until he clicks ON -- a restart while he is away from the desk "
        "must come back simulated.")
