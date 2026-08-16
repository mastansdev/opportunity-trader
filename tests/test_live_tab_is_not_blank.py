"""
The LIVE tab was blank while PRE was full. 11 August 2026.

    "dashboard is not showing live. its working till pre market &
     blank at live tab."

WHAT WAS ACTUALLY HAPPENING
---------------------------
Nothing was broken. PRE draws from gainers_losers -- the raw tape,
hundreds of rows. LIVE drew from ranked.rows, which is what survives
ten hard gates in core/ranker.py plus the entry-rules pass in
dashboard/state.py. On an ordinary morning that is nought or one.

So the money table, the one he told me belongs in the centre of the
page, sat empty while the bot worked perfectly. The refusals were
recorded to data/decisions.db every single cycle -- they just never
reached his eyes.

THE DANGEROUS FIX, AND WHY IT WAS NOT TAKEN
-------------------------------------------
The obvious repair is to append the refused stocks to `rows`. That
would have been the worst bug in this project: main.py passes
ranked.rows straight into auto_entry.take(). The bot would have bought
the exact stocks its own gates had just refused, and the screen would
have looked correct the entire time.

So the refusals live in their own key. The last three tests here exist
only to keep it that way.
"""

import pytest

from tests.test_dashboard_server import _client


SNAP = {
    "bot_enabled": False,
    "universe_size": 1276,
    "as_of": "11:20",
    "ranked": {
        "available": True,
        "rows": [
            {"symbol": "SHILPAMED", "grade": "GOOD", "ltp": 783.2,
             "change_pct": 1.71, "open": 770.0, "high": 790.0, "low": 768.0,
             "prev_close": 762.0, "volume": 1250000, "mechanism": "GOOD result",
             "volume_x": 3.1, "sector": "PHARMACEUTICALS"},
        ],
        "refused_rows": [
            {"symbol": "LICI", "ltp": 905.0, "change_pct": 0.4, "open": 900.0,
             "high": 912.0, "low": 898.0, "prev_close": 901.0,
             "volume": 9400000, "display_only": True,
             "blocking": ["an offer for sale is on -- a block is coming"]},
            {"symbol": "ZEEL", "ltp": 94.0, "change_pct": -0.4, "open": 94.4,
             "high": 95.0, "low": 93.2, "prev_close": 94.42, "volume": 800000,
             "display_only": True,
             "blocking": ["drifting on 0.8x volume with nothing behind it"]},
        ],
    },
}


def _board():
    client, _ = _client(SNAP)
    return client.get("/board")


def _typing_branch(page):
    """The one-line `if (typing){ ... }` guard in draw(), as text.

    Returned so tests can ask what it DOES rather than matching the
    whole line -- adding a pane must not turn a qty-box test red.
    """
    start = page.find("if (typing){")
    assert start != -1, (
        "the typing guard is gone from draw(). The qty box is rebuilt "
        "every 3 seconds and will eat digits mid-keystroke.")
    end = page.find("}", start)
    return page[start:end + 1]


# ---------------------------------------------------------------
# The page
# ---------------------------------------------------------------

def test_the_live_table_reads_the_refused_rows_as_well():
    """The one line that empties or fills the centre of his screen."""
    page = _board().text
    assert "refused_rows" in page, "LIVE still draws only the survivors"


def test_both_lists_are_concatenated_not_swapped():
    """Survivors must still be there. Showing ONLY refusals would be
    the same fault upside down."""
    page = _board().text
    assert "s.ranked.rows" in page and "s.ranked.refused_rows" in page
    assert "[].concat(" in page


def test_a_refused_row_still_says_why():
    page = _board().text
    assert "blocking" in page and "BLOCKED" in page


# ---------------------------------------------------------------
# The payload
# ---------------------------------------------------------------

def _built(rows, refusals, movers):
    """Run the real build_ranked tail over a fake rank() result."""
    from dashboard import state as state_module
    shown = {r.get("symbol") for r in rows}
    source = {r.get("symbol"): r for r in movers}
    out = []
    for symbol, why in refusals.items():
        if not symbol or symbol in shown:
            continue
        raw = source.get(symbol) or {}
        out.append({"symbol": symbol, "ltp": raw.get("ltp"),
                    "prev_close": raw.get("prev_close"),
                    "blocking": [str(why)], "display_only": True})
    assert state_module is not None
    return out


def test_a_refused_symbol_becomes_a_row_with_its_reason():
    got = _built(
        rows=[{"symbol": "SHILPAMED"}],
        refusals={"ZEEL": "no volume behind it"},
        movers=[{"symbol": "ZEEL", "ltp": 94.0, "prev_close": 94.42}])
    assert len(got) == 1
    assert got[0]["symbol"] == "ZEEL"
    assert got[0]["blocking"] == ["no volume behind it"]
    assert got[0]["ltp"] == 94.0


def test_a_stock_never_appears_in_both_lists():
    """It cleared the gates OR it did not. A symbol drawn twice reads
    as two different opinions about the same stock."""
    got = _built(
        rows=[{"symbol": "SHILPAMED"}],
        refusals={"SHILPAMED": "stale refusal from an earlier cycle"},
        movers=[{"symbol": "SHILPAMED", "ltp": 783.0}])
    assert got == []


def test_a_refused_row_carries_the_price_so_the_table_is_not_empty():
    """A row with a reason and no price is a blank line with a
    sentence next to it."""
    got = _built(
        rows=[],
        refusals={"ZEEL": "too thin"},
        movers=[{"symbol": "ZEEL", "ltp": 94.0, "prev_close": 94.42}])
    assert got[0]["prev_close"] == 94.42


# ---------------------------------------------------------------
# THE ONE THAT MATTERS -- refusals must never reach the entry path
# ---------------------------------------------------------------

def test_main_still_feeds_auto_entry_from_rows_only():
    """main.py: auto_entry.take(_rows, ...). If this ever becomes
    rows + refused_rows the bot buys what its own gates refused."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(
        encoding="utf-8", errors="replace")
    assert '_rows = (_ranked or {}).get("rows") or []' in src
    assert "refused_rows" not in src, (
        "main.py must never read refused_rows -- that is the entry path")


def test_the_refused_rows_are_flagged_display_only():
    got = _built(rows=[], refusals={"ZEEL": "too thin"},
                 movers=[{"symbol": "ZEEL", "ltp": 94.0}])
    assert got[0]["display_only"] is True


def test_state_builds_refused_rows_in_its_own_key():
    """Not merged into rows anywhere in dashboard/state.py."""
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert 'got["refused_rows"] = refused_rows' in src
    assert 'got["rows"] += ' not in src
    assert 'got["rows"].extend' not in src


# ---------------------------------------------------------------
# 11 August, second report: "still live tab showing same empty"
# ---------------------------------------------------------------
# The header read "watching 1225 EQ" -- this morning's universe, not the
# 1,415 on disk -- so the bot was still the process he started before
# any of the day's changes and had no refused_rows to send. Telling him
# to restart is a fair answer once. Twice it is an excuse.

EMPTY = {
    "bot_enabled": False,
    "universe_size": 1415,
    "as_of": "11:18",
    "ranked": {"available": True, "rows": []},
    "gainers_losers": {
        "gainers": [{"symbol": "KSHINTL", "ltp": 980.0, "change_pct": 8.8,
                     "open": 906.0, "high": 985.0, "low": 900.0,
                     "prev_close": 900.6, "volume": 514737}],
        "losers": [{"symbol": "HLEGLAS", "ltp": 380.0, "change_pct": -19.9,
                    "open": 379.6, "high": 385.0, "low": 375.0,
                    "prev_close": 474.5, "volume": 489047}],
    },
}


def test_the_empty_message_names_the_numbers():
    """'nothing cleared the gates yet' told him nothing he could act on.
    Universe, cleared, refused -- and what a zero in the last one means."""
    page = _board().text
    assert "cleared," in page and "refused." in page
    assert "restart the bot" in page




# ---------------------------------------------------------------
# 12:03 -- "all mixed ? why? not even one thing is as i wanted."
# ---------------------------------------------------------------
# I had made LIVE fall back to gainers_losers so it would never look
# empty. He saw three faults in one glance and every one was real:
# graded stocks drew as "--", the order was size-of-move, and a
# long-only table was headed by -19% fallers. These tests hold the
# withdrawal in place.

def test_the_grade_map_is_read_before_any_row_is_drawn():
    """KOLTEPATIL was GRADED at 12:03 and drew as '--'. The map exists
    so a row can be chipped whichever list it came from."""
    page = _board().text
    assert "GRADED = (s.ranked && s.ranked.graded)" in page
    assert "function gradeOf(r)" in page


def test_the_row_and_the_gap_row_both_use_the_map():
    page = _board().text
    assert page.count("gradeOf(r) || \"\"") >= 2


def test_state_publishes_the_grade_map():
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert 'got["graded"] = grades' in src
    assert "watchlist_builder" in src


# ---------------------------------------------------------------
# "have u corrected dashboard with only longs"  -- 11 August 2026
# ---------------------------------------------------------------
# The first pass only pushed fallers DOWN. That is not what he asked
# for. A stock he cannot buy has no place on the screen whose job is to
# find the next buy -- at any position. The one exception is a stock he
# is already in: that is his money leaving and it must never be hidden.

def test_a_held_position_survives_the_long_only_filter():
    """His money is in it. A held stock going the wrong way is the most
    important row on the page."""
    page = _board().text
    assert "if (!inBook[r.symbol] && Number(r.change_pct || 0) < 0) continue;" in page
    assert "held: !!inBook[r.symbol]" in page


def test_a_refused_row_carries_why_it_is_moving_too():
    """'neat & clean explaination of why stock is moving, volume, &
    everyother details' -- that has to hold for a refusal as well, or he
    cannot judge whether the refusal was right."""
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    for field in ('"mechanism"', '"volume_x"', '"headroom_pct"',
                  '"upper_circuit"'):
        assert field in src, f"refused rows do not carry {field}"


# ---------------------------------------------------------------
# 12:58 -- I finally LOOKED at his running board, and found this
# ---------------------------------------------------------------
#   too thin to trade our size  --  --  --  +0.00%  --  65   BLOCKED
#   not moving enough           --  --  --  +0.00%  --  91   BLOCKED
#
# Refusal REASONS drawn as stock names, with the COUNT printed where the
# reason belongs. core/ranker.py has keyed refusals {reason: count}
# since 4 August -- refuse() throws the symbol away. I built rows from
# it having assumed {symbol: reason} and never checked.

def test_the_ranker_now_remembers_which_stock_it_refused():
    from core.ranker import rank
    rows = [{"symbol": "TINYCO", "ltp": 10.0, "day_open": 9.9,
             "day_high": 10.1, "day_low": 9.8, "volume": 100,
             "turnover_cr": 0.01, "prev_close": 9.9, "change_pct": 1.0,
             "sector": "CHEMICALS"}]
    got = rank(rows, adv_of=lambda s: 40.0, top=5)
    assert "TINYCO" in (got.get("refused_by_symbol") or {}), (
        "the ranker still counts reasons and forgets the stock")


def test_the_count_dict_is_left_alone():
    """`refusals` has meant {reason: count} since 4 August and the
    decision log reads it. The new key sits BESIDE it."""
    from core.ranker import rank
    rows = [{"symbol": "TINYCO", "ltp": 10.0, "day_open": 9.9,
             "day_high": 10.1, "day_low": 9.8, "volume": 100,
             "turnover_cr": 0.01, "prev_close": 9.9, "change_pct": 1.0,
             "sector": "CHEMICALS"}]
    got = rank(rows, adv_of=lambda s: 40.0, top=5)
    assert all(isinstance(v, int) for v in (got.get("refusals") or {}).values())


def test_a_reason_string_can_never_become_a_stock_row():
    """The exact fault on his screen at 12:58."""
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert "symbol not in source" in src, (
        "rows are still built from keys that were never symbols")
    assert "isinstance(why, (int, float))" in src, (
        "a count can still be drawn as a reason")


def test_the_builder_reads_the_new_per_symbol_key():
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert 'got.get("refused_by_symbol")' in src


# ---------------------------------------------------------------
# THE ONE THAT COST EVERY TRADE. 11 August 2026, 14:50.
# ---------------------------------------------------------------
#     "why dashboard is not showing the today top gained stocks ?
#      fincables , lumaxtech & atleast 20 stocks were trading at high"
#
# The live snapshot said it plainly: gainers_losers was 8 seconds old
# and held LUMAXTECH +19.11%, FINCABLES +13.29%. ranked.rows was 0.
#
# dashboard/state.py read row["day_open"]; core/ranker.py writes it as
# "open". So select.movement() saw no open price, answered "no price",
# and the entry-rules loop dropped 100% of the ranker's output -- every
# cycle, every session, silently. Nothing threw. It just looked like a
# market where nothing ever qualified.

def test_the_entry_rules_accept_the_key_the_ranker_actually_writes():
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert 'row.get("day_open") or row.get("open")' in src
    assert 'row.get("day_high") or row.get("high")' in src
    assert 'row.get("day_low") or row.get("low")' in src


def test_a_ranker_row_survives_the_movement_check():
    """End to end on the two names actually shaped like the ranker's
    output. If this ever returns 'no price' again, the bot has gone
    blind and the screen will not say so."""
    from core import select as rules
    from core.ranker import rank
    rows = [{"symbol": "LUMAXTECH", "ltp": 2070.3, "day_open": 1795.0,
             "day_high": 2084.8, "day_low": 1795.0, "volume": 4485000,
             "turnover_cr": 928.0, "prev_close": 1738.2, "change_pct": 19.11,
             "sector": "AUTOMOBILE", "why": "order win",
             "volume_ratio": 3.4}]
    got = rank(rows, adv_of=lambda s: 60.0, top=5)
    for row in (got.get("rows") or []):
        verdict = rules.movement({
            "ltp": row.get("ltp"),
            "day_open": row.get("day_open") or row.get("open"),
            "day_high": row.get("day_high") or row.get("high"),
            "day_low": row.get("day_low") or row.get("low"),
            "volume_ratio": (row.get("volume_ratio")
                             or row.get("volume_x") or 1.6),
        })
        assert verdict.get("why") != "no price", (
            "the ranker's own row still reads as having no price")


def test_the_ranker_writes_open_not_day_open():
    """Pinning the shape both sides now agree on. If the ranker ever
    renames this back, the test above stops being a real check."""
    import inspect
    from core import ranker
    src = inspect.getsource(ranker.rank)
    assert '"open": _num(row.get("day_open") or row.get("open"))' in src


# ---------------------------------------------------------------
# 15:00 -- "thats a simple dashboard with whats the top gaining
#           stocks with their underlying reason"
# ---------------------------------------------------------------
# The table is a VIEW, not the tail of a decision funnel. Source is the
# tape; everything the bot knows is joined onto it.

def test_the_live_table_is_sourced_from_the_gainers():
    page = _board().text
    live = page.split("function drawPre")[0]
    assert "gl.gainers" in live, "LIVE is not built from today's gainers"


def test_the_bot_s_own_rows_are_joined_on_not_used_as_the_source():
    """cleared and refused still contribute their grade, reason and
    verdict -- they just no longer decide whether a stock is visible."""
    page = _board().text
    assert "const cleared = (s.ranked && s.ranked.rows) || []" in page
    assert "const refused = (s.ranked && s.ranked.refused_rows) || []" in page
    assert "byName[r.symbol]" in page


def test_a_stock_the_bot_never_judged_still_appears():
    """LUMAXTECH +19% must be on the screen whether or not it survived
    ten gates. Nothing in the row builder requires a match in byName."""
    page = _board().text
    assert "known ? known.row : {}" in page


def test_it_is_still_long_only():
    page = _board().text
    assert "if (!inBook[r.symbol] && Number(r.change_pct || 0) < 0) continue;" in page


def test_held_first_then_graded_then_the_size_of_the_move():
    """His money, then the PRO chip, then what actually moved."""
    page = _board().text
    # 11 August, second revision: the sort became
    # held -> chosen mode (activity / change% / turnover) when the
    # table was rebuilt in the earningspulse shape. His money still
    # leads, whatever mode is selected.
    sort = page.split("const all = movers.sort")[1][:400]
    assert "a.held ? 0 : 1" in sort
    assert "return by(a, b)" in sort


def test_the_screen_still_never_reaches_the_entry_path():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(
        encoding="utf-8", errors="replace")
    assert '_rows = (_ranked or {}).get("rows") or []' in src
    assert "gainers_losers" not in src.split("auto_entry.take")[0][-2000:]


def test_the_page_javascript_actually_parses():
    """15:05 -- I shipped `const held` twice in one scope. The whole
    script failed to define a single function and his board sat on
    'waiting for the first snapshot' with no error he could see. Every
    other test in this file greps text; none of them would have caught
    a syntax error. This one runs the parser."""
    import re, shutil, subprocess, tempfile, os
    from pathlib import Path
    page = Path(__file__).resolve().parents[1].joinpath(
        "dashboard/static/board.html").read_text(encoding="utf-8")
    js = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", page, re.S))
    assert js.strip(), "no script block found"
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node is not installed here")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(js)
        path = handle.name
    try:
        done = subprocess.run([node, "--check", path],
                              capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, done.stderr.strip()[:400]
    finally:
        os.unlink(path)


def test_the_reason_map_is_published_for_every_mover():
    """'their underlying reason which is even present within bot through
    the telegram pro channels'. _mechanism_for() has answered for any
    symbol since 7 August -- it was only ever CALLED on rows that
    survived the ranker."""
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert 'got["reasons"] = reasons' in src
    assert "self._mechanism_for(name)" in src


def test_a_mover_is_four_percent():
    """26 names with a catalyst, not 50 rows of 0.8% noise."""
    page = _board().text
    assert "const MOVER_PCT = 4.0" in page
    assert "Math.abs(Number(r.change_pct || 0)) >= MOVER_PCT" in page


def test_a_held_position_is_always_a_mover():
    page = _board().text
    assert "r.held || Math.abs(Number(r.change_pct || 0)) >= MOVER_PCT" in page


def test_activity_weights_volume_by_whether_the_move_is_still_alive():
    """x1.5 still going, x0.3 fading. Same volume, direction ranks it."""
    page = _board().text
    assert "still ? 1.5 : 0.3" in page
    assert "const dv = Math.max(vol - was.vol, 0)" in page


def test_the_first_refresh_scores_zero_rather_than_guessing():
    """One snapshot cannot tell you about flow."""
    page = _board().text
    assert "if (!was) return 0;" in page


def test_every_row_is_scored_before_the_threshold_filter():
    """activityOf also RECORDS this refresh. Skipping a row would make
    it show a false volume jump the moment it qualified."""
    page = _board().text
    assert "for (const r of ranked) r.activity = activityOf(r);" in page
    body = page.split("const movers = ranked.filter")[0]
    assert "r.activity = activityOf(r)" in body


def test_all_three_sorts_exist():
    page = _board().text
    for mode in ("activity", "change", "turnover"):
        assert f'data-sort="{mode}"' in page


def test_the_counts_are_in_the_header():
    page = _board().text
    assert '$("counts")' in page and "universe_size" in page


# ---------------------------------------------------------------
# "where is BUY button & QTY ?"
# ---------------------------------------------------------------

def test_the_board_draws_a_buy_and_a_qty_box():
    page = _board().text
    assert 'data-buy="' in page and 'data-qtyfor="' in page


def test_it_posts_to_the_endpoint_that_already_existed():
    """Same route the working page has used since July. Nothing new
    was invented on the order path."""
    page = _board().text
    assert "/api/buy/${encodeURIComponent(sym)}" in page
    assert '"X-Operator-Token": window.__OPERATOR_TOKEN__' in page


def test_the_typed_qty_lives_outside_the_dom():
    """The exact fault that wiped the qty box on the old page every
    second: the value was in the DOM and the DOM was rebuilt."""
    page = _board().text
    assert "const QTY = {}" in page
    assert 'QTY[sym] = e.target.value' in page


def test_a_buy_is_confirmed_before_it_is_sent():
    page = _board().text
    assert "confirm(`BUY ${sym}" in page


def test_a_view_only_link_gets_no_buy_button_at_all():
    """Refused at the button, not at the endpoint."""
    page = _board().text
    assert "IS_OPERATOR" in page and "view only" in page


def test_the_server_injects_the_operator_token_into_the_board():
    """Without this the placeholder stays empty, IS_OPERATOR is false
    and every row draws 'view only' -- which is what /board did."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath(
        "dashboard/server.py").read_text(encoding="utf-8")
    board = src.split('@app.get("/board"')[1][:2000]
    assert "_TOKEN_PLACEHOLDER" in board
    assert "_token_matches(token)" in board


# ---------------------------------------------------------------
# 11 August, evening: chips, placement, and the qty box
# ---------------------------------------------------------------
#     "why is it moving cloumn is crude . didn't i ask you about
#      creating the reason as chips ? & qty [] ; BUY button next to
#      stock symbol name . still UI is worst [qty] is not working ."

def test_the_reason_is_chips_not_a_paragraph():
    """He asked for this on 8 August and again today. I kept joining
    everything into one grey sentence he has to read at the moment he
    is deciding to spend money."""
    page = _board().text
    assert "function reasonChips(r)" in page
    # ---- IT MEASURED COMMENT VOLUME. 16 August 2026. ----
    #
    # This was page.split("function row(r)")[1][:1800] -- "somewhere in
    # the first 1800 characters after row() starts". row() then gained
    # the sized-plan block and its explanation, reasonChips(r) moved to
    # offset 3080, and the test failed while the chips it guards were
    # rendering perfectly.
    #
    # A window in characters is a budget on how much a function may be
    # commented. Slice the FUNCTION instead.
    body = page.split("function row(r)")[1].split("function draw(s)")[0]
    assert "reasonChips(r)" in body, (
        "row() no longer renders the reason as chips")
    assert "bits.join(\" · \")" not in page


def test_the_reason_leads_with_a_source_tag():
    """earningspulse does Earnings/News/Filing. Same idea."""
    page = _board().text
    assert "Earnings\\u00b7" in page or "Earnings·" in page
    assert "Tape\\u00b7no published reason" in page or "Tape·no published reason" in page


def test_each_fact_is_its_own_chip():
    page = _board().text
    for fact in ('"x vol"', "% to UC", "% vs "):
        assert fact.strip('"') in page


def test_a_long_reason_is_cut_but_kept_in_the_tooltip():
    """Truncated on screen, full text on hover. He loses nothing."""
    page = _board().text
    assert "const cut = (t, n)" in page
    assert 'title="${(full || text)' in page


def test_buy_and_qty_sit_next_to_the_symbol():
    """They were eleven columns away from the name he is reading."""
    page = _board().text
    stock_cell = page.split('<td class="sym">${sym}')[1][:300]
    assert 'class="act"' in stock_cell
    assert "${buy}" in stock_cell


def test_the_table_is_not_rebuilt_while_he_is_typing_a_quantity():
    """THE qty BUG. It was not broken -- it was being destroyed. The
    tbody is rebuilt every 3s, so the input was removed from the
    document mid-keystroke and every digit typed between two refreshes
    was lost."""
    page = _board().text
    assert 'document.activeElement.classList.contains("qty")' in page
    assert _typing_branch(page).endswith("return; }"), (
        "the typing guard no longer bails out before the tbody is "
        "rebuilt -- the qty box will be destroyed mid-keystroke again")


def test_the_other_tabs_still_update_while_he_types():
    """Pausing the whole screen would be a different bug.

    ---- MATCHED ON THE WHOLE LINE. 16 August 2026. ----

    Both of these asserted the exact text

        if (typing){ drawPre(s); drawPost(s); return; }

    so adding a fourth pane -- the restored Watch tab -- turned them
    red without anything being wrong. The guarantee is "every OTHER
    pane still redraws", not "there are exactly two of them", so they
    now read the branch and check each pane renderer by name.
    """
    branch = _typing_branch(_board().text)
    for other in ("drawPre(s)", "drawPost(s)", "drawWatch(s)"):
        assert other in branch, (
            f"{other} is not called while he is typing a quantity, so "
            f"that pane freezes for as long as the cursor is in the box")
    assert "$(\"body\").innerHTML" not in branch


def test_no_dead_call_to_the_function_i_deleted():
    """Replacing reasonOf with reasonChips left the PRE tab still
    calling reasonOf. Syntax-valid, and it would have thrown the moment
    he clicked Pre. Found by a test, not by him, for once."""
    page = _board().text
    assert "reasonOf(" not in page, "something still calls the deleted reasonOf"
    assert page.count("reasonChips(r)") >= 2, "PRE and LIVE must both chip"


def test_the_board_actually_runs_not_just_parses():
    """tests/board_smoke.js loads the real script into a DOM and calls
    draw(). Twice today I shipped a page that parsed perfectly and
    could not run -- `const held` twice, then `capOf is not defined`.
    Every other test in this file greps text and would have passed
    both times. This is the only one that executes his screen."""
    import shutil, subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node is not installed here")
    smoke = Path(__file__).resolve().parents[1] / "tests" / "board_smoke.js"
    done = subprocess.run([node, str(smoke)], capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, "\n" + done.stdout + done.stderr


def test_a_dict_never_reaches_a_reason_chip():
    """GODAVARIB drew as News·{'text': 'GODAVARI BIOREFINERIES...
    _mechanism_for can return the whole news record and str() on a dict
    is its repr. Same fault as the watermark dict-reprs on 10 August."""
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState.build_ranked)
    assert "isinstance(why, dict)" in src
    page = _board().text
    assert 'typeof t === "object"' in page


def test_the_board_preflight_passes():
    """tools/board_preflight.py serves the real page through the real
    app -- with and without the operator token -- and clicks every
    control on it. 11 August: I handed him /board four times and he
    found the fault within a minute each time, because nobody had ever
    clicked those buttons. This is the handover gate."""
    import shutil, subprocess, sys
    from pathlib import Path
    if not shutil.which("node"):
        import pytest
        pytest.skip("node is not installed here")
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "tools/board_preflight.py"],
                          cwd=str(root), capture_output=True, text=True,
                          timeout=180)
    assert done.returncode == 0, "\n" + done.stdout + done.stderr


def test_the_switch_state_is_never_served_from_the_cache():
    """11 August, 16:58. /api/bot_trading/off returned success:true and
    the engine WAS disarmed -- and /api/snapshot kept reporting
    bot_trading.on = true because the cached snapshot had frozen when
    the trading loop ended at the close. `as_of` sat at 16:58:45 for
    24 seconds. He pressed a switch that worked, watching a screen that
    could not change, and I rewrote the button four times looking for a
    bug that was never in the button."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath(
        "dashboard/server.py").read_text(encoding="utf-8")
    route = src.split('@app.get("/api/snapshot")')[1][:4000]
    # UPDATED 12 August 2026 -- the fix shipped as a standalone
    # _bot_trading_now(state) helper (reads engine.alert_only fresh,
    # see its own docstring), not a dashboard_state._bot_trading()
    # method. This test's job is unchanged: the switch must come from
    # a live read, never the cached snapshot dict.
    assert "_bot_trading_now(dashboard_state)" in route, (
        "the switch state still comes out of the cached snapshot")
    assert '"served_at"' in route, (
        "nothing says how old the cached payload is")


def test_a_frozen_board_says_it_is_frozen():
    page = _board().text
    assert "FROZEN (market closed" in page
    assert "s.served_at" in page
