"""
Decision-correctness tests for the dashboard operator token:
stable across repeated calls (same as a restart), never empty,
never guessable-short.
"""

import os

from dashboard.access_token import get_or_create_token


def test_creates_a_token_when_none_exists(tmp_path):
    path = os.path.join(str(tmp_path), "token.txt")
    token = get_or_create_token(path=path)

    assert token
    assert len(token) >= 20  # not a trivially guessable short value
    assert os.path.exists(path)


def test_returns_the_same_token_on_a_second_call_not_a_new_one(tmp_path):
    """Stability across restarts -- an operator control link that
    changes every run isn't a link worth bookmarking."""
    path = os.path.join(str(tmp_path), "token.txt")
    first = get_or_create_token(path=path)
    second = get_or_create_token(path=path)

    assert first == second


def test_two_different_paths_get_two_different_tokens(tmp_path):
    path_a = os.path.join(str(tmp_path), "a.txt")
    path_b = os.path.join(str(tmp_path), "b.txt")

    token_a = get_or_create_token(path=path_a)
    token_b = get_or_create_token(path=path_b)

    assert token_a != token_b


def test_recovers_if_the_file_exists_but_is_empty(tmp_path):
    path = os.path.join(str(tmp_path), "token.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("")

    token = get_or_create_token(path=path)
    assert token  # regenerates rather than handing back an empty secret


# ---------------------------------------------------------------
# ONE LINK. PRINTED WHOLE. NOTHING TYPED BY HAND.
# ---------------------------------------------------------------
#     "why user needs to enter /screen ? why can't bot print the
#      complete link ?"
#     "why all these ? only one universal screen required for now.
#      no screen sharing to anyone."
#     "keep same dashboard for both main & preview"
#                                     -- operator, 4 August 2026
#
# First I made him append the path himself. Then I printed three links
# and made him pick. There is one operator and one page, so the address
# is "/" with the token already on it, and main.py and the preview
# print the same one -- otherwise a layout he approves in the preview
# is not the layout he trades on.
PRINTERS = ("main.py", "tools/dashboard_preview.py")


def _code(path):
    """Prose in docstrings and comments has passed these assertions
    before. Only the executable lines count."""
    src = open(path, encoding="utf-8").read()
    return "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))


def _printed(path):
    """Every f-string address the file prints."""
    import re
    return re.findall(r"\{_?base\}(/\S*?)\?token=", _code(path))


#: The one page. "/" until 12 August 2026, when he said:
#:
#:     "this is the old dashboard. we moved to new one with
#:      http://127.0.0.1:8000/board"
#:
#: "/" serves app.html (6 August). "/board" serves board.html
#: (9 August) -- the newer screen, deliberately one table. The rule
#: this file enforces is unchanged: ONE address, the same one
#: everywhere, with the token already on it. Only which address moved.
THE_PAGE = "/board"


def test_every_printer_prints_the_one_page_with_the_token_on_it():
    for path in PRINTERS:
        assert "?token={" in _code(path), path
        assert _printed(path), path
        assert set(_printed(path)) == {THE_PAGE}, (path, _printed(path))


def test_no_printer_offers_a_second_address():
    """Three links and a 'safe to share' line meant deciding which one
    to click before he could look at a price."""
    for path in PRINTERS:
        assert len(set(_printed(path))) == 1, (path, _printed(path))


def test_the_preview_and_the_live_session_print_the_same_page():
    assert set(_printed("main.py")) == set(_printed("tools/dashboard_preview.py"))


def test_start_dashboard_prints_no_link_of_its_own():
    """Five lines came up on one start: three from start_dashboard and
    a boxed two from main.py. Both callers print their own banner, so
    anything printed here is only ever the duplicate."""
    server = _code("dashboard/server.py")
    assert "?token={operator_token}" not in server


def test_the_old_page_is_kept_reachable_and_unadvertised():
    """It still carries panels the clean screen has not absorbed --
    the watchlist and some POST tables. Not deleted to tidy a route,
    just not printed."""
    server = _code("dashboard/server.py")
    assert '@app.get("/full"' in server
    for path in PRINTERS:
        assert "/full?token=" not in _code(path), path


def test_every_old_link_still_lands_somewhere_usable():
    """His bookmarks must keep working.

    ---- THE PAGES BEHIND THEM CHANGED. 13 August 2026. ----
    This asserted that "/" and "/screen" both served screen.html. Four
    pages were collapsed to two that day -- /board for trading, /full
    for diagnostics -- and app.html and screen.html were deleted as a
    third and fourth page doing neither job.

    The GUARANTEE is unchanged and is what this now checks: no link he
    has ever been given may 404. They redirect to the board instead of
    serving a page of their own.
    """
    server = _code("dashboard/server.py")
    for retired in ('@app.get("/screen")', '@app.get("/old")',
                    '@app.get("/")', '@app.get("/app")'):
        assert retired in server, f"{retired} is gone -- an old link 404s"
    assert "RedirectResponse" in server, (
        "the retired routes no longer redirect anywhere")
    assert "SCREEN_PATH" not in server, (
        "screen.html is deleted; a path constant pointing at it is a "
        "FileNotFoundError waiting for whoever uses it next")
