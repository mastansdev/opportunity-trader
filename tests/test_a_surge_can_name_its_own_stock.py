"""---- THE SURGE RULE HAD NEVER FIRED. 1 September 2026. ----

    "dycl starting 10:55 order flow confirmed surge in volume that
     usual . which exactly reason to trigger in buy"
                                                -- the operator

A volume surge has counted as a reason since 31 August. On 1 September
it had still not fired once, live, all session:

    grep -c "its normal volume -- something moved before the news did"
    0

    DYCL         +9.97%    32x its own normal pace    why=[]
    GODREJAGRO   +6.98%    89.6x                      why=[]

TWO faults, both of which had to be fixed before one line could print.
Each alone was enough to keep the rule silent forever, and the first
fix on 1 September removed neither -- which is why it changed nothing.

FAULT ONE -- A SWALLOWED NameError.
The loop that computes the ratios opens data/liquidity.json with
os.path.join, inside a `try: ... except Exception:`. dashboard/state.py
does not import os at module level -- only locally, inside two other
functions. So the open raised NameError, the except caught it, the adv
table came back empty, every ratio was None, and _volume_now was empty
on every cycle of every session. Nothing was ever logged, because that
except was written to survive a missing file.

FAULT TWO -- THE POOL WAS CIRCULAR.
_symbols_with_news_today() is the SEED for the candidate pool:

    movers = []
    movers = self._widen_by_reason(movers)

and everything it returned was a stock something had been FILED or
REPORTED about. So a stock whose only reason is its volume was never in
the pool, never had a ratio computed, never got a surge reason, and was
never a candidate. The rule was unreachable by construction: it needed
the stock to already have a reason in order to give it one.

These two are why "10x is the right bar" changed nothing on its own.
The bar was never the thing stopping it.
"""

import json
import os

import dashboard.state as st
from core.rules import SURGE_REASON_MIN_RATIO

# The real 1 September numbers, off the live board at 12:40.
LIVE_ROWS = [
    {"symbol": "DYCL",       "ltp": 542.75, "volume": 7279857},
    {"symbol": "GODREJAGRO", "ltp": 658.10, "volume": 9553419},
    {"symbol": "SSWL",       "ltp": 344.60, "volume": 13136071},
    {"symbol": "RELIANCE",   "ltp": 1400.0, "volume": 2000000},
]


class _Board:
    """Only the two methods under test, over the REAL liquidity table."""

    _surging_now = st.DashboardState._surging_now
    _symbols_with_news_today = st.DashboardState._symbols_with_news_today
    engine = None            # no news stores: only the volume can answer

    def __init__(self, rows=None):
        self._rows = LIVE_ROWS if rows is None else rows

    def _compute_gl_rows(self):
        return self._rows


def _has_adv():
    """Skip rather than lie on a box with no liquidity table built."""
    try:
        with open(os.path.join("data", "liquidity.json"),
                  encoding="utf-8") as fh:
            return bool((json.load(fh) or {}).get("adv_cr"))
    except Exception:                                      # noqa: BLE001
        return False


# ------------------------------------------------ fault one: the ratios

def test_the_ratios_are_actually_computed():
    """The whole of fault one. If os goes unimported again the except
    swallows it, this returns {}, and this test says so -- instead of
    the bot going quiet for a session with nobody knowing why."""
    if not _has_adv():
        return
    got = _Board()._surging_now()
    assert got, ("no ratios at all -- the adv table failed to load and "
                 "the exception was swallowed, exactly as on 1 Sept")
    assert got.get("DYCL", 0) > 10, got


def test_an_ordinary_stock_reads_far_below_the_bar():
    """A number that comes out huge for everything is not a measurement.
    RELIANCE on those volumes is a quiet day and must read as one."""
    if not _has_adv():
        return
    got = _Board()._surging_now()
    assert got.get("RELIANCE", 99) < SURGE_REASON_MIN_RATIO, got


def test_a_junk_row_does_not_stop_the_others():
    """It runs on the build path. One bad row may not cost the rest."""
    if not _has_adv():
        return
    rows = ([{"symbol": "JUNK", "ltp": None, "volume": None},
             {"symbol": None, "ltp": 1, "volume": 1}] + LIVE_ROWS)
    got = _Board(rows)._surging_now()
    assert "DYCL" in got
    assert "JUNK" not in got


# ------------------------------------------------- fault two: the seed

def test_a_surging_stock_gets_into_the_pool_on_volume_alone():
    """Fault two. DYCL had no filing and no news on 1 September -- its
    volume was the entire reason. If this fails the surge rule is
    unreachable again, however low the bar is set."""
    if not _has_adv():
        return
    named = {str(s).upper() for s in _Board()._symbols_with_news_today()}
    assert "DYCL" in named, (
        "a stock at 30x its normal pace is still not a candidate")


def test_a_quiet_stock_is_not_dragged_in_by_the_surge():
    """"never in to random stocks". The seed widens by the SURGE, not by
    having been on the board at all."""
    if not _has_adv():
        return
    class _NoSurge(_Board):
        def _surging_now(self):
            return {}

    with_surge = {str(s).upper()
                  for s in _Board()._symbols_with_news_today()}
    without = {str(s).upper()
               for s in _NoSurge()._symbols_with_news_today()}
    added = with_surge - without
    ratios = _Board()._surging_now()
    for symbol in added:
        assert ratios.get(symbol, 0) >= SURGE_REASON_MIN_RATIO, (
            f"{symbol} was added on {ratios.get(symbol)}x")


def test_the_seed_survives_a_broken_surge_lookup():
    """The news seed is the older and more important half. A fault in
    the volume half may not take it down with it."""
    class _Broken(_Board):
        def _surging_now(self):
            raise RuntimeError("no liquidity table")

    assert isinstance(_Broken()._symbols_with_news_today(), set)


# ------------------------------------------ the swallowed-import shape

def test_nothing_on_the_live_path_uses_a_module_it_never_imported():
    """The general form of fault one, and the part worth keeping.

    A bare `os.` inside a `try/except Exception`, in a file that does
    not import os, is INVISIBLE: it raises, the except eats it, the
    feature is silently dead and nothing is ever logged. That is how
    the surge rule stayed dead through a whole session.

    Grepping cannot find it. state.py contains "import os" twice --
    both inside other functions -- so the file looks fine and the
    module global does not exist. This resolves it per scope: a
    function sees its OWN imports (wherever in its body, including
    inside its try/if blocks) plus every enclosing scope's, and
    nothing else.

    Swept over core/, dashboard/, trading/ and main.py on 1 September
    2026: the state.py one was the only real instance."""
    import ast
    import pathlib

    def own(scope):
        """Names bound by an import anywhere in this scope, but not
        inside a nested def or class -- those are scopes of their own."""
        names, stack = set(), list(ast.iter_child_nodes(scope))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            if isinstance(node, ast.Import):
                names.update((a.asname or a.name.split(".")[0])
                             for a in node.names)
            stack.extend(ast.iter_child_nodes(node))
        return names

    def scopes(node, inherited, out):
        here = inherited | own(node)
        stack = list(ast.iter_child_nodes(node))
        while stack:
            child = stack.pop()
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((child, here | own(child)))
                scopes(child, here | own(child), out)
            elif isinstance(child, ast.ClassDef):
                scopes(child, here, out)
            else:
                stack.extend(ast.iter_child_nodes(child))
        return out

    watched = {"os", "json", "csv", "sqlite3", "math", "subprocess",
               "time", "re", "random", "shutil", "glob", "pickle"}
    live = ("core/", "dashboard/", "trading/", "main.py")
    bad = []
    for path in sorted(pathlib.Path(".").rglob("*.py")):
        name = str(path).replace("\\", "/")
        if "__pycache__" in name:
            continue
        if not (name == "main.py" or name.startswith(live)):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8",
                                            errors="ignore"))
        except SyntaxError:
            continue
        for fn, seen in scopes(tree, set(), []):
            # This scope's own statements only. ast.walk() would descend
            # into nested defs and blame the parent for a line the child
            # owns -- and the child may well import it itself.
            body, stack = [], list(ast.iter_child_nodes(fn))
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    continue
                body.append(node)
                stack.extend(ast.iter_child_nodes(node))
            for node in body:
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in watched
                        and node.value.id not in seen):
                    bad.append(f"{name}:{node.lineno} {fn.name}() "
                               f"{node.value.id}.{node.attr}")
    assert not bad, ("these raise NameError the moment they run, and an "
                     "except will hide it: " + "; ".join(sorted(set(bad))))
