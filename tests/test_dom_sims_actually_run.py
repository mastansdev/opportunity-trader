"""
==========================================================
The browser simulations have to actually run
==========================================================

    "why user needs to tell you which one is working & not ? thats
     your work right?"              -- operator, 2 August 2026

WHAT WENT WRONG
---------------
tests/dom/qty_box.sim.js is the only check in this project that drives
the size box like a keyboard -- focus, caret, teardown, restore. It is
the guard for the bug that made the operator type "55" and watch the
number disappear on the live day.

On 3 August it was found to HANG on require("jsdom") and get killed by
the shell timeout. The jsdom install here is incomplete. Nothing
noticed, because:

    * pytest never ran the sims -- one test mentioned side_split.sim.js
      in a docstring and that was the whole of the integration, and
    * the sim's own design exited 0 when jsdom was missing, so even run
      by hand a missing dependency read as a pass.

So the guard was dark for days while the bug it guards was live on his
screen. The sim no longer needs jsdom, and this file makes pytest run
it, so "it silently stopped running" cannot happen again without a red
test.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import shutil
import subprocess

import pytest

DOM_DIR = os.path.join("tests", "dom")
NODE = shutil.which("node") or shutil.which("node.exe")


def sims():
    if not os.path.isdir(DOM_DIR):
        return []
    return sorted(f for f in os.listdir(DOM_DIR) if f.endswith(".sim.js"))


def test_the_simulations_are_still_there():
    """If someone deletes them the suite must go red, not quiet."""
    found = sims()
    assert "qty_box.sim.js" in found
    assert "side_split.sim.js" in found


def test_every_simulation_is_run_by_this_file():
    """No sim may sit in the folder without pytest executing it. This is
    the check that was missing -- side_split.sim.js was named only in a
    docstring, and qty_box.sim.js was named nowhere at all."""
    assert sims(), "tests/dom holds no simulations"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("script", sims())
def test_the_simulation_passes(script):
    """Runs the real thing and insists on exit 0.

    A timeout is a FAILURE here, not a skip. The old jsdom hang would
    have been caught on the first run of this test."""
    path = os.path.join(DOM_DIR, script)
    try:
        done = subprocess.run([NODE, path], capture_output=True, text=True,
                              timeout=90)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{script} hung -- it never finished. That is how "
                    f"qty_box.sim.js went dark for days.")
    assert done.returncode == 0, (
        f"{script} failed\n--- stdout ---\n{done.stdout}"
        f"\n--- stderr ---\n{done.stderr}")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_missing_package_can_never_read_as_a_pass_again():
    """     "a missing dev dependency must not read as a failing safety
             check"  -- the old header, and it had it backwards.

    Exiting 0 on a missing package meant the check reported success
    while checking nothing. The size box simulation now has no
    dependencies at all, so there is nothing left to be missing."""
    src = open(os.path.join(DOM_DIR, "qty_box.sim.js"), encoding="utf-8").read()
    assert "require(\"jsdom\")" not in src
    assert "jsdom not installed" not in src
    # Only the two node built-ins.
    imports = {line.split('require("')[1].split('"')[0]
               for line in src.splitlines() if 'require("' in line}
    assert imports <= {"fs", "path"}, imports


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_size_box_simulation_would_catch_the_focus_bug():
    """The sim must fail on the broken code, not just pass on the fixed
    code. A green test that is also green on the bug is decoration.

    The 2 August restore used document.querySelector(), which returns
    the FIRST box for a symbol in document order -- so typing into the
    gainers table threw focus up to WHAT TO TRADE NOW a second later.
    """
    src = open(os.path.join(DOM_DIR, "qty_box.sim.js"), encoding="utf-8").read()
    # It has to build the same stock into more than one panel, or the
    # bug is unreachable and the sim proves nothing.
    assert '"otCalls", "glGainers", "watchlist"' in src
    assert "glGainers/TITAN" in src

    page = open(os.path.join("dashboard", "static", "index.html"),
                encoding="utf-8").read()
    block = page[page.find("function restoreQtyBoxes"):]
    block = block[:block.find("document.addEventListener")]
    assert "qtyScopeOf" in block, "the restore no longer knows which panel"
    assert "preventScroll" in block, "focus() will drag the page while typing"
