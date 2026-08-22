"""
==========================================================
Nine positions, minus Rs 88,096, and nobody was watching.
==========================================================

    "why i still manually tracking all? didn't i ask you to automate
     everything from tracking my open position to search new
     opportunity?"

    "bot trading - ON/OFF = ON > bot trades + track old positions ;
     OFF > Bot Observe the markets & alerts about opportunities +
     track old positions"
                                -- operator, 21 August 2026

The second quote is the specification, and it is the important one:
TRACKING IS UNCONDITIONAL. The switch gates TRADING and nothing else.

The first run against his real account, 21 August:

    Invested Rs 14,12,887      P&L  Rs -88,096
    SIX of NINE below their own reference stop
    PANAMAPET -17.19%   DEEPAKFERT -13.08%   AARTIPHARM -10.70%

WHY IT HAD NEVER BEEN LOOKED AT

Four gates stopped the bot ACTING on these positions, every one of
them put there for a good reason -- the worst being 7 August, when
the bot adopted three stocks he had bought himself and sold all three
out from under him with bot trading OFF.

Not one of those gates was meant to stop it LOOKING. Together they
did, and the result was a dashboard showing a phantom NILKAMAL that
had never been bought while nine real positions went unwatched.

THE LINE THIS FILE DEFENDS

Reporting is not adopting. There is no order path in
core/holdings_watch.py, in either switch position, in either trading
mode -- and the tests below read the source to keep it that way.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core import holdings_watch as hw

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _holding(symbol="CORONA", qty=100, avg=2266.24, ltp=2131.80, mtf=100):
    return {"tradingSymbol": symbol, "totalQty": qty,
            "avgCostPrice": avg, "lastTradedPrice": ltp, "mtf_qty": mtf}


def _quiet(monkeypatch, stop_pct=4.0):
    """No events, no sector move, a known stop width."""
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: stop_pct)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: None)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)


# ---------------------------------------------------------------
# THE NUMBERS HE ACTS ON
# ---------------------------------------------------------------

def test_the_pnl_is_his_real_pnl(monkeypatch):
    """THE CORONA ROW off his own account."""
    _quiet(monkeypatch)
    got = hw.row_for(_holding())
    assert got["symbol"] == "CORONA"
    assert got["pnl_pct"] == -5.93
    assert got["pnl_rs"] == -13444.0


def test_a_position_below_its_own_stop_is_flagged(monkeypatch):
    """PANAMAPET was -17.19%. If this does not fire, the whole module
    is decoration."""
    _quiet(monkeypatch, stop_pct=6.0)
    got = hw.row_for(_holding("PANAMAPET", 100, 592.53, 490.65))
    assert got["below_stop"] is True
    assert "BELOW REFERENCE STOP" in got["flags"]


def test_a_position_above_its_stop_is_not_flagged(monkeypatch):
    """The control. A flag that is always on is not a flag."""
    _quiet(monkeypatch, stop_pct=6.0)
    got = hw.row_for(_holding("KABRAEXTRU", 100, 533.08, 542.00, mtf=0))
    assert got["below_stop"] is False
    assert "IN PROFIT" in got["flags"]
    assert got["mtf"] is False


def test_the_worst_position_is_first(monkeypatch):
    """A list he has to scan is a list he stops reading."""
    _quiet(monkeypatch)
    rows = hw.watch([
        _holding("KABRAEXTRU", 100, 533.08, 542.00),
        _holding("PANAMAPET", 100, 592.53, 490.65),
        _holding("SOLARINDS", 10, 20262.0, 19971.0),
    ])
    assert [r["symbol"] for r in rows][0] == "PANAMAPET"


def test_a_breached_stop_outranks_a_bigger_loss(monkeypatch):
    """Being through the level is the thing needing a decision, even
    if another stock is down more."""
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: None)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_reference_stop_pct",
                        lambda s: 1.0 if s == "TIGHT" else 50.0)
    rows = hw.watch([_holding("LOOSE", 10, 100.0, 70.0),
                     _holding("TIGHT", 10, 100.0, 97.0)])
    assert rows[0]["symbol"] == "TIGHT"


# ---------------------------------------------------------------
# IT REPORTS. IT DOES NOT TRADE.
# ---------------------------------------------------------------

def test_there_is_no_order_path_in_the_module():
    """7 August: the bot adopted three of his own stocks and sold them
    out from under him with trading OFF. This module must not be able
    to repeat that, whatever a future flag says.

    Read off the PARSED TREE, not the text. The first version of this
    grepped the source and failed on its own docstring -- prose
    explaining that there is no adopt() call is not an adopt() call,
    and a test that cannot tell the difference will be deleted by
    whoever hits it next.
    """
    import ast

    src = (ROOT / "core" / "holdings_watch.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    called = set()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                called.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                called.add(fn.attr)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    for banned in ("place_order", "place_forever", "modify_forever",
                   "cancel_forever", "adopt", "sell", "buy",
                   "square_off", "exit_all"):
        assert banned not in called, f"it calls {banned}()"

    for banned in ("core.adopt_positions", "trading.live_execution",
                   "trading.broker_stop", "trading.execution"):
        assert banned not in imported, f"it imports {banned}"


def test_it_never_returns_a_verdict(monkeypatch):
    """Flags are facts and rule outputs. The moment one reads SELL it
    has stopped reporting and started advising, and the doctrine on
    holdings was settled on 29 July against 19 measured filings."""
    _quiet(monkeypatch, stop_pct=1.0)
    rows = hw.watch([_holding("X", 10, 100.0, 80.0)])
    said = " ".join(rows[0]["flags"]).upper()
    for verdict in ("SELL", "BUY", "ADD", "EXIT", "BOOK"):
        assert verdict not in said


def test_the_digest_says_nothing_was_placed(monkeypatch):
    _quiet(monkeypatch)
    said = hw.digest(hw.watch([_holding()]))
    assert "placed nothing" in said
    assert "not orders" in said


# ---------------------------------------------------------------
# NONE IS NOT EMPTY
# ---------------------------------------------------------------

def test_an_unanswered_broker_is_not_an_empty_account():
    """Merging "could not ask" with "he holds nothing" is how a blip
    becomes "your positions vanished"."""
    assert hw.watch(None) == []
    assert hw.digest(hw.watch(None)) == "HOLDINGS -- nothing to report."


def test_one_bad_row_does_not_lose_the_other_eight(monkeypatch):
    _quiet(monkeypatch)
    rows = hw.watch([_holding("A"), None, {}, _holding("B")])
    assert {r["symbol"] for r in rows} == {"A", "B"}


def test_it_survives_junk_numbers(monkeypatch):
    _quiet(monkeypatch)
    for bad in (None, "", "abc", float("nan")):
        got = hw.row_for({"tradingSymbol": "X", "totalQty": bad,
                          "avgCostPrice": bad, "lastTradedPrice": bad})
        assert got["symbol"] == "X"
        assert got["pnl_rs"] == 0.0


def test_a_broken_atr_does_not_stop_the_report(monkeypatch):
    """A missing stop width must degrade to the fallback, not lose the
    position from the list entirely."""
    monkeypatch.setattr("core.atr.scaled_stop_pct",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("no daily bars")))
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: None)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    rows = hw.watch([_holding()])
    assert rows and rows[0]["ref_stop_pct"] == hw.FALLBACK_STOP_PCT


# ---------------------------------------------------------------
# IT READS THE SAME STORES THE ALERT READS
# ---------------------------------------------------------------

def test_the_event_comes_from_the_channel_store():
    """One store, one answer. A second lookup would drift and the
    holding line would contradict the opportunity line."""
    src = (ROOT / "core" / "holdings_watch.py").read_text(encoding="utf-8")
    body = src[src.find("def _event_for"):src.find("def _sector_note")]
    assert "from core.why_moving import _events_for, from_events" in body


def test_the_stop_width_comes_from_the_one_definition():
    """core/atr.py is the single definition all three stop sites read
    -- established 19 August. A fourth would drift within a week."""
    src = (ROOT / "core" / "holdings_watch.py").read_text(encoding="utf-8")
    assert "from core.atr import scaled_stop_pct" in src


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "holdings_watch.py").read_text(encoding="utf-8")
    assert "KALYANKJIL" in src and "track old positions" in src


# ---------------------------------------------------------------
# THE FILING'S DIRECTION IS THE HALF THAT MATTERS
# ---------------------------------------------------------------

def test_a_filing_is_not_printed_as_a_raw_dict(monkeypatch):
    """It was. "FILED: {'text': 'BEAT Revenue...", braces and all,
    went to his phone on the first run of the monitor."""
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: 4.0)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_day_move_pct", lambda s, l: None)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: {
        "text": "Q1 FY27 revenue beat", "direction": "NEGATIVE",
        "source": "PRO channel"})
    said = hw.digest(hw.watch([_holding()]))
    assert "{'text'" not in said
    assert "Q1 FY27 revenue beat" in said


def test_the_direction_reaches_the_flag(monkeypatch):
    """A filing graded NEGATIVE on a position he is already down on is
    the entire reason he asked for this. Dropping it left every filing
    looking identical."""
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: 4.0)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_day_move_pct", lambda s, l: None)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: {
        "text": "order win", "direction": "POSITIVE", "source": "x"})
    got = hw.row_for(_holding())
    assert "FILED TODAY (POSITIVE)" in got["flags"]


def test_a_directionless_filing_still_reports(monkeypatch):
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: 4.0)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_day_move_pct", lambda s, l: None)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: {
        "text": "something filed", "direction": "", "source": ""})
    assert "FILED TODAY" in hw.row_for(_holding())["flags"]


def test_todays_move_is_shown_beside_the_position(monkeypatch):
    """P&L against his average says where it stands. It does not say
    whether something is happening NOW -- the difference between
    quietly down 6% and down 6% because it fell 5% this morning."""
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: 4.0)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: None)
    monkeypatch.setattr(hw, "_day_move_pct", lambda s, l: -5.12)
    said = hw.digest(hw.watch([_holding()]))
    assert "today -5.12%" in said


def test_a_missing_day_move_is_simply_absent(monkeypatch):
    """No daily bar must not print "today None%"."""
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: 4.0)
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: None)
    monkeypatch.setattr(hw, "_day_move_pct", lambda s, l: None)
    said = hw.digest(hw.watch([_holding()]))
    assert "today" not in said and "None" not in said


# ---------------------------------------------------------------
# IT SPEAKS ONCE PER CROSSING, NOT ONCE PER HEARTBEAT
# ---------------------------------------------------------------

def _mon(monkeypatch):
    monkeypatch.setattr(hw, "_sector_note", lambda s, m: None)
    monkeypatch.setattr(hw, "_event_for", lambda s, on_date=None: None)
    monkeypatch.setattr(hw, "_day_move_pct", lambda s, l: None)
    monkeypatch.setattr(hw, "_reference_stop_pct", lambda s: 6.0)
    return hw.HoldingsMonitor()


def test_the_first_sweep_gives_him_the_whole_picture(monkeypatch):
    mon = _mon(monkeypatch)
    _rows, says = mon.sweep([_holding("KABRAEXTRU", 100, 533.08, 542.00)])
    assert len(says) == 1
    assert "HOLDINGS AT DHAN" in says[0]


def test_an_unchanged_book_says_nothing(monkeypatch):
    """A digest every heartbeat is 300 identical messages a day, which
    is the same as no messages."""
    mon = _mon(monkeypatch)
    rows = [_holding("KABRAEXTRU", 100, 533.08, 542.00)]
    mon.sweep(rows)
    assert mon.sweep(rows)[1] == []


def test_a_crossing_speaks_exactly_once(monkeypatch):
    mon = _mon(monkeypatch)
    mon.sweep([_holding("KABRAEXTRU", 100, 533.08, 542.00)])
    _rows, first = mon.sweep([_holding("KABRAEXTRU", 100, 533.08, 400.00)])
    _rows, again = mon.sweep([_holding("KABRAEXTRU", 100, 533.08, 395.00)])
    assert len(first) == 1 and "BELOW REFERENCE STOP" in first[0]
    assert again == [], "it nagged on every later heartbeat"


def test_being_in_profit_is_never_announced(monkeypatch):
    """A state, not an event. Announcing it trains him to swipe the
    notification away, and the one that mattered goes with it."""
    mon = _mon(monkeypatch)
    mon.sweep([_holding("A", 10, 100.0, 99.0)])
    _rows, says = mon.sweep([_holding("A", 10, 100.0, 120.0)])
    assert says == []


def test_an_unanswered_broker_mid_session_says_nothing(monkeypatch):
    """None must not be read as "he sold everything" and produce a
    flurry of messages."""
    mon = _mon(monkeypatch)
    mon.sweep([_holding("A", 10, 100.0, 99.0)])
    assert mon.sweep(None)[1] == []


def test_the_crossing_message_places_nothing(monkeypatch):
    mon = _mon(monkeypatch)
    mon.sweep([_holding("A", 10, 100.0, 99.0)])
    _rows, says = mon.sweep([_holding("A", 10, 100.0, 50.0)])
    assert "placed nothing" in says[0]
    assert "yours to decide" in says[0]
