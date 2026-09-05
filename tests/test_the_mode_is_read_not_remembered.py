"""---- ONE DIAL, READ THE SAME WAY EVERYWHERE. 3 September 2026. ----

    "the switch ON- REAL & OFF-PAPER both needed to reverify again."
    "but our work is not this i believe"
                                            -- the operator

I TOLD HIM THE SWITCH WAS WIRED TO THE WRONG DIAL. It is not, and
this docstring said so for an hour before I read far enough.

WHAT IS ACTUALLY TRUE. trading/execution._route():

    switch OFF  ->  paper. Nothing reaches Dhan.
    switch ON   ->  Dhan.

engine.alert_only is set False in BOTH positions, so the bot always
trades and the switch only chooses whose money. That is exactly his
rule, and it has been built correctly since 31 August.

WHAT WAS WRONG was what the screen SAID. Both messages described
rules the code no longer follows -- see the second half of this file.
The ON message in particular announced "nothing reaches Dhan" on the
strength of config.TRADING_MODE, which _route() never reads, so on a
machine with a Dhan client it would have routed REAL ORDERS while
claiming they were simulated.

WHAT THIS FILE DEFENDS is the precondition for all of it: TRADING_MODE
must be
readable at call time everywhere, so that the day the switch moves it,
no module is still holding the value it saw at import.

core/broker_sync._is_live() has said this in its own docstring for
weeks, and says why: "a value captured at import told him the bot was
placing REAL orders while TRADING_MODE said PAPER." Eight call sites
already read it live. core/broker_funds.py and main.py did not.

IN FAIRNESS TO THE OLD CODE: both of those read it only during
startup, before any flip could happen, so this was not the live bug I
first described to him. It is still the right shape -- a module-level
binding is a value that CANNOT follow the dial, and nobody should have
to remember which files are special.
"""

import ast
import os

# Files that legitimately DEFINE the value rather than consume it.
DEFINERS = {"config.py"}

ROOTS = ("core", "dashboard", "trading", ".")


def _python_files():
    for root in ROOTS:
        if root == ".":
            names = [f for f in os.listdir(".") if f.endswith(".py")]
            for name in names:
                yield name
            continue
        if not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            if "__pycache__" in base:
                continue
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(base, name)


def _binds_at_import(path):
    """`from config import TRADING_MODE` at module level, which freezes
    the value for the life of the process."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        try:
            tree = ast.parse(handle.read())
        except SyntaxError:
            return False
    for node in tree.body:                       # MODULE LEVEL ONLY
        if isinstance(node, ast.ImportFrom) and node.module == "config":
            for alias in node.names:
                if alias.name == "TRADING_MODE":
                    return True
    return False


def test_no_module_freezes_the_trading_mode_at_import():
    guilty = [p for p in _python_files()
              if os.path.basename(p) not in DEFINERS and _binds_at_import(p)]
    assert not guilty, (
        "these modules bind TRADING_MODE at import, so they cannot "
        "follow the dial once it moves: " + ", ".join(sorted(guilty)))


def test_broker_funds_follows_a_runtime_change():
    """The real assertion: flip it and see."""
    import config
    from core import broker_funds

    before = config.TRADING_MODE
    try:
        config.TRADING_MODE = "LIVE"
        assert broker_funds._mode() == "LIVE"
        config.TRADING_MODE = "PAPER"
        assert broker_funds._mode() == "PAPER"
    finally:
        config.TRADING_MODE = before


def test_a_missing_config_value_reads_as_paper():
    """The safe end. If the attribute is gone, this must not decide
    that real orders are fine."""
    import config
    from core import broker_funds

    before = config.TRADING_MODE
    try:
        del config.TRADING_MODE
        assert broker_funds._mode() == "PAPER"
    finally:
        config.TRADING_MODE = before


def test_broker_sync_still_reads_it_live():
    """It was already right, and must stay right -- its docstring is
    the reason this whole file exists."""
    with open(os.path.join("core", "broker_sync.py"), encoding="utf-8") as f:
        body = f.read()
    assert "from config import TRADING_MODE" in body
    assert "Read at CALL time, never cached" in body


# ==========================================================
# THE SWITCH SAYS WHAT IT DOES
# ==========================================================
#
#     "bot opens with Default OFF = paper trade , after clicking
#      ON = real trade mode . is this working right now or not.
#      just confirm me that"       -- operator, 3 September 2026
#
# It is working, and he was right to doubt it, because both messages
# were describing rules the code no longer follows:
#
#   ON  said "nothing reaches Dhan" on the strength of TRADING_MODE,
#       which trading/execution._route() never reads. With a Dhan
#       client present -- which is this machine -- ON routes REAL
#       ORDERS while the terminal claimed they were simulated.
#
#   OFF said "no new entries", which was the third state removed on
#       31 August. engine.alert_only is now set False in BOTH
#       positions; the bot always trades and the switch only chooses
#       whose money.
#
# A message that contradicts the code teaches him not to trust the
# screen, and that costs more than the bug.

def _server_source():
    with open(os.path.join("dashboard", "server.py"), encoding="utf-8") as f:
        return f.read()


def test_the_bot_trades_in_both_positions():
    """No third state. alert_only is off either way."""
    body = _server_source()
    # ---- ONE FUNCTION MOVES THE SWITCH NOW. 5 September 2026. ----
    #
    # These asserted on lines inside the endpoint. The endpoint no
    # longer writes the flags itself: the desk and the phone both go
    # through core.trading_gate.apply_switch(), because until then the
    # same OFF meant "still trading, on paper" on the desk and "stop
    # trading, alerts only" from Telegram -- the third state, still
    # reachable from his phone.
    #
    # So the assertion follows the behaviour to where it lives: the
    # endpoint must DELEGATE, and apply_switch must do the thing.
    import inspect

    from core.trading_gate import apply_switch
    _gate = inspect.getsource(apply_switch)
    assert "apply_switch" in body, (
        "the endpoint no longer moves the switch through the gate")
    # ---- THE FLAG IT CHECKED FOR IS RETIRED. 5 September 2026. ----
    #
    # This asserted apply_switch clears engine.alert_only, so that a
    # feed-guard disarm could be undone from the dashboard. Two things
    # have since changed and both remove the need:
    #
    #   the guard no longer disarms anything -- main.py wires it as
    #   _LiveGuard(disarm=None): "Nothing may turn trading off but him"
    #
    #   alert_only is gone entirely (the collapse to two, 5 Sep). The
    #   switch writes execution.live and nothing else, so there is no
    #   second flag left for anything to get stuck on.
    #
    # What must remain true is that the switch MOVES, from one place.
    assert "execution.live = bool(on)" in _gate
    assert "execution.live = bool(on)" in _gate


def test_the_on_message_asks_the_router_not_the_config():
    """/api/mode has always asked whether this process can reach Dhan.
    The switch message asked config.TRADING_MODE, which the router
    never consults."""
    body = _server_source()
    head = body.split("BOT TRADING IS ON")[0][-1200:]
    assert 'getattr(execution, "_live", None) is not None' in head, (
        "the ON message does not ask whether real orders are possible")


def test_the_off_message_does_not_claim_it_stops_trading():
    """It says PAPER now, because that is what OFF does."""
    body = _server_source()
    off = body.split("Bot trading OFF")[1][:220]
    assert "PAPER" in off, off
    assert "no new entries" not in off, (
        "the OFF message still describes the third state that was "
        "removed on 31 August")
