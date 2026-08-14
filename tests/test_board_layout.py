"""
==========================================================
The board, laid out to order
==========================================================

    "make what to trade now as main theme give it the center box &
     below give as open positions table . remaining every item make
     them as a chip below the fixed box and above what to trade box. at
     right side keep a box of tradebook to show the orders are executed
     or pending with symbol & status . all chips will linked and when i
     click on top gainers move the page to that box"
    "MAKE THE FEED LINE +THE TAB BUTTONS AS A FIXED LIKE THE ABOVE TOP
     RIBBON. WHILE I SCROLL I NEED TO SEE THE TABS"
                                    -- operator, 3 August 2026

WHY THIS IS DONE BY MOVING NODES, NOT BY WRITING MARKUP
------------------------------------------------------
The three blank pages of 29-30 July all came from re-authoring markup.
Every panel below already existed and is RE-PARENTED. If this file ever
starts asserting freshly written HTML for these panels, that lesson has
been forgotten.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import subprocess
import shutil

import pytest

PAGE = "dashboard/static/index.html"


def html():
    return open(PAGE, encoding="utf-8").read()


def script():
    src = html()
    return "\n;\n".join(re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S))


# ---------------------------------------------------------------
# 0. IT PARSES
# ---------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_script_is_valid_javascript(tmp_path):
    """     "before sending me to verify have u cheked?"

    A syntax error anywhere in this file blanks the whole dashboard,
    and the operator finds out at 09:15."""
    path = tmp_path / "page.js"
    path.write_text(script(), encoding="utf-8")
    done = subprocess.run(["node", "--check", str(path)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


# ---------------------------------------------------------------
# 1. THE PINNED BLOCK
# ---------------------------------------------------------------
def test_the_feed_line_and_tabs_are_pinned():
    src = html()
    assert 'pinned.id = "otPinned"' in src
    block = src[src.index("#otPinned {"):]
    block = block[:block.index("}")]
    assert "position: sticky" in block
    assert "--otHeadH" in block


def test_the_tabs_move_into_the_pinned_block():
    """     "WHILE I SCROLL I NEED TO SEE THE TABS" """
    src = html()
    assert "pinned.appendChild(strip);" in src
    assert "pinned.appendChild(tabs);" in src


def test_the_header_height_is_measured_not_assumed():
    """The ribbon wraps at narrow widths. A hardcoded offset leaves a
    gap or hides the read line behind it."""
    src = html()
    assert "getBoundingClientRect().height" in src
    assert "ResizeObserver" in src


def test_a_chip_target_is_not_hidden_under_the_pinned_block():
    """Scrolling an anchor to the top of the window puts it UNDER a
    sticky header. Every jump target carries the offset."""
    src = html()
    block = src[src.index(".ot-jumpto {"):]
    block = block[:block.index("}")]
    assert "scroll-margin-top" in block
    assert "--otHeadH" in block and "--otPinH" in block


# ---------------------------------------------------------------
# 2. THE CENTRE BOX AND HIS POSITIONS
# ---------------------------------------------------------------
def test_what_to_trade_now_is_the_centre_and_positions_sit_under_it():
    src = html()
    assert "leftCol.appendChild(calls);" in src
    assert "leftCol.appendChild(book);" in src
    assert src.index("leftCol.appendChild(calls);") < \
        src.index("leftCol.appendChild(book);")


def test_the_calls_box_scrolls_inside_itself():
    """     On a six-call day his open positions must not be pushed
            below the fold. Not seeing a position is what cost him on
            the first live day."""
    src = html()
    block = src[src.index("#otCallsBody {"):]
    block = block[:block.index("}")]
    assert "max-height" in block and "overflow-y: auto" in block


def test_the_tradebook_is_the_right_hand_column():
    src = html()
    assert 'rightCol.id = "otBoardSide"' in src
    assert "rightCol.appendChild(orders);" in src


def test_orders_today_was_renamed_not_duplicated():
    """     "Both are same tradebook and ORDERS TODAY. keep one only" """
    src = html()
    assert 'nodeValue = "TRADEBOOK ";' in src
    # The panel is moved, not recreated -- one node, one renderer.
    assert src.count('id="otOrders"') == 1


# ---------------------------------------------------------------
# 3. THE CHIPS
# ---------------------------------------------------------------
def test_the_chip_menu_is_pinned_and_does_not_scroll_away():
    """     "these chips must be fixed . if i click on FILED TODAY page
             will move to end. i need to scroll upside but better to
             click on the fixed chip to move"

    A jump menu that scrolls away with the page is a menu you can use
    exactly once. The chips are the last row of the pinned block, so
    they are still below the tiles and above the centre box -- they
    simply travel."""
    src = html()
    assert 'chips.id = "otChips"' in src
    assert "pinned.appendChild(chips);" in src
    assert 'pinned.insertAdjacentElement("afterend", chips);' not in src
    # Last row: after the tabs.
    assert src.index("pinned.appendChild(tabs);") < \
        src.index("pinned.appendChild(chips);")


def test_a_tab_takes_him_back_to_the_top():
    """     "if i click on LIVE tab = move instantly to top of the page
             right?"

    Right. Changing tab three screens down used to leave him three
    screens down, looking at whatever sat at that scroll position in
    the new tab."""
    src = html()
    block = src[src.index("A TAB TAKES HIM BACK TO THE TOP"):]
    block = block[:block.index("} catch (err) {")]
    assert 'button[data-tab]' in block
    assert 'window.scrollTo({top: 0, behavior: "smooth"});' in block


def test_the_jump_offset_grows_with_the_pinned_block():
    """The pinned block gets taller when the tiles or the chips wrap to
    a second row. A fixed offset buries the top of the target."""
    src = html()
    assert "--otPinH" in src
    assert 'root.setProperty("--otPinH"' in src
    assert "watch.observe(pinned);" in src


def test_every_chip_jumps_somewhere():
    src = html()
    assert 'chip.dataset.jump = node.id;' in src
    assert 'node.scrollIntoView({behavior: "smooth", block: "start"});' in src


def test_a_chip_opens_the_drawer_it_lands_in():
    """Most of these panels are folded. A chip that scrolls to a shut
    drawer looks broken."""
    src = html()
    block = src[src.index('chips.addEventListener("click"'):]
    block = block[:block.index("});")]
    assert 'box.tagName === "DETAILS"' in block


def test_the_chips_name_the_lists_he_asked_for():
    src = html()
    block = src[src.index("var TARGETS = ["):]
    block = block[:block.index("];")]
    for label in ("TOP GAINERS", "TOP LOSERS", "WHY THINGS ARE MOVING",
                  "TURNED AROUND", "FRESH BREAKOUTS", "NEWS", "SECTORS",
                  "FILED TODAY"):
        assert label in block, label
    # ORDERS TODAY is gone -- it became the tradebook on the right.
    assert "ORDERS TODAY" not in block


# ---------------------------------------------------------------
# 4. THE ONE-LINE READ, AND FII/DII COLOURED BY DIRECTION
# ---------------------------------------------------------------
def test_market_intelligence_is_one_thin_line():
    """     "no need to mention Market Intelligence just give the data
             trend; breadth; bias in one line smaller is sufficient" """
    src = html()
    assert "function renderReadLine" in src
    assert "renderReadLine(snap);" in src
    block = src[src.index("function renderReadLine"):]
    block = block[:block.index("function renderTopStrip")]
    for word in ("Trend ", "Breadth ", "Bias "):
        assert word in block, word


def test_each_side_of_the_flow_is_coloured_by_its_own_direction():
    """     "keep green if buy & red if sold ... If FII bought 1000
             crores & DII sold 500 crores then FII/DII = 1000 (in
             green)/500(in red)"

    One colour for the pair would hide the commonest shape there is:
    foreign money selling into domestic buying."""
    src = html()
    block = src[src.index("function renderReadLine"):]
    block = block[:block.index("function renderTopStrip")]
    assert 'v >= 0 ? "ot-up" : "ot-dn"' in block
    assert "side(flows.fii_cr)" in block and "side(flows.dii_cr)" in block


def test_the_flow_figure_always_carries_its_date():
    """It is published after the close, so during a session it is
    always the PREVIOUS one -- Friday's on a Monday."""
    src = html()
    block = src[src.index("function renderReadLine"):]
    block = block[:block.index("function renderTopStrip")]
    assert "flows.as_of" in block
    assert "flows.source" in block


def test_it_reads_the_key_the_payload_actually_uses():
    """dashboard/state.py nests these under market_intelligence. Reading
    snap.market would draw an empty line forever and look like missing
    data rather than a wrong key."""
    src = html()
    assert "snap.market_intelligence" in src
    state = open("dashboard/state.py", encoding="utf-8").read()
    assert '"institutional": self._build_institutional(),' in state


# ---------------------------------------------------------------
# 5. NOTHING WAS RE-AUTHORED
# ---------------------------------------------------------------
def test_the_panels_are_moved_and_not_rebuilt():
    """     The three blank pages of 29-30 July all came from rewriting
            markup. Each of these ids must appear exactly once."""
    src = html()
    for node in ("otCalls", "otBook", "otOrders", "otTopStrip", "otCause"):
        assert src.count('id="%s"' % node) == 1, node


def test_the_whole_layout_pass_is_inside_a_safety_net():
    """     "A broken layout tweak must never cost him the screen." """
    src = html()
    start = src.index("THE BOARD, LAID OUT TO ORDER")
    after = src[start:]
    assert "} catch (err) {" in after[:after.index("function renderReadLine")
                                      if "function renderReadLine" in after
                                      else len(after)]
