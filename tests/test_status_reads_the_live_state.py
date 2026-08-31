"""---- HE SHOULD NOT HAVE TO BELIEVE ME. 31 August 2026. ----

    "like this way u sounded very confident each time but in reality
     its opposite. how i can believe u now?"          -- the operator

On 31 August I told him the bot had made no trades and the board was
clean. It was holding NCC and CDSL, bought on 21 August. I had read the
closed-trades store and spoken as if I had read the system -- which is
the same mistake in every wrong thing I told him that day: one source
read, whole-system claim made, said with confidence.

tools/status.py exists so the answer never comes from a summary again.
These tests hold it to that: it reads live state, it says when
something is being carried, and it never prints a judgement.

The first run of it printed "could not read config" for half its
content, because it was missing the sys.path line every other tool in
that directory has. Silently wrong, in the file whose entire purpose is
not being silently wrong. That is the first test below.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "tools" / "status.py"


def _run(cwd=None):
    return subprocess.run([sys.executable, str(STATUS)],
                          capture_output=True, text=True,
                          cwd=str(cwd or ROOT))


def test_it_runs_and_every_section_reports():
    """The failure it shipped with: two of four sections printed
    'could not read config' and the other two looked fine."""
    out = _run()
    assert out.returncode == 0, out.stderr
    assert "could not read" not in out.stdout, (
        "a section failed silently:\n" + out.stdout)
    for section in ("WHOSE MONEY",
                    "WHAT IT IS HOLDING RIGHT NOW",
                    "THE RULES IT TRADES BY",
                    "WHEN IT LAST CLOSED A TRADE"):
        assert section in out.stdout, section


def test_it_answers_in_words_not_setting_names():
    """---- HE ASKED WHICH NUMBER WAS THE RISK. 31 August 2026. ----

    This screen used to print setting NAMES and values:

        RISK_PER_TRADE_RS     2500
        FIXED_STOP_LOSS_RS    1000
        FIXED_TARGET_RS       2500

    Four money numbers, no way to tell which decided anything -- and
    two of those three are DEAD, imported by core/engine.py and read by
    no line of it. A screen built so he would not have to trust a
    summary was printing dead settings beside live ones in identical
    formatting.

    Plain words on the left now, and only values something reads."""
    out = _run().stdout
    for phrase in ("Money it puts in each trade",
                   "Books profit at",
                   "How a position ends",
                   "Holds overnight",
                   "Buys only between"):
        assert phrase in out, phrase


def test_no_dead_setting_appears_on_the_screen():
    """FIXED_STOP_LOSS_RS and FIXED_TARGET_RS are imported once by
    core/engine.py and never read. If a value cannot change what the
    bot does, showing it can only mislead."""
    out = _run().stdout
    for dead in ("FIXED_STOP_LOSS_RS", "FIXED_TARGET_RS"):
        assert dead not in out, f"{dead} is dead and back on the screen"


def test_it_shows_no_setting_that_does_not_exist():
    """It printed EXIT_ON_MOMENTUM_EXHAUSTED <absent> after that setting
    was removed. A row saying "<absent>" is noise pretending to be a
    fact."""
    assert "<absent>" not in _run().stdout


def test_a_carried_position_is_called_out_not_just_listed(tmp_path,
                                                          monkeypatch):
    """Listing NCC in a table is not enough -- it WAS listed, on the
    dashboard, for ten days, and nobody read it as a problem. The line
    has to say the position is old and say what to do about it."""
    from tools import status

    state = {"open_positions": {
        "NCC": {"qty": 357, "entry_price": 149.82,
                "entry_time": "2026-08-21T12:41:57"}}}
    path = tmp_path / "session_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(status, "STATE", str(path))

    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k:
                        printed.append(" ".join(str(x) for x in a)))
    status.show_holdings("2026-08-31")
    text = "\n".join(printed)

    assert "NCC" in text
    assert "10 DAYS AGO" in text
    assert "carried" in text
    assert "flatten_carried" in text, "it says there is a problem and no fix"


def test_a_position_opened_today_is_not_called_carried(tmp_path,
                                                       monkeypatch):
    """A normal open position must not be flagged, or the warning stops
    meaning anything within a week."""
    from tools import status

    state = {"open_positions": {
        "ASHOKA": {"qty": 100, "entry_price": 120.0,
                   "entry_time": "2026-08-31T10:16:00"}}}
    path = tmp_path / "session_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(status, "STATE", str(path))

    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k:
                        printed.append(" ".join(str(x) for x in a)))
    status.show_holdings("2026-08-31")
    text = "\n".join(printed)

    assert "ASHOKA" in text
    assert "carried" not in text
    assert "flatten_carried" not in text


def test_an_empty_book_says_so(tmp_path, monkeypatch):
    from tools import status

    path = tmp_path / "session_state.json"
    path.write_text(json.dumps({"open_positions": {}}), encoding="utf-8")
    monkeypatch.setattr(status, "STATE", str(path))

    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k:
                        printed.append(" ".join(str(x) for x in a)))
    status.show_holdings("2026-08-31")
    assert "nothing open" in "\n".join(printed)


def test_it_prints_no_judgement():
    """The rule for this file. Every confidently wrong thing I told him
    was a judgement laid over a partial read. This screen reports and
    stops.

    'no reason' and 'unreadable' are not judgements -- they are facts
    about what could not be read, which is the opposite failure."""
    out = _run().stdout.lower()
    for word in ("looks fine", "healthy", "all good", "everything is",
                 "should be", "probably", "seems", "score"):
        assert word not in out, f"it is grading rather than reporting: {word}"


def test_it_survives_a_missing_state_file(tmp_path, monkeypatch):
    """A tool he reaches for when something is wrong must not itself
    fall over when something is wrong."""
    from tools import status

    monkeypatch.setattr(status, "STATE", str(tmp_path / "not_here.json"))
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k:
                        printed.append(" ".join(str(x) for x in a)))
    status.show_holdings("2026-08-31")
    assert printed  # it said something rather than raising


# ---- IT DESCRIBED BEHAVIOUR THAT HAD CHANGED. 31 August 2026. ----
#
# He ran this screen after the evening's work and three rows were false:
#
#   "Sells everything at 15:15 -- nothing is carried overnight"
#       Square-off had been turned OFF at his instruction. Nothing is
#       sold at 15:15 and positions ARE carried.
#   "Risk on each trade ... position is sized so a stop-out costs this"
#       Sizing moved to the MTF margin on 29 July.
#   "holds until a stop or 15:15"
#       It books when the buying dries up as well.
#
# The screen exists so he does not have to trust a summary, and it had
# quietly become one. The rows that were wrong were the ones stating
# behaviour from memory; the fix is that they read the settings.

def test_the_overnight_row_follows_the_square_off_setting():
    """This said "nothing is carried overnight" while carrying two
    positions for ten days."""
    from tools import status
    import config

    row = dict((label, fn) for label, fn, _ in status.RULES
               if callable(fn)).get("Holds overnight")
    assert row is not None, "the overnight row is gone"

    class _Off:
        FORCE_SQUARE_OFF_AT_CLOSE = False
        SQUARE_OFF_TIME = "15:15"

    class _On(_Off):
        FORCE_SQUARE_OFF_AT_CLOSE = True

    assert "YES" in row(_Off())
    assert "no" in row(_On()).lower() and "15:15" in row(_On())
    # and it agrees with the real config right now
    expected = ("YES" if not config.FORCE_SQUARE_OFF_AT_CLOSE else "no")
    assert row(config).lower().startswith(expected.lower())


def test_the_exit_row_lists_every_live_exit():
    """It said "a stop or 15:15" after the buying-dried-up exit went in,
    and after square-off came out. Both wrong in one line."""
    from tools import status

    row = dict((label, fn) for label, fn, _ in status.RULES
               if callable(fn)).get("How a position ends")
    assert row is not None

    class _Cfg:
        ENABLE_BOT_TRAILING_STOP = True
        FORCE_SQUARE_OFF_AT_CLOSE = False
        SQUARE_OFF_TIME = "15:15"

    got = row(_Cfg())
    assert "buying dries up" in got
    assert "stop" in got
    assert "15:15" not in got, "it claims a square-off that is switched off"

    _Cfg.FORCE_SQUARE_OFF_AT_CLOSE = True
    assert "15:15" in row(_Cfg())


def test_no_row_states_behaviour_the_settings_do_not_support():
    """The general rule. A row about what the bot DOES must read a
    setting -- a hardcoded sentence is a summary, and this file exists
    so he never has to trust one."""
    from tools import status

    out = _run().stdout
    import config

    if not config.FORCE_SQUARE_OFF_AT_CLOSE:
        assert "nothing is carried overnight" not in out
        assert "Sells everything at" not in out
    if config.MTF_MARGIN_PER_POSITION_RS:
        assert "sized so a stop-out costs this" not in out, (
            "the sizing row describes the pre-29-July rule")
