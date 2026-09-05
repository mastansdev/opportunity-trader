"""A restart must not lose what was published while it was down.

    "if run stopped at 08 & restarted at 10 , then bot must get both
     news events info right . simultaneous or data after 08 published
     in channels + current run data , by dismissing the gaps."
                                    -- operator, 24 August 2026

catch_up() already did this. It ran only behind --catchup, so every
restart without that flag lost the outage window -- silently, because
a normal poll still returns the last 30 per channel and looks healthy.
Day Trader Telugu alone posts ~25 an hour.
"""

import inspect

import tools.collector as collector


def test_catch_up_is_the_default():
    sig = inspect.signature(collector.main)
    assert sig.parameters["catchup"].default is True


def test_the_opt_out_is_the_flag_now():
    src = inspect.getsource(collector)
    assert '"--no-catchup" not in sys.argv' in src, \
        "the flag must turn catch-up OFF, not on"


def test_the_run_loop_calls_catch_up_when_catchup_is_true():
    """The guard branch itself, read from the source of main().

    Not a mock that never runs: main() takes the reader lock, builds
    Telethon clients and opens four stores, so a fake that reaches
    catch_up() would be testing the fake. What CAN be asserted without
    lying is that the branch exists, is guarded by `catchup`, and that
    `catchup` defaults True -- and the previous version of this test
    asserted `0 == 0` while appearing to check all three.

    End to end this is verified by starting the collector and reading
    the line it prints: "Filling the gap since the last run."
    """
    import ast
    import textwrap
    src = textwrap.dedent(inspect.getsource(collector.main))
    tree = ast.parse(src)

    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name)                 and node.test.id == "catchup":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call)                         and isinstance(inner.func, ast.Attribute):
                    calls.append(inner.func.attr)
    # ---- THE GAP IS FILLED FORWARD NOW. 5 September 2026. ----
    #
    #     "in case of tools/collector not active then its
    #      patchup/recall must check bots own memory that it stored
    #      last data from each telegram channel & start from that last
    #      recvd time"                              -- the operator
    #
    # This asserted catch_up(), the BACKWARD page walk. Two mechanisms
    # were doing one job and the older one could only do half of it:
    # it stops after two pages that add nothing, and the pages either
    # side of a weekend hole are ground already held, so 183 posts sat
    # uncollected while it reported itself finished every morning.
    #
    # The job is split properly now and the guard still owns both
    # halves. Posts NEWER than the last one held come from poll()'s
    # forward first pass (since_id + reverse), which is precisely what
    # he described. Posts MISSING below that mark come from
    # fill_gaps(), which asks for them by number. The rule this test
    # protects -- that a restart does not silently lose the night -- is
    # unchanged; what fulfils it is not.
    assert "fill_gaps" in calls, \
        "main() must fill the holes under `if catchup:`"


def test_no_catchup_is_still_available():
    src = inspect.getsource(collector)
    assert "--no-catchup" in src
    # And the old flag name is gone from the usage line, so nobody is
    # told to type something that no longer changes anything.
    usage = src[:src.index("import os")]
    assert "--catchup " not in usage
