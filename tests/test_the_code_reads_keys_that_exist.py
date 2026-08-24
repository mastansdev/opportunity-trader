"""Every key and attribute the code reads must exist on the real thing.

    "all files had some or other errors to be fixed. until i see & ask,
     u will not even touch them"      -- operator, 24 August 2026

He is right that the pattern was: a bug exists, it is invisible, and it
is found only when he happens to read a line of terminal output. Four
in one week, all the same shape -- code reading a name the object does
not have, failing SILENTLY rather than raising:

    position.get("stop")            -> None. "[CARRY] ... stop None"
                                       for three positions that had
                                       stops of 1358.55, 648.90, 145.55
    dashboard_state.snapshot()      -> AttributeError x487. The movers
                                       finder never ran once.
    engine.results_calendar         -> AttributeError x487. The results
                                       half of the watchlist never
                                       populated.
    "OrderBook Pulse" vs
    "orders_pulse"                  -> the folder hands over usernames,
                                       so a priority list of display
                                       names matched nothing.

A dict .get() returns None and a getattr in a try/except returns
nothing. Both look like "no data today", which is indistinguishable
from the truth until somebody reads the log.

This test reads the REAL objects -- a real stored position, the real
Engine and DashboardState classes -- and checks the names the source
actually asks for against them.
"""

import ast
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "data", "session_state.json")

SKIP_DIRS = (".git", "__pycache__", "tests", ".venv", "backtest", "logs")


def _python_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _tree(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return ast.parse(handle.read())
    except (SyntaxError, OSError):
        return None


def _real_position_keys():
    if not os.path.exists(STATE):
        return None
    with open(STATE, encoding="utf-8") as handle:
        book = (json.load(handle).get("open_positions") or {})
    keys = set()
    for position in book.values():
        if isinstance(position, dict):
            keys |= set(position)
    return keys or None


# ---- KNOWN, UNVERIFIED. Recorded rather than silently allowed. ----
#
# Found by this test on 24 August and NOT fixed, because the operator
# asked for a plan followed rather than opportunistic edits. Each is
# a `position.get(X)` where X is not on a stored position, so it can
# only ever return the default:
#
#   core/shock.py        symbol, change_pct, pnl   -- no defaults
#   dashboard/state.py   change_pct (HAS a default), pnl (does not)
#
# Whether these are bugs depends on whether the caller passes an
# ENRICHED position. That has to be established per call site, not
# assumed either way. Until then they are pinned here so the count
# cannot grow quietly.
# RESOLVED 24 August 2026, by reading each call site:
#
#   core/shock.py x3  -- FALSE POSITIVES. assess() is handed the
#     enriched dict that dashboard/state.py builds, which really does
#     carry symbol/change_pct/pnl. The variable is named `position`
#     but is not a stored position.
#   dashboard/state.py change_pct -- correct, it has a fallback to a
#     computed `pct`.
#   dashboard/state.py pnl -- REAL, and fixed. There is no such key,
#     so it returned None every time and the shock banner showed a
#     blank P&L for every open position during the one event where it
#     matters. It now falls back to (last - entry) * qty. The READ
#     remains -- an enriched caller may still supply it -- which is
#     why it stays listed here.
#
# Four of five were noise. That ratio is why this list is reviewed
# per call site and never extended merely to silence a failure. Each
# entry means "checked, and safe because of a fallback", never
# "unknown".
KNOWN_UNVERIFIED = {
    ("core/shock.py", "symbol"),
    ("core/shock.py", "change_pct"),
    ("core/shock.py", "pnl"),
    ("dashboard/state.py", "change_pct"),
    ("dashboard/state.py", "pnl"),
}


def _position_key_reads():
    """Every `position.get("X")` in the repo, with its file."""
    out = []
    for path in _python_files():
        tree = _tree(path)
        if tree is None:
            continue
        rel = os.path.relpath(path, REPO).replace(os.sep, "/")
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "position"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            out.append((rel, node.args[0].value))
    return out


def test_no_new_position_key_is_read_that_does_not_exist():
    """The `stop` bug, and anything shaped like it."""
    real = _real_position_keys()
    if real is None:
        pytest.skip("no stored positions on this machine to check against")

    unknown = {(rel, key) for rel, key in _position_key_reads()
               if key not in real}
    new = unknown - KNOWN_UNVERIFIED
    assert not new, (
        "code reads position keys that no stored position has:\n  "
        + "\n  ".join(f"{rel}: position.get({key!r})"
                      for rel, key in sorted(new))
        + "\n\nEither the key is wrong, or the caller passes an enriched "
          "position -- establish which, do not add it to the allowlist "
          "to make this pass.")


def test_stop_specifically_is_never_read_off_a_position():
    """The one he found. A position has initial_stop / atr_stop."""
    real = _real_position_keys()
    if real is None:
        pytest.skip("no stored positions to check against")
    assert "stop" not in real
    offenders = [rel for rel, key in _position_key_reads() if key == "stop"]
    assert not offenders, (
        f"position.get('stop') is back in {offenders} -- it returns None "
        f"for every position. Use Engine._live_stop_price().")


def test_the_allowlist_only_holds_things_that_still_exist():
    """A stale allowlist hides the next one."""
    found = set(_position_key_reads())
    stale = {entry for entry in KNOWN_UNVERIFIED if entry not in found}
    assert not stale, (
        f"these were fixed or removed -- delete them from "
        f"KNOWN_UNVERIFIED: {sorted(stale)}")


# ==========================================================
#  THE ATTRIBUTE HALF
# ==========================================================
#   dashboard_state.snapshot()   -- 487 AttributeErrors in 37 minutes
#   engine.results_calendar      -- 487 more, same session
#
# Both were caught in a try/except that logged a diagnostic, so they
# read as "no data today" for weeks. Scoped to the two places where
# the type is PROVABLE -- `dashboard_state` in main.py is a
# DashboardState, `self.engine` in dashboard/state.py is an Engine --
# because a repo-wide scan cannot tell those from a SQLAlchemy engine
# and drowns in false positives.

def _known_attrs(cls):
    import inspect
    import re
    got = set(dir(cls))
    try:
        got |= set(re.findall(r"self\.([a-z_][a-z0-9_]*)\s*=",
                              inspect.getsource(cls)))
    except (OSError, TypeError):
        pass
    return got


def _unknown_attrs(path, matches, known):
    tree = _tree(os.path.join(REPO, path))
    if tree is None:
        return set()
    return {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and matches(node.value)
            and node.attr not in known}


def _is_dashboard_state(value):
    return isinstance(value, ast.Name) and value.id == "dashboard_state"


def _is_self_engine(value):
    return (isinstance(value, ast.Attribute) and value.attr == "engine"
            and isinstance(value.value, ast.Name)
            and value.value.id == "self")


def test_main_only_calls_methods_dashboard_state_has():
    from dashboard.state import DashboardState
    unknown = _unknown_attrs("main.py", _is_dashboard_state,
                             _known_attrs(DashboardState))
    assert not unknown, (
        f"main.py calls dashboard_state.{sorted(unknown)} which does not "
        f"exist. `snapshot()` was this exact bug -- the real name is "
        f"get_snapshot().")


def test_the_dashboard_only_reads_engine_attributes_that_exist():
    from core.engine import Engine
    unknown = _unknown_attrs("dashboard/state.py", _is_self_engine,
                             _known_attrs(Engine))
    assert not unknown, (
        f"dashboard/state.py reads self.engine.{sorted(unknown)} which "
        f"does not exist. `results_calendar` was this exact bug.")


def test_the_detector_actually_detects():
    """Both tests above pass because the bugs are FIXED.

    A detector that would also pass on the broken code is worthless,
    so this feeds it the original faults and requires it to object.
    """
    from dashboard.state import DashboardState
    known = _known_attrs(DashboardState)
    assert "get_snapshot" in known
    assert "snapshot" not in known, (
        "DashboardState grew a snapshot() -- the main.py test above is "
        "no longer guarding anything")

    from core.engine import Engine
    assert "results_calendar" not in _known_attrs(Engine), (
        "Engine grew results_calendar -- the dashboard test above is no "
        "longer guarding anything")
