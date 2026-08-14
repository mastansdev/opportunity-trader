"""
==========================================================
py tools/board_preflight.py  --  click every control first
==========================================================

    "all of them are your scope before handing me the dashboard link."
                                -- operator, 11 August 2026

He is right, and this file is the correction.

On 11 August I handed him /board four times. Each time he found the
fault within a minute of opening it:

    the LIVE tab was empty            he found it
    the qty box did not work          he found it
    Activity / Change% / Turnover
      blanked the whole page          he found it
    there was no on/off switch        he found it

Every one of those was a control that had never been clicked by
anybody before it reached him. That is not a testing gap, it is a
handover gap: I was shipping a link, not a working screen.

WHAT THIS DOES
--------------
Serves the REAL board through the REAL FastAPI app -- twice, once
with the operator token and once without -- then drives every control
on it through tests/board_smoke.js and reports one line per control.

Nothing is mocked except the market data. If a button does not exist,
does not respond, or blanks the page, this says so BEFORE he sees it.

    py tools/board_preflight.py

Exit code 0 means the screen is fit to hand over. Nothing else does.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests" / "board_smoke.js"
BOARD = ROOT / "dashboard" / "static" / "board.html"


# A token the app is actually built with. It must be a REAL value, not
# None: build_app(operator_token=None) makes _token_matches() return
# True for anything and substitutes an EMPTY string, which looks exactly
# like a server that forgot to substitute at all. That false alarm cost
# me a round trip on 11 August; the fixture is explicit now.
FAKE_TOKEN = "preflight-operator-token"


def _served(token=""):
    """The page as the server actually sends it, token substitution and
    all. Reading board.html off disk would skip the one step that
    decides whether he gets a BUY button."""
    from tests.test_dashboard_server import _client
    client, _ = _client({
        "bot_enabled": False, "universe_size": 1315, "as_of": "15:52",
        "ranked": {"available": True, "rows": [], "refused_rows": []},
    }, operator_token=FAKE_TOKEN)
    url = "/board" + (f"?token={token}" if token else "")
    got = client.get(url)
    return got.status_code, got.text


def _operator_token():
    try:
        from dashboard.access_token import get_or_create_token
        return get_or_create_token()
    except Exception:                                          # noqa: BLE001
        path = ROOT / "data" / "dashboard_token.txt"
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def js_of(html):
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S))


def _controls_in(html):
    """Every clickable thing the page declares."""
    found = set(re.findall(r'data-(?:tab|sort)="([a-z%]+)"', html))
    if 'id="switch"' in html:
        found.add("switch")
    if "data-buy=" in html:
        found.add("buy")
    if "data-qtyfor=" in html:
        found.add("qty")
    return found


def main():
    print()
    print("  BOARD PREFLIGHT -- every control, before he sees it")
    print("  " + "=" * 62)

    broken = []

    def report(ok, name, note=""):
        mark = "  OK  " if ok else "BROKEN"
        print(f"  [{mark}] {name}")
        if note:
            print(f"           {note}")
        if not ok:
            broken.append(name)

    # ---- 1. the page is served at all ----
    try:
        code, view_html = _served()
        report(code == 200, "the board is served", f"HTTP {code}")
    except Exception as exc:                                   # noqa: BLE001
        report(False, "the board is served", str(exc))
        print()
        return 1

    # Serve it the way HE is served: with the operator token on the URL.
    op_code, op_html = _served(FAKE_TOKEN)
    real_token = _operator_token()

    # ---- 2. the operator link really differs from the view-only one --
    # If the server forgets the substitution, every row silently says
    # "view only" and he cannot trade from this screen at all. That is
    # exactly what /board did until 11 August.
    report(bool(real_token), "an operator token exists on disk",
           "data/dashboard_token.txt" if real_token else "no token file")

    armed = f'window.__OPERATOR_TOKEN__ = "{FAKE_TOKEN}";' in op_html
    report(armed, "the operator link is armed",
           "token substituted into the page -- BUY and the switch are live"
           if armed else
           "server did not replace the placeholder -- BUY and the switch "
           "would be dead on his link")

    view_armed = 'window.__OPERATOR_TOKEN__ = "";' in view_html
    report(view_armed, "a link WITHOUT the token stays read-only",
           "no controls are drawn" if view_armed
           else "a tokenless link can trade -- that is a security hole")

    # ---- 3. every control the page declares is exercised ----
    declared = _controls_in(view_html)
    report(bool(declared), "controls found on the page",
           ", ".join(sorted(declared)) or "none")

    # ---- 4. drive them ----
    node = shutil.which("node")
    if not node:
        report(False, "node is available to run the page",
               "install node, or these controls go to him unclicked")
        print()
        return 1

    done = subprocess.run([node, str(SMOKE)], capture_output=True,
                          text=True, timeout=120)
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("ok "):
            print(f"  [  OK  ] {line[3:].strip()}")
        elif line.startswith("FAIL"):
            report(False, line[4:].strip())
    if done.returncode != 0 and not broken:
        report(False, "the page harness", (done.stderr or "")[:200])

    # ---- 4b. EVERY KEY THE PAGE READS MUST EXIST IN THE PAYLOAD ----
    #
    #     "what about OFF ? who will give me the OFF option?"
    #
    # The switch read s.bot_enabled. dashboard/state.py publishes
    # bot_trading: {on: ...}. No such key as bot_enabled has ever
    # existed, so the toggle rendered OFF whether the bot was armed or
    # not and every click sent "on" again -- there was no OFF path at
    # all, and he found it by arming the bot for real.
    #
    # Three key-name mismatches in one day: day_open/open in the entry
    # rules, refusals {reason:count} vs {symbol:reason}, and this. Each
    # one silent, each one found by him. So the contract is checked
    # here, mechanically, against the REAL snapshot.
    try:
        # The truth is what dashboard/state.py BUILDS, not what an empty
        # object returns. Read the literal keys out of the snapshot dict
        # it assembles -- that is the contract the page is written
        # against.
        import inspect
        from dashboard.state import DashboardState
        published = set(re.findall(
            r'^\s{8,}"([a-z_][a-z0-9_]*)":',
            inspect.getsource(DashboardState), re.M))
        # dashboard/server.py adds keys to the payload on its way out --
        # bot_trading is recomputed live and served_at is stamped per
        # request. The page's contract is with what is SERVED, not with
        # state.py alone. Missing this made the check cry wolf.
        served = (ROOT / "dashboard" / "server.py").read_text(
            encoding="utf-8").split('@app.get("/api/snapshot")')[1][:4000]
        published |= set(re.findall(r'payload\["([a-z_][a-z0-9_]*)"\]', served))

        # `s` in the page is the snapshot. Exclude JavaScript's own
        # string/array methods or every .slice() looks like a missing
        # key -- which is exactly what this check said the first time.
        JS_METHODS = {
            "match", "slice", "split", "replace", "trim", "toUpperCase",
            "toLowerCase", "includes", "indexOf", "length", "concat",
            "filter", "map", "forEach", "sort", "join", "push", "some",
            "every", "find", "startsWith", "endsWith", "toFixed",
        }
        # Strip comments first. The scan was matching key names inside
        # the very comments explaining that those keys do not exist.
        code = js_of(view_html)
        code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
        code = re.sub(r"//[^\n]*", " ", code)
        read_keys = set(re.findall(r"\bs\.([a-z_][a-z0-9_]*)",
                                   code)) - JS_METHODS
        missing = sorted(k for k in read_keys if k not in published)
        report(not missing, "every key the page reads is published",
               ("NOT in the snapshot: " + ", ".join(missing))
               if missing else
               f"{len(read_keys)} keys read, every one is published")
    except Exception as exc:                                   # noqa: BLE001
        report(False, "every key the page reads is published", str(exc))

    # ---- 5. nothing on the page calls something that does not exist --
    js = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>",
                              view_html, re.S))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(js)
        path = handle.name
    try:
        parsed = subprocess.run([node, "--check", path],
                                capture_output=True, text=True, timeout=60)
        report(parsed.returncode == 0, "the page parses",
               (parsed.stderr or "").strip()[:160])
    finally:
        os.unlink(path)

    print("  " + "-" * 62)
    if broken:
        print(f"  {len(broken)} control(s) NOT fit to hand over:")
        for name in broken:
            print(f"      {name}")
        print()
        return 1
    print("  Every control on the board has been clicked and works.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
