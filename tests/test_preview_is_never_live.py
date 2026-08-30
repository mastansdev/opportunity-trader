"""
==========================================================
A preview that could place an order would be the bug
==========================================================

    RuntimeError: TRADING_MODE is LIVE but no Dhan client was
    provided. Refusing to start -- a bot you believe is live and
    which is only pretending is the worse failure.
                                    -- 1 August 2026

The operator ran tools/dashboard_preview.py to look at the new
earnings chips and got that instead.

trading/execution.py is RIGHT and its guard is not to be touched. It
is the thing that stops main.py ever paper-trading a session believed
to be real, and weakening it to make a dev tool start would be trading
a real protection for a convenience.

The fault was in the preview. Its own banner promises

    "REPLAY: read-only, no broker, no orders possible"

and it then asked Engine for an executor built in LIVE mode. Both
statements could not be true.

THE FIX, AND ITS ONE DIRECTION
------------------------------
The preview forces config.TRADING_MODE to PAPER for its own process,
before trading.execution is imported anywhere -- once that module runs
`from config import TRADING_MODE` the value is bound and a later
change is ignored.

It can only ever turn LIVE into PAPER. There is no path here that
turns PAPER into LIVE, and that asymmetry is the whole point: this
file exists to make sure nobody later "fixes" the preview by relaxing
execution.py, and to make sure the override never leaks into main.py.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

PREVIEW = open("tools/dashboard_preview.py", encoding="utf-8").read()
EXECUTION = open("trading/execution.py", encoding="utf-8").read()
MAIN = open("main.py", encoding="utf-8").read()


def _code_only(src):
    """The file with its comments and docstrings removed.

    Both of the first two attempts at these tests failed against
    PROSE: "wired to a bare Engine()" in the preview's own docstring
    counted as a call to Engine, and a comment in main.py mentioning
    dashboard_preview counted as an import of it. A test that reads
    documentation as code is worse than no test, because it fails on
    the day someone improves a comment.
    """
    import io
    import tokenize

    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.line.strip().startswith(
                    ('"""', "'''", 'r"""', "f'''")):
                continue
            out.append((tok.type, tok.string, tok.start, tok.end, tok.line))
    except tokenize.TokenError:
        return src
    return tokenize.untokenize(out)


PREVIEW_CODE = _code_only(PREVIEW)
MAIN_CODE = _code_only(MAIN)


# ---------------------------------------------------------------
# 1. THE GUARD IN execution.py IS UNTOUCHED
# ---------------------------------------------------------------
def test_live_still_refuses_to_start_without_a_broker():
    """The line the operator saw. It must keep existing."""
    assert "no Dhan client was provided" in EXECUTION
    assert "Refusing to start" in EXECUTION


def test_live_still_requires_the_second_switch():
    assert "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS" in EXECUTION


def test_paper_is_the_only_fallback():
    """If the LIVE branch is not taken, the executor is PaperExecution
    and nothing else. A third branch is where a "sort of live" mode
    would be born."""
    assert EXECUTION.count("self.executor = ") == 2
    assert "self.executor = PaperExecution" in EXECUTION


# ---------------------------------------------------------------
# 2. THE PREVIEW FORCES PAPER, AND ONLY EVER PAPER
# ---------------------------------------------------------------
def test_the_preview_forces_paper():
    assert '_config.TRADING_MODE = "PAPER"' in PREVIEW


def test_the_preview_never_forces_live():
    """The asymmetry that matters. Nothing in this file may assign
    LIVE to the trading mode."""
    for hit in re.finditer(r"TRADING_MODE\s*=\s*[\"'](\w+)[\"']", PREVIEW):
        assert hit.group(1) == "PAPER", (
            f"the preview assigned TRADING_MODE = {hit.group(1)!r}")


def test_the_override_happens_before_execution_is_imported():
    """`from config import TRADING_MODE` binds the value at import.
    An override afterwards is silently ignored, which would look
    exactly like this fix working."""
    assert "trading.execution" in PREVIEW and "not in sys.modules" in PREVIEW
    forced = PREVIEW_CODE.index("_config.TRADING_MODE")
    for later in ("from core.engine import", "Engine(", "MasterLoader()"):
        found = PREVIEW_CODE.find(later)
        if found != -1:
            assert forced < found, (
                f"the mode must be forced before {later!r}")


def test_the_operator_is_told_the_mode_was_changed():
    """A mode nobody can see is how a preview gets mistaken for the
    real bot."""
    assert PREVIEW.count("TRADING_MODE forced") >= 2, (
        "both the replay and the live-quote banner must say it")


# ---------------------------------------------------------------
# 3. IT MUST NOT LEAK
# ---------------------------------------------------------------
def test_config_on_disk_says_paper_because_he_chose_paper():
    """This asserted LIVE until 9 August 2026.

        "lets bot trade in paper mode but dashboard must show me as we
         both agreed . i'll trade manually"

    The test was right about the DANGER and wrong about the direction.
    Its point is that the preview tool's override must never reach
    config.py -- the mode on disk has to be a decision he made, not a
    side effect of a tool that ran. That still holds; the decision has
    simply changed.

    PAPER changes the executor only. Real ticks, real cards, real
    board, simulated fills.
    """
    config = open("config.py", encoding="utf-8").read()
    assert re.search(r"^TRADING_MODE\s*=\s*[\"']PAPER[\"']", config, re.M), (
        "config.py must say PAPER -- his 9 August decision. If this "
        "fails, check whether a tool wrote to config.py or whether the "
        "operator deliberately went live again.")


def test_main_does_not_import_the_preview():
    """The only way the override could reach the real bot.

    Mentioning the preview in a comment is fine and useful; IMPORTING
    it would run the override inside the live process.
    """
    assert not re.search(r"^\s*(import|from)\s+.*dashboard_preview",
                         MAIN_CODE, re.M)


@pytest.mark.parametrize("tool", [
    "tools/preflight.py", "tools/telegram_catchup.py",
    "tools/build_stock_events.py",
])
def test_no_other_tool_touches_the_trading_mode(tool):
    try:
        src = open(tool, encoding="utf-8").read()
    except FileNotFoundError:
        pytest.skip(f"{tool} not present")
    assert not re.search(r"TRADING_MODE\s*=", src), (
        f"{tool} assigns TRADING_MODE -- only the preview may, and only "
        f"to PAPER")


# ---------------------------------------------------------------
# LOOKING AT THE PANEL IS NOT A TELEGRAM FETCH -- 2 August 2026
# ---------------------------------------------------------------
#
# The preview polled Telegram before drawing anything. On a weekend
# backlog that is ten to twenty minutes of downloading and OCRing
# photos, and the operator -- who only wanted to LOOK at the dashboard
# after a change -- pressed Ctrl+C mid-download and got a traceback:
#
#     File "core/image_text.py", line 219, in fetch
#     ...
#     KeyboardInterrupt
#
# Nothing had failed. The tool was doing an expensive job nobody asked
# for, and then reporting the interruption as a crash.

def test_the_preview_can_skip_the_telegram_fetch():
    """Everything the panel draws is already in the databases."""
    src = open("tools/dashboard_preview.py", encoding="utf-8").read()
    assert '"--no-fetch" in sys.argv' in src


def test_ctrl_c_during_a_fetch_is_not_reported_as_a_failure():
    """Stopping a download is an ordinary thing to do, and the panel
    still has every stored message to draw from."""
    src = open("tools/dashboard_preview.py", encoding="utf-8").read()
    block = src[src.find('if "--no-fetch" in sys.argv:'):]
    block = block[:block.find("dashboard_state = DashboardState")]
    assert "except KeyboardInterrupt" in block
    assert block.find("except KeyboardInterrupt") < block.find(
        "except Exception"), (
        "KeyboardInterrupt must be caught BEFORE the general handler, "
        "or it is reported as 'Telegram unavailable'")


def test_the_fetch_warns_that_it_is_slow():
    """The operator had no way to know the wait was a photo backlog
    rather than a hang."""
    src = open("tools/dashboard_preview.py", encoding="utf-8").read()
    assert "--no-fetch to skip it" in src


def test_no_fetch_still_reads_the_stored_channels():
    """---- NO FETCH IS NOT NO TELEGRAM. 30 August 2026. ----

        "show me in another tab named Telegram"   -- 30 August

    --no-fetch set telegram = None, so the whole panel went dark. Every
    column on the new Telegram tab -- last post, when the bot read it,
    how late, pictures read -- comes out of data/telegram.db and needs
    no network at all. --no-fetch means "do not go and GET new
    messages", not "pretend there are none".

    Which is the exact fault this file already guards elsewhere: a
    preview that silently shows LESS than main.py is indistinguishable
    from a broken panel, and checking panels outside market hours is
    the whole reason the script exists.
    """
    src = open("tools/dashboard_preview.py", encoding="utf-8").read()
    block = src[src.find('if "--no-fetch" in sys.argv:'):]
    block = block[:block.find("dashboard_state = DashboardState")]
    assert "TelegramFeed(client=None" in block, (
        "--no-fetch leaves the Telegram tab empty; it must still read "
        "the stored channels")


def test_the_read_only_feed_cannot_reach_the_network():
    """client=None is the point: poll() refuses rather than fetching."""
    from core.telegram_feed import TelegramFeed

    feed = TelegramFeed(client=None)
    assert feed.poll() == 0
    assert "no Telegram client" in (feed._last_error or "")
