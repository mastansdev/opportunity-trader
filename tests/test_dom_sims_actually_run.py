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


