"""
==========================================================
The switch is on the screen, not in a source file
==========================================================

    "you give me a control button in dashboard not in code files.
     control = bot trading on / off ; ON = bot will trade & OFF =
     bot will [not] trade"
    "everything i need control over the bot. it must follow me .
     not i needs to go back on bot."
                                -- operator, 5 August 2026

WHAT WAS WRONG
--------------
Arming the bot meant editing config.py line 1406 and restarting the
process. That is a deployment, not a control. It cannot be undone in
the two seconds that matter when something is going wrong, and it
cannot be done at all from a phone.

THE FOUR RULES
--------------
1. It flips the ENGINE at runtime. Next tick, no restart.
2. The page reads the state back OFF THE ENGINE, never off config. A
   button that says TRADING while the engine only alerts is a lie
   about his own money.
3. OFF stops NEW entries only. Every open position keeps its stop,
   its trail and its target. Abandoning live money because he stopped
   buying would be the opposite of control.
4. A restart returns to watching. If the bot dies at 11:00 and comes
   back while he is away from the desk, it must come back watching.

Author : H&M Opportunity Trader
==========================================================
"""

import inspect

from dashboard.state import DashboardState


class FakeEngine:
    def __init__(self, alert_only=True, held=0):
        self.alert_only = alert_only
        self.open_positions = {f"S{i}": {} for i in range(held)}


def state(engine):
    got = DashboardState.__new__(DashboardState)
    got.engine = engine
    return got


# ---------------------------------------------------------------
# 1. THE PAGE TELLS THE TRUTH ABOUT THE ENGINE
# ---------------------------------------------------------------
def test_watching_reads_as_off():
    got = state(FakeEngine(alert_only=True))._bot_trading()
    assert got["on"] is False and got["known"] is True
    assert "places nothing" in got["note"]


def test_trading_reads_as_on_and_says_so_plainly():
    got = state(FakeEngine(alert_only=False))._bot_trading()
    assert got["on"] is True
    assert "REAL" in got["note"]


def test_it_reads_the_engine_not_the_config():
    """config.ALERT_ONLY_MODE is the STARTUP value. Once he has
    touched the switch they disagree, and the engine is the one
    holding his money."""
    src = inspect.getsource(DashboardState._bot_trading)
    assert "alert_only" in src
    assert "ALERT_ONLY_MODE" not in src, (
        "the panel is reading the config file instead of the engine")


def test_no_engine_is_reported_as_unknown_not_as_off():
    """"Off" is a state he chose. "I cannot tell" is not the same
    thing and must not be drawn as though it were."""
    got = state(None)._bot_trading()
    assert got["known"] is False


def test_a_silent_engine_is_also_unknown():
    class Mute:
        alert_only = None
    assert state(Mute())._bot_trading()["known"] is False


def test_open_positions_are_counted_beside_the_switch():
    got = state(FakeEngine(alert_only=False, held=3))._bot_trading()
    assert got["open_positions"] == 3


def test_the_restart_behaviour_is_stated_not_hidden():
    """The one thing about this switch that would surprise him."""
    assert state(FakeEngine())._bot_trading()["resets_on_restart"] is True


def test_the_switch_is_in_the_snapshot():
    """_build() is what fills the snapshot get_snapshot() hands out --
    checked against the real class rather than assumed from the
    getter's name."""
    src = inspect.getsource(DashboardState._build)
    assert '"bot_trading"' in src


# ---------------------------------------------------------------
# 2. THE ENDPOINT FLIPS THE ENGINE AND NOTHING ELSE
# ---------------------------------------------------------------
def _endpoint(code_only=False):
    src = open("dashboard/server.py", encoding="utf-8").read()
    start = src.find('@app.post("/api/bot_trading/{state}")')
    assert start > 0, "the switch has no endpoint"
    body = src[start:src.find("@app.", start + 10)]
    if not code_only:
        return body
    # Strip the docstring and the comments. Seven times now I have
    # asserted against prose I wrote myself and called it a test --
    # this one tripped on the word "config.py" inside the paragraph
    # explaining why it must never touch config.py.
    import re
    body = re.sub(r'"""[\s\S]*?"""', "", body)
    return re.sub(r"^\s*#.*$", "", body, flags=re.M)


def test_turning_it_on_needs_the_operator_token():
    """A view-only visitor must never be able to arm real orders."""
    assert "_require_operator(request)" in _endpoint()


def test_it_sets_the_live_switch_not_alert_only():
    """---- THE SWITCH MOVED. 31 August 2026. ----

    It used to set engine.alert_only = not want_trading, so OFF meant
    the bot placed nothing at all. That third state produced 65 alerts
    and 0 trades on 31 August.

    "keep simple ON = REAL TRADES . OFF = PAPER TRADES". The bot always
    trades now; the endpoint sets execution.live and leaves alert_only
    off in both positions.
    """
    body = _endpoint()
    assert "execution.live = bool(want_trading)" in body
    assert "engine.alert_only = False" in body


def test_it_does_not_write_the_config_file():
    """A restart must return to watching. Persisting the armed state
    would mean a crash at 11:00 brings the bot back trading while he
    is away from the desk."""
    body = _endpoint(code_only=True)
    for forbidden in ("open(", "config.py", "write", "ALERT_ONLY_MODE ="):
        assert forbidden not in body, forbidden


def test_it_never_touches_an_open_position():
    """OFF governs NEW entries. Stops and trails keep running."""
    body = _endpoint(code_only=True)
    for forbidden in ("_exit(", "flatten", "close_all", "square_off"):
        assert forbidden not in body, forbidden
    assert "stops and trails" in _endpoint()


def test_arming_is_announced_loudly():
    body = _endpoint()
    assert "REAL" in body


# ---------------------------------------------------------------
# 3. THE BUTTON IS ON THE PAGE AND BEHAVES
# ---------------------------------------------------------------
# ---- IT MOVED WITH HIM. 13 August 2026. ----
#
# This read dashboard/static/screen.html. He moved to /board on
# 9 August, and on 13 August the four pages were collapsed to two --
# /board for trading, /full for diagnostics -- with app.html and
# screen.html deleted as a third and fourth page doing neither.
#
# The BEHAVIOUR these tests defend has not changed and still matters:
# the switch must be drawn, must call the endpoint, must confirm when
# ARMING and never when stopping, and must refuse a view-only visitor.
# Only the page it lives on moved.
#
# board.html writes the command on the button itself --
# data-arm="on" / data-arm="off" -- rather than deriving it from a
# BOT_ON variable, because a stale variable once meant every click
# sent "on" and there was no way to switch off.
PAGE = open("dashboard/static/board.html", encoding="utf-8").read()


def test_the_button_is_rendered_on_the_trading_screen():
    assert 'data-arm="on"' in PAGE and 'data-arm="off"' in PAGE, (
        "the ON/OFF buttons are not on the board")
    assert "paintState(" in PAGE, "they are never painted with live state"


def test_the_button_calls_the_endpoint():
    assert "/api/bot_trading/" in PAGE


def test_the_command_is_in_the_markup_not_in_a_variable():
    """A stale BOT_ON once made every click send 'on', leaving no way
    to switch off. The button carries its own command."""
    assert 'getAttribute("data-arm")' in PAGE


def test_arming_asks_first_and_stopping_also_confirms():
    """Both directions confirm on this page -- switching a live bot
    off mid-session is also worth one keystroke of thought, and the
    text differs so he can see which he is about to do."""
    block = PAGE[PAGE.find('getAttribute("data-arm")'):]
    block = block[:block.find("paintState(arm ===")]
    assert "confirm(ask)" in block
    assert 'arm === "on"' in block, (
        "the two confirmations are not distinguished, so he cannot see "
        "which direction he is about to send")
    assert "OPEN NEW POSITIONS" in block, (
        "the ARM confirmation does not say what it permits")


def test_a_view_only_visitor_gets_no_switch():
    block = PAGE[PAGE.find('getAttribute("data-arm")'):]
    assert "if (!IS_OPERATOR)" in block[:400], (
        "a read-only link can operate the switch")
    assert "read-only link" in PAGE, (
        "a view-only visitor is not told WHY the switch does nothing")
