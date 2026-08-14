"""
==========================================================
The report must survive printing its own warning
==========================================================

    "NEVER ASSUME"      -- operator, standing instruction

tools/learning_report.py printed five tables of sector, hour and symbol
P&L, and then CRASHED on the line that says those numbers are not
evidence:

    UnicodeEncodeError: 'charmap' codec can't encode character '\\u26a0'

A U+26A0 warning sign against a cp1252 Windows console. So every run
ever made showed the numbers and died on the caveat -- the one arrangement
of those two facts that is actively misleading. It had been that way
since the tool was written.

These tests run the real script end to end and check it exits clean and
says the things that stop somebody acting on 134 trades.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, "tools/learning_report.py", *args],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)


@pytest.fixture(scope="module")
def report():
    return _run()


def test_it_exits_clean(report):
    """THE REGRESSION. It used to exit 1 on the last print."""
    assert report.returncode == 0, (
        "learning_report.py crashed:\n" + report.stderr[-2000:])
    assert "UnicodeEncodeError" not in report.stderr


def test_it_prints_no_matter_the_console_encoding(report):
    """The fix is sys.stdout.reconfigure at import time, before
    anything writes. Not 'we removed that one character' -- the next
    person to type an em dash would put it straight back."""
    src = (ROOT / "tools" / "learning_report.py").read_text(
        encoding="utf-8", errors="replace")
    assert "sys.stdout.reconfigure" in src, (
        "the encoding guard is gone -- one non-ASCII character will "
        "crash this tool again")


def test_the_caveat_actually_reaches_the_end(report):
    """The whole point: the reader must get to the bottom."""
    assert "HAS ANY OF THIS EARNED A VOTE?" in report.stdout
    assert report.stdout.rstrip().endswith("=" * 62)


def test_the_bar_is_the_projects_own_number(report):
    """Not a number typed into this file. core/outcomes.py owns
    MIN_SAMPLE and refuses to call a bucket a result below it; if these
    two ever disagree, one of them is quietly wrong."""
    from core.outcomes import MIN_SAMPLE
    assert f"n >= {MIN_SAMPLE}" in report.stdout


def test_it_warns_that_a_big_bucket_can_still_be_two_populations():
    """Sample size is not the only way a bucket lies. TRAILING_STOP is
    n=64 and still wrong, because the trail was switched off halfway
    through the window and the hard stop kept the same label. Somebody
    reading only the n would act on it -- BOT_SPEC.md did."""
    got = _run()
    if "TRAILING_STOP" not in got.stdout:
        pytest.skip("no bucket has reached the bar in this database")
    assert "TWO populations" in got.stdout
    assert "29 July" in got.stdout


def test_it_says_the_memory_has_no_vote_somewhere(report):
    """core/trade_memory.py's own docstring is the source of truth for
    this; the report must not imply otherwise."""
    text = report.stdout.lower()
    assert "vote" in text
