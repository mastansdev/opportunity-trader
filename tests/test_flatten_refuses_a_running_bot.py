"""---- IT EDITED A FILE THE BOT WAS NOT READING. 2 Sep 2026. ----

    "yes fix that tool so it can't run while bot is up."
                                            -- the operator

He asked for an empty book before the open and ran
tools/flatten_carried.py --close at 09:04, with main.py already up
since 08:56. It reported three positions closed. They were not.

The tool edits data/session_state.json. The RUNNING bot holds its book
in memory and writes that file back on save, so the edit was silently
overwritten. What actually happened that morning:

    09:16:32  SELL INTELLECT  120 @  685.73   TRAILING_STOP
    09:20:40  SELL RAINBOW     74 @ 1420.25   TRAILING_STOP
              CAPLIPOINT still open, holding a seat

    10:38     NUVAMA at 26.65x its normal volume
              -> "book full (4 positions)"

A real trade lost to a maintenance tool that should never have been
runnable in that state. It also wrote three exits into trade memory
that never happened, so INTELLECT and RAINBOW are each recorded twice
-- once as the real trailing stop, once as a phantom.

THE RIGHT PATH while the bot is up is the dashboard's SELL button,
which reaches the running process. That is what owns the book.
"""

import inspect
from pathlib import Path

import tools.flatten_carried as flatten


def test_it_refuses_when_the_bot_is_running(monkeypatch, capsys):
    monkeypatch.setattr(flatten, "the_bot_is_running", lambda: True)
    monkeypatch.setattr("sys.argv", ["flatten_carried.py", "--close"])
    assert flatten.main() == 1, "it ran anyway while the bot was up"
    said = capsys.readouterr().out
    assert "REFUSING" in said
    assert "SELL" in said, "it does not say what to do instead"


def test_it_still_works_when_nothing_is_running(monkeypatch):
    """The tool has a real job -- clearing a book before a session or
    after one. A guard that refused always would be no use."""
    monkeypatch.setattr(flatten, "the_bot_is_running", lambda: False)
    monkeypatch.setattr("sys.argv", ["flatten_carried.py"])
    assert flatten.main() != 1


def test_the_guard_runs_before_anything_is_read():
    """It must refuse BEFORE touching the state file, not after."""
    src = inspect.getsource(flatten.main)
    refuse = src.find("the_bot_is_running()")
    reads = src.find("json.load(open(STATE")
    assert refuse != -1 and reads != -1
    assert refuse < reads, "it reads the book before deciding to refuse"


def test_it_detects_the_bot_by_asking_the_dashboard():
    """A PID check would miss a bot started another way and would catch
    an unrelated python process. The snapshot answers the actual
    question: is something serving the book right now."""
    src = inspect.getsource(flatten.the_bot_is_running)
    assert "SNAPSHOT" in src


def test_the_incident_is_written_down_where_it_happened():
    """The next person to add a file-editing maintenance tool needs to
    find this, not rediscover it with a live book."""
    src = Path("tools/flatten_carried.py").read_text(encoding="utf-8")
    assert "NUVAMA" in src and "session_state.json" in src
