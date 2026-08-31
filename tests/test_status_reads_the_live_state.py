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
                    "THE SETTINGS THAT DECIDE WHAT IT DOES",
                    "WHEN IT LAST CLOSED A TRADE"):
        assert section in out.stdout, section


def test_it_names_the_settings_that_decide_behaviour():
    """These are the ones that were wrong, or silently not what he
    thought, on 31 August. Each has to be visible without asking me."""
    out = _run().stdout
    for setting in ("FORCE_SQUARE_OFF_AT_CLOSE",   # was off, carried 10 days
                    "ENABLE_SLOT_ROTATION",        # he stopped it; it was on
                    "ALERT_ONLY_MODE",             # froze the bot for 10 days
                    "EXIT_ON_MOMENTUM_EXHAUSTED"):
        assert setting in out, setting


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
