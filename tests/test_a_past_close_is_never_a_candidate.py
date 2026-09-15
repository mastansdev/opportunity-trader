"""---- IT BOUGHT SUNTV ON FRIDAY'S MOVE. 15 September 2026. ----

main.py restarted at 11:03:51; the first board had no live quotes and
fell back to the 11 Sep close (labelled at_close). The ranker read it as
today's tape -- SUNTV "up 4.5%, 32x volume", which was 11 Sep -- and it
was bought at 11:04:40 while it was actually down 1.1% on the day.
"""

import pathlib

from dashboard.state import DashboardState


def _state(rows):
    s = object.__new__(DashboardState)
    s._gl_rows_this_build = rows
    return s


def test_a_board_built_from_the_close_is_a_past_close():
    s = _state([{"symbol": "SUNTV", "at_close": True},
                {"symbol": "KEC", "at_close": True}])
    assert s._board_is_a_past_close({}) is True


def test_the_tables_own_flag_is_enough():
    assert _state([])._board_is_a_past_close({"at_close": True}) is True


def test_live_rows_are_not_a_past_close():
    s = _state([{"symbol": "SUNTV", "at_close": False}, {"symbol": "KEC"}])
    assert s._board_is_a_past_close({"at_close": False}) is False


def test_a_past_close_yields_no_candidates_in_either_lane():
    s = _state([{"symbol": "SUNTV", "at_close": True}])
    table = {"at_close": True, "gainers": [{"symbol": "SUNTV"}]}
    assert s.build_early(table, {})["rows"] == []
    src = pathlib.Path("dashboard/state.py").read_text(encoding="utf-8")
    start = src.index("    def build_ranked(")
    body = src[start:src.index("    def ", start + 10)]
    assert "_board_is_a_past_close(gainers_losers)" in body
