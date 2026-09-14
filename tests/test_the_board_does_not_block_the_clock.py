"""
==========================================================
A 98-second rebuild inside a 1-second loop IS the loop
==========================================================

    "today i observed bot is late around mx 5 mins at some point of
     time & later recovered to correct time but it is never sync with
     real current time"              -- the operator, 14 September 2026

WHAT WAS WRONG. dashboard_state.refresh() recomputes twenty-seven panels,
and main.py called it INLINE in the main loop, once a second. From his
10 September log:

    89 slow rebuilds, 20.0s to 98.5s
    the cost every time: `ranked` up to 35.9s, `shortlist` up to 18.6s
    everything else under 3s

While one was in flight, nothing else in that loop ran. The heartbeat is
the proof: meant to be steady, it landed 85-100s apart through
10:22-10:31. That is the clock freezing and jumping, which is what he
saw.

IT COST MORE THAN THE CLOCK. `_candidates["rows"]` -- the list the tick
worker hands free seats from -- is published in that same loop, so it
stood as much as 98s stale. The seats filled fast with whatever was on
the OLD board rather than what was moving now. Entry PRICING was already
live off the tick (3 September); entry SELECTION was not.

THE FIX. The expensive thing gets its own thread. It rebuilds and swaps
the snapshot in atomically under state.py's own lock; the main loop reads
the latest one each second for free. Nothing about which stocks qualify
changes -- take() applies the same gates to the same rows.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / "main.py").read_text(encoding="utf-8")


def _main_loop():
    """The body of the trading loop, and nothing else."""
    start = SRC.index("        while True:\n            now = datetime.now().time()")
    end = SRC.index("            time.sleep(1)", start)
    return SRC[start:end]


def _rebuilder():
    """The board thread's own function body."""
    start = SRC.index("    def _board_rebuilder(stop):")
    end = SRC.index("\n    board_thread = threading.Thread(", start) \
        if "\n    board_thread = threading.Thread(" in SRC[start:] \
        else len(SRC)
    return SRC[start:end]


# ---------------------------------------------------------------
# THE LOOP NO LONGER REBUILDS
# ---------------------------------------------------------------

def test_the_main_loop_does_not_rebuild_the_board():
    """THE CASE. This one line froze the loop for up to 98 seconds."""
    body = _main_loop()
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "dashboard_state.refresh()" not in code, (
        "the board rebuild is back inside the main loop -- the clock "
        "will freeze and the candidate list will go stale again")


def test_the_loop_still_publishes_the_candidates_every_cycle():
    """The cheap half must STAY in the loop. If publishing moved to the
    board thread too, the worker's list would again only be as fresh as
    a rebuild -- which is the whole fault."""
    body = _main_loop()
    assert '_candidates["rows"] = _rows' in body


def test_the_loop_still_reads_the_latest_board():
    """It reads the snapshot rather than building one. get_snapshot() is
    a lock-protected dict read, so this costs nothing."""
    body = _main_loop()
    assert "dashboard_state.get_snapshot()" in body


# ---------------------------------------------------------------
# THE REBUILD HAS ITS OWN THREAD
# ---------------------------------------------------------------

def test_the_rebuild_runs_on_its_own_thread():
    assert "def _board_rebuilder(stop):" in SRC
    assert "target=_board_rebuilder" in SRC
    assert "board_thread.start()" in SRC


def test_it_stops_with_the_rest_of_the_session():
    """Reuses the same stop_event the tick worker and command reader
    use, so one shutdown path ends all three."""
    assert "args=(stop_event,), name=\"board\"" in SRC
    assert "while not stop.is_set():" in _rebuilder()


def test_it_starts_only_once_the_panels_are_wired():
    """Started after the first fill, not beside the other workers: every
    provider the panels read is wired by then, so the thread's first
    pass is a refresh rather than the first build."""
    wired = SRC.index("dashboard_state.refresh()  # panels fill in")
    started = SRC.index("board_thread.start()")
    assert wired < started


# ---------------------------------------------------------------
# IT MUST NOT BE ABLE TO STOP, OR TO SPIN
# ---------------------------------------------------------------

def test_a_failing_panel_does_not_end_the_rebuild_loop():
    """A board that freezes silently is worse than a slow one: every
    stock that moves afterwards is invisible to the ranker."""
    body = _rebuilder()
    assert "except Exception" in body
    assert "warn(" in body
    assert body.index("except Exception") < body.index("stop.wait(")


def test_it_is_paced_so_it_cannot_spin_the_cpu():
    """A rebuild that finishes fast must not run this thread flat out on
    a laptop that is also running the feed."""
    body = _rebuilder()
    assert "stop.wait(" in body
    assert "DASHBOARD_REFRESH_INTERVAL_SECONDS" in body
    assert "0.2" in body, "no floor on the wait -- a fast rebuild spins"
