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


def test_the_snapshot_still_publishes_what_the_board_reads():
    state = STATE.read_text(encoding="utf-8", errors="replace")
    assert '"broker_stop"' in state, (
        "dashboard/state.py no longer publishes broker_stop, so the "
        "board's chip will never appear -- silently")


