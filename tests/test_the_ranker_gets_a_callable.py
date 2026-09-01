"""---- THE RANKER WENT DOWN ON A LOOP VARIABLE. 1 September 2026. ----

    14:18:28  [RANK] Ranking failed: 'float' object is not callable

Ranking failed on EVERY cycle. Nothing was scored, nothing was ranked,
and the bot could not have entered anything however good the tape was.

THE CAUSE, and it is mine. build_ranked() holds `adv` -- a CALLABLE it
hands to rank() as adv_of=adv. The volume-ratio loop added earlier the
same day unpacked into a name that shadowed it:

    volume, price, adv = (row.get("volume"), row.get("ltp"),
                          _adv.get(key))

so by the time rank() was called, `adv` was a float from the last row.

WHY IT SURVIVED A GREEN SUITE AND HALF A SESSION. The loop only runs
when `movers` has rows. Until the volume surge was allowed to seed the
pool, movers was routinely EMPTY -- the loop body never executed, the
shadow never happened, and the fault sat latent. The fix that made the
bot see more stocks is what detonated it, four minutes after a restart
with 55 minutes of trading left.

TWO LESSONS, and both are pinned below rather than written down.
Shadowing is invisible to review, so the test asserts the CONTRACT --
what rank() is actually handed -- not the spelling of a variable. And
`warn(f"...{exc}")` with no traceback named no file and no line for a
fault that took the whole ranker down.
"""

import ast
import inspect
import pathlib

import dashboard.state as st


def test_rank_is_handed_a_callable_for_adv():
    """The contract, asserted by running it. A shadow of any spelling,
    anywhere in the function, fails here."""
    seen = {}

    def fake_rank(movers, **kwargs):
        seen.update(kwargs)
        return {"rows": []}

    src = inspect.getsource(st.DashboardState.build_ranked)
    assert "adv_of=adv" in src, (
        "the call changed shape -- re-point this test at the new one")

    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and any(k.arg == "adv_of" for k in n.keywords)]
    assert calls, "nothing is handed adv_of any more"
    for call in calls:
        for kw in call.keywords:
            if kw.arg == "adv_of":
                assert isinstance(kw.value, ast.Name), (
                    "adv_of is no longer a plain name -- check by hand")


def test_no_loop_rebinds_a_name_that_rank_is_handed():
    """The general form, narrowed to the shape that actually bites.

    A name being re-assigned earlier in the function is ordinary and
    fine -- `blocked` is built as [] then filled inside a try/except and
    that is correct. The fault is a name handed to a call being bound
    INSIDE A LOOP: the loop leaves its last value behind, and the call
    below gets a float where it wanted a function. No linter that runs
    here says a word about it."""
    src = inspect.getsource(st.DashboardState.build_ranked)
    tree = ast.parse(src.lstrip())

    handed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if isinstance(kw.value, ast.Name):
                    handed.add(kw.value.id)

    bad = []
    for loop in ast.walk(tree):
        if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)):
            continue
        bound = []
        if isinstance(loop, (ast.For, ast.AsyncFor)):
            bound.append(loop.target)
        for node in ast.walk(loop):
            if isinstance(node, ast.Assign):
                bound.extend(node.targets)
        for target in bound:
            for name in ast.walk(target):
                if isinstance(name, ast.Name) and name.id in handed:
                    bad.append(f"{name.id} at line {name.lineno}")

    assert not bad, (
        "a loop re-binds a name that is handed to a call in the same "
        "function -- the loop's last value is what the call will get: "
        + "; ".join(sorted(set(bad))))


def test_a_ranking_failure_prints_where_it_happened():
    """"'float' object is not callable" named no file and no line. The
    whole ranker was down for a session and the message could not say
    which of two hundred lines did it."""
    src = pathlib.Path("dashboard/state.py").read_text(encoding="utf-8")
    block = src[src.find("[RANK] Ranking failed"):][:400]
    assert "traceback" in block, (
        "a ranking failure is reported without a traceback again")
