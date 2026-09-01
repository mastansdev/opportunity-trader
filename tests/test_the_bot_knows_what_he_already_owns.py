"""---- DHAN AND THE BOT WERE NOT IN LINE. 1 September 2026. ----

    "another thing dhan & bot is not inline. i had caplinpoint stock
     but bot does'nt know that still"
                                                -- the operator

Measured on the live snapshot at the moment he said it:

    his at Dhan     CAPLIPOINT, SSWL, INTELLECT, MARINE, RAINBOW, VTL
    ranked to BUY   CAPLIPOINT, SSWL, DYCL, ENGINERSIN, MARINE, MASTEK

    in both at once CAPLIPOINT, SSWL

CAPLIPOINT and SSWL were his own positions AND live buy candidates. The
only reason nothing was bought on top of them is that the book happened
to be full -- luck, not a guard.

THE CAUSE. build_ranked() builds its `held` set from
engine.open_positions, which is the BOT'S OWN trades and nothing else.
Anything he opened himself was invisible to routing.

IT WAS NEVER A DATA PROBLEM, which is what makes it the same fault as
all the others this week. core/broker_sync.py prints

    [BOOK] CAPLIPOINT: 50 at Dhan, opened outside the bot. Shown on the
    panel; the bot will not stop or exit it.

every single cycle, and build_book() puts it on the screen. The reading
was there, correct, and displayed. It just never reached the DECISION.

WHAT THIS IS NOT. Not an adoption and not a block: the bot still will
not stop, trail or exit anything he opened. It only stops the bot
BUYING a stock he is already in -- exactly what "no pyramiding" has
always meant for its own positions.
"""

import core.engine as eng
import dashboard.state as st


class _Executor:
    def __init__(self, rows):
        self._rows = rows

    def positions(self):
        return self._rows


class _Execution:
    def __init__(self, rows):
        self.executor = _Executor(rows)


class _Engine:
    def __init__(self, rows):
        self.execution = _Execution(rows)


class _Board:
    """The ENGINE owns the reading -- see Engine.symbols_at_broker()."""
    symbols_at_broker = eng.Engine.symbols_at_broker
    _refresh_broker_held = eng.Engine._refresh_broker_held
    BROKER_HELD_SECONDS = eng.Engine.BROKER_HELD_SECONDS

    def __init__(self, rows):
        self.execution = _Execution(rows)

    def settled(self):
        """What it knows once the worker has been round once.

        symbols_at_broker() answers from memory and refreshes on a
        thread -- see its docstring. The tests drive the worker directly
        rather than sleeping on it, so they measure the reading and not
        the scheduler."""
        self._refresh_broker_held()
        return self.symbols_at_broker()


# His real book on 1 September, in Dhan's own shape.
HIS = [{"tradingSymbol": "CAPLIPOINT", "netQty": 50},
       {"tradingSymbol": "SSWL", "netQty": 25},
       {"tradingSymbol": "CLOSEDONE", "netQty": 0}]


def test_it_finds_what_he_holds_at_dhan():
    got = _Board(HIS).settled()
    assert "CAPLIPOINT" in got
    assert "SSWL" in got


def test_a_flat_row_is_not_a_holding():
    """Dhan returns netQty 0 for a position closed today. Counting it
    would block a stock he no longer owns."""
    assert "CLOSEDONE" not in _Board(HIS).settled()


def test_it_reads_the_same_fields_build_book_reads():
    """If these two ever disagree, the panel and the decision disagree
    about what he owns -- which is the whole bug, moved."""
    rows = [{"symbol": "ALTKEY", "quantity": 10}]
    assert "ALTKEY" in _Board(rows).settled()


def test_a_short_counts_as_held():
    """A negative netQty is a position. Buying into it is not a fresh
    entry, it is closing his short by accident."""
    assert "SHORTED" in _Board(
        [{"tradingSymbol": "SHORTED", "netQty": -40}]).settled()


# ------------------------------------------------------- it fails OPEN

def test_a_broker_that_cannot_be_reached_costs_nothing():
    """It runs on the refresh loop. If Dhan times out, routing must
    behave exactly as it did before this existed -- not refuse
    everything because one REST call failed."""
    class _Broken(_Executor):
        def positions(self):
            raise RuntimeError("Dhan unreachable")

    board = _Board([])
    board.execution.executor = _Broken([])
    assert board.settled() == set()


def test_paper_mode_with_no_broker_reader_is_empty_not_an_error():
    board = _Board([])
    board.execution.executor = object()
    assert board.settled() == set()


def test_a_rubbish_reply_does_not_take_the_loop_down():
    """A broker reply is somebody else's data structure."""
    for rubbish in (None, "not a list", [None, 7, {"no": "symbol"}]):
        assert isinstance(_Board(rubbish).settled(), set)


# ------------------------------------------------- and it is not polled hard

def test_it_is_cached_between_refreshes():
    """build_ranked() runs on the refresh loop. An uncached REST call
    on the live account there is how a session gets rate-limited."""
    calls = []

    class _Counting(_Executor):
        def positions(self):
            calls.append(1)
            return HIS

    board = _Board([])
    board.execution.executor = _Counting([])
    board._refresh_broker_held()                 # one real read
    for _ in range(25):
        board.symbols_at_broker()
    assert len(calls) == 1, f"polled Dhan {len(calls)} times in one loop"


def test_it_never_blocks_the_caller():
    """---- 25.6 SECONDS. 1 September 2026. ----

    Measured on the live bot: one /api/snapshot took 25.6s with this
    read on the build path. BOTH callers are hot loops -- the dashboard
    refresh and main.py's trading loop, the same loop that checks
    square-off and the feed watchdog -- and core/engine.py has been
    bitten by exactly this before with the 52-week scan.

    So the answer comes from memory and the fetch happens on a worker.
    A stale reading is worth far more than a stalled heartbeat."""
    import time

    class _Slow(_Executor):
        def positions(self):
            time.sleep(5)
            return HIS

    board = _Board([])
    board.execution.executor = _Slow([])
    started = time.time()
    got = board.symbols_at_broker()
    took = time.time() - started
    assert took < 0.5, f"the caller waited {took:.1f}s on a Dhan read"
    assert got == set(), "a first call must fail open, not guess"


def test_a_worker_that_raises_does_not_wedge_it_forever():
    """It sets a running flag. If the worker dies without clearing it,
    the holdings freeze at whatever they were and nothing ever refreshes
    again -- silently, because it is a thread."""
    class _Broken(_Executor):
        def positions(self):
            raise RuntimeError("Dhan unreachable")

    board = _Board([])
    board.execution.executor = _Broken([])
    board._refresh_broker_held()
    assert board._broker_held_running is False, (
        "the refresh flag is stuck on -- holdings will never update")


# --------------------------------------------- the wiring, not the helper

def test_the_ranker_consults_it():
    """The panel half."""
    import inspect

    src = inspect.getsource(st.DashboardState.build_ranked)
    assert "_symbols_at_broker()" in src, (
        "build_ranked no longer consults his Dhan holdings")
    where_held = src.find("held = set()")
    where_use = src.find("_symbols_at_broker()")
    where_rank = src.find("held=held")
    assert where_held < where_use < where_rank, (
        "the holdings are read after the set is handed to rank()")


def test_his_holdings_do_not_eat_the_bots_seats():
    """THE TRAP, and it would have been far worse than the bug.

    auto_entry.refuse_reason() uses `held` for TWO questions:

        if symbol in held:                          do I own this?
        if len(held) >= max_positions:              is the book full?

    He holds seven stocks at Dhan. Folding those into `held` against a
    cap of three reads "book full (10 of 3)" on every cycle for the rest
    of time -- a bot that never trades again. So they go in a SEPARATE
    set that answers only the first question."""
    from core import auto_entry

    row = {"symbol": "FRESH", "score": 50.0, "state": "ok", "action": "BUY",
           "plan": {"ok": True, "qty": 10, "stop": 90.0,
                    "entry": 100.0}}
    got = auto_entry.refuse_reason(
        row, _Engine([]), held={"BOTONE"}, max_positions=3,
        owned_elsewhere={"CAPLIPOINT", "SSWL", "A", "B", "C", "D", "E"})
    assert not (got and "book full" in got), (
        f"his own holdings are counted as the bot's seats: {got}")


def test_a_stock_he_already_owns_is_refused_by_name():
    from core import auto_entry

    row = {"symbol": "CAPLIPOINT", "score": 50.0, "state": "ok", "action": "BUY",
           "plan": {"ok": True, "qty": 10, "stop": 90.0,
                    "entry": 100.0}}
    got = auto_entry.refuse_reason(
        row, _Engine([]), held=set(), max_positions=3,
        owned_elsewhere={"CAPLIPOINT"})
    assert got, "the bot would buy on top of his own CAPLIPOINT"
    assert "Dhan" in got, got


def test_it_says_WHOSE_position_it_is():
    """"already holding it" would be a lie -- the BOT is not holding it,
    he is, and the bot will not stop or exit it. He has to be able to
    tell those two apart on the panel."""
    from core import auto_entry

    mine = auto_entry.refuse_reason(
        {"symbol": "X", "score": 9.0, "state": "ok", "action": "BUY",
           "plan": {"ok": True, "qty": 10, "stop": 90.0,
                    "entry": 100.0}}, _Engine([]),
        held={"X"}, max_positions=3)
    his = auto_entry.refuse_reason(
        {"symbol": "X", "score": 9.0, "state": "ok", "action": "BUY",
           "plan": {"ok": True, "qty": 10, "stop": 90.0,
                    "entry": 100.0}}, _Engine([]),
        held=set(), max_positions=3, owned_elsewhere={"X"})
    assert mine != his, "the two cases give the same sentence"


def test_take_passes_it_through():
    """refuse_reason() growing the parameter is worth nothing if take()
    never hands it over -- which is this week's entire theme."""
    import inspect

    src = inspect.getsource(auto_entry_take())
    assert "owned_elsewhere=owned_elsewhere" in src, (
        "take() drops the holdings before refuse_reason() sees them")


def auto_entry_take():
    from core import auto_entry
    return auto_entry.take


def test_the_ORDER_PATH_consults_it():
    """THE HALF THAT ACTUALLY PLACES THE ORDER, and the one I nearly
    missed. main.py does NOT reuse the ranker's held set -- it builds
    auto_entry's separately:

        held=set(engine.open_positions),

    So fixing dashboard/state.py alone would have corrected the display
    and left the buy exactly as it was. That is the same fault being
    fixed here, repeated inside its own fix."""
    from pathlib import Path

    src = Path("main.py").read_text(encoding="utf-8")
    at = src.find("owned_elsewhere=engine.symbols_at_broker()")
    assert at > 0, (
        "main.py never hands auto_entry his Dhan holdings -- they do "
        "not reach the order decision")


def test_both_paths_read_the_same_source():
    """Two readers with two implementations drift. One helper, one
    cache, one answer -- that is the whole point of it living on the
    engine rather than on either caller."""
    import inspect

    panel = inspect.getsource(st.DashboardState._symbols_at_broker)
    assert "self.engine.symbols_at_broker()" in panel, (
        "the dashboard has grown its own copy of the reading again")
