"""
==========================================================
The board must say when a position has no stop at Dhan
==========================================================

    "this is the old dashboard. we moved to new one with
     http://127.0.0.1:8000/board"     -- operator, 12 August 2026

board.html is the screen he uses. `BROKER_STOP_ENABLED` went True the
same day, so every entry now also rests a Forever Order at Dhan at the
hard stop -- and that order is the only thing protecting a position
between 15:30 and 09:15, or any time main.py is not running.

dashboard/state.py has published `broker_stop` since 2 August. This
board never drew it. He was told to "watch the broker_stop panel" and
there was no such thing on his screen.

WHY A HEADER CHIP AND NOT A PANEL
---------------------------------
This board is one table and nothing else, deliberately:

    "one verdict not six chips"
    "no more top 50/20/10 gainers tables"

The only figure that earns permanent space is `unprotected`, because
it is the one that means a position dies with this process. It is
SILENT when there is nothing to say -- so its presence is the warning.
A green badge sitting there all day becomes furniture and stops being
read.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOARD = ROOT / "dashboard" / "static" / "board.html"
STATE = ROOT / "dashboard" / "state.py"


def _script():
    src = BOARD.read_text(encoding="utf-8", errors="replace")
    found = re.search(r"<script[^>]*>(.*?)</script>", src, re.S)
    assert found, "board.html has no <script> block"
    return found.group(1)


def test_the_board_reads_broker_stop():
    assert "broker_stop" in _script(), (
        "board.html never reads snapshot['broker_stop']. The switch is "
        "ON and real resting orders go to Dhan -- he cannot see whether "
        "a held position has one.")


def test_it_shows_the_number_that_means_an_exposure():
    """`resting` and `open` are reassuring on their own. `unprotected`
    is the only one that reports a position dying with the process."""
    assert "unprotected" in _script(), (
        "the board shows broker-stop counts without `unprotected`")


def test_it_names_the_symbols_that_are_bare():
    """A count tells him something is wrong. A name tells him what to
    do about it, at 15:29, without opening another screen."""
    script = _script()
    assert re.search(r"unprotected[^\n]*join", script), (
        "the board reports how many positions are unprotected but not "
        "WHICH -- he cannot act on a number")


def test_it_is_silent_when_there_is_nothing_to_say():
    """Presence is the warning. A permanent badge is furniture."""
    script = _script()
    assert 'display = "none"' in script or "display='none'" in script, (
        "the broker-stop chip is never hidden, so it will sit on the "
        "header every day and stop being read")


def test_the_snapshot_still_publishes_what_the_board_reads():
    state = STATE.read_text(encoding="utf-8", errors="replace")
    assert '"broker_stop"' in state, (
        "dashboard/state.py no longer publishes broker_stop, so the "
        "board's chip will never appear -- silently")


def test_the_script_parses():
    """board.html is one <script>. A syntax error blanks the table and
    the bot never notices, because the failure is in his browser."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(_script())
        path = handle.name
    try:
        done = subprocess.run([node, "--check", path],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, (
            "board.html does not parse -- the table will be BLANK:\n"
            + done.stderr)
    finally:
        pathlib.Path(path).unlink(missing_ok=True)
