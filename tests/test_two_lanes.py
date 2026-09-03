"""---- THE REBUILD SAYS WHO, THE TICK SAYS WHEN. 3 Sep 2026 ----

    "fix the entry lag, make it read ticks not the snapshot ... i want
     lag free & seamless dashboard with out missing any opportunity.
     bot is doing too much complex of operations"     -- the operator

The entry decision was made in main.py's main loop, from
dashboard_state.get_snapshot(). That snapshot is rebuilt by _build(),
which recomputes twenty-seven panels from scratch -- 42s at the
median, 82s at p90 -- while main.py asks for one every second. The buy
decision stood in a queue behind twenty-four panels no trade reads.

Split by how fast the thing actually changes:

    WHO is worth watching   news, an order, results, a concall, a
                            surge. A company does not win a Rs 755
                            crore order twice in a minute. The rebuild
                            owns it and 42s is fine.

    WHEN to act             the price. Runs on the tick worker, the
                            same single thread the exits already use.

ONE SECOND, NOT EVERY TICK. auto_entry.take() sorts candidates by
volume ratio before handing out seats, and its own measured table puts
that ordering at +Rs 565 a trade against -Rs 36 for "first to fire".
Deciding inside one tick can only consider the stock that just ticked,
which IS first-to-fire.

These are source assertions on purpose. Every property here is about
WHERE code is called from, and the failure mode is an ABSENT or a
DUPLICATED call -- neither of which any fixture can produce.
"""

import io
import re

import config

SRC = io.open("main.py", encoding="utf-8").read()


def test_entries_are_placed_from_exactly_one_place():
    """THE SAFETY PROPERTY. Two callers would be two threads placing
    orders, and one stock could be bought twice. The main loop's call
    is deleted, not duplicated."""
    assert SRC.count("auto_entry.take(") == 1, (
        "entries must have exactly one call site -- found %d"
        % SRC.count("auto_entry.take("))


def test_that_one_place_is_the_tick_worker():
    """It must sit inside _tick_worker's reach, not the main loop."""
    call = SRC.index("auto_entry.take(")
    worker = SRC.index("def _tick_worker")
    route = SRC.index("def _route_entries")
    assert route < call < worker, (
        "take() is no longer inside _route_entries above the worker")


def test_the_main_loop_only_publishes():
    """It hands over WHO, and decides nothing."""
    assert '_candidates["rows"] = _rows' in SRC
    publish = SRC.index('_candidates["rows"] = _rows')
    assert publish > SRC.index("def _tick_worker"), (
        "the publish should be in the main loop, below the worker")


def test_the_decision_runs_on_a_beat_not_on_every_tick():
    """Every tick would give the seat to whoever ticked first, which
    core/auto_entry.py measured at -Rs 36 a trade against +Rs 565 for
    the volume ordering it would be replacing."""
    assert "ENTRY_DECISION_INTERVAL_SECONDS" in SRC
    assert config.ENTRY_DECISION_INTERVAL_SECONDS >= 1.0


def test_a_quiet_second_still_decides():
    """queue.Empty used to `continue`, which skipped the rest of the
    loop. A minute with no ticks in a thin stock must not stop the bot
    acting on the candidates it already has."""
    body = SRC[SRC.index("def _tick_worker"):]
    body = body[:body.index("error_tracker")]
    empty = body.index("except queue.Empty:")
    assert "continue" not in body[empty:empty + 120], (
        "a quiet second skips the decision")


def test_routing_cannot_kill_the_tick_loop():
    """Exits live on this thread. A routing failure must never stop
    the trailing stop from running."""
    worker = SRC[SRC.index("def _tick_worker"):]
    body = worker[worker.index("_route_entries()"):]
    assert "except Exception" in body[:400]
    assert "Exits and the feed are unaffected" in body[:600]


def test_it_prices_from_the_feed_not_the_snapshot():
    """The whole point: the price the order is placed at."""
    call = SRC[SRC.index("def _route_entries"):]
    call = call[:call.index("def _tick_worker")]
    assert "price_of=tick_ohlc.of" in call


def test_every_gate_still_applies():
    """Nothing about WHICH stocks qualify changed. take() gets the
    same arguments it always did -- seats, the daily cap, one stock one
    trade a day, sizing, the stop."""
    call = SRC[SRC.index("def _route_entries"):]
    call = call[:call.index("def _tick_worker")]
    for arg in ("security_id_of=", "held=", "traded_today=",
                "max_positions=", "alert=", "enter="):
        assert arg in call, "take() lost %s" % arg


def test_no_candidates_is_not_an_error():
    """Most of the day there is nothing to buy. That is a correct day,
    not a fault, and it must not log or raise."""
    body = SRC[SRC.index("def _route_entries"):]
    body = body[:body.index("def _tick_worker")]
    assert re.search(r"if not rows:\s*\n\s*return", body), (
        "an empty candidate list must return quietly")
