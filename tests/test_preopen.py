"""
Tests for core/preopen.py -- the 09:00-09:15 blind spot.

    "the bot is completely blind 09:00-09:15"   -- 29 July 2026

Item 16 on the operator's own preparation chart, collected by nobody.

The rules this is held to, same as every other collector in this
codebase: NSE's own percentage is read rather than recomputed, and a
stock NSE did not return is MISSING rather than zero. A pre-open panel
showing a stock at 0.00 is worse than one omitting it, because zero
looks like data.
"""

import json

import pytest

from core.preopen import PreOpen, parse_preopen_payload

# The real shape of NSE's /api/market-data-pre-open response, trimmed
# to the fields this module reads.
PAYLOAD = json.dumps({"data": [
    {"metadata": {"symbol": "INFY", "previousClose": 1109.95,
                  "lastPrice": 1151.38, "pChange": 3.73},
     "detail": {"preOpenMarket": {
         "IEP": 1151.38, "finalQuantity": 412000,
         "totalTurnover": 474000000.0,
         "totalBuyQuantity": 900000, "totalSellQuantity": 100000,
         "lastUpdateTime": "29-Jul-2026 09:12:00"}}},
    {"metadata": {"symbol": "TATAMOTORS", "previousClose": 700.0,
                  "lastPrice": 679.0, "pChange": -3.0},
     "detail": {"preOpenMarket": {
         "IEP": 679.0, "finalQuantity": 250000,
         "totalBuyQuantity": 50000, "totalSellQuantity": 450000}}},
    {"metadata": {"symbol": "FLAT", "previousClose": 100.0,
                  "lastPrice": 100.0, "pChange": 0.0},
     "detail": {"preOpenMarket": {"IEP": 100.0, "finalQuantity": 1000}}},
]})


def _pre(tmp_path, fetcher):
    return PreOpen(fetcher=fetcher, store_path=str(tmp_path / "p.json"))


# ---------------------------------------------------------------
# Reading the book
# ---------------------------------------------------------------

def test_it_reads_the_opening_price():
    """The IEP is where the stock WILL open. Known at 09:12, before
    the bell -- a published fact, not a forecast."""
    assert parse_preopen_payload(PAYLOAD)["INFY"]["iep"] == 1151.38


def test_the_gap_percent_is_NSEs_not_ours():
    """Operator's standing rule: percentages follow NSE."""
    assert parse_preopen_payload(PAYLOAD)["INFY"]["gap_pct"] == 3.73


def test_the_unmatched_order_imbalance_is_computed():
    """900k buy against 100k sell = +0.80: four-fifths of the leftover
    book is buying. Nowhere else on the operator's screen is this
    visible, and two stocks showing the same +4% can be completely
    different underneath."""
    rows = parse_preopen_payload(PAYLOAD)
    assert rows["INFY"]["imbalance"] == pytest.approx(0.8)
    assert rows["TATAMOTORS"]["imbalance"] == pytest.approx(-0.8)


def test_a_stock_with_no_imbalance_data_reports_None_not_zero():
    """Zero would read as 'perfectly balanced', which is a different
    claim from 'not published'."""
    assert parse_preopen_payload(PAYLOAD)["FLAT"]["imbalance"] is None


def test_a_stock_that_did_not_trade_in_the_preopen_is_left_out():
    """No equilibrium price means it did not participate. Recorded as
    absent, never as 0.00."""
    payload = json.dumps({"data": [
        {"metadata": {"symbol": "DEAD", "previousClose": 100.0},
         "detail": {"preOpenMarket": {"IEP": 0}}},
    ]})
    assert parse_preopen_payload(payload) == {}


def test_junk_never_becomes_a_row():
    for junk in (None, "", "garbage", "{}", "[]", '{"data": null}'):
        assert parse_preopen_payload(junk) == {}


# ---------------------------------------------------------------
# Collecting
# ---------------------------------------------------------------

def test_a_collection_is_stored_and_readable(tmp_path):
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    assert pre.refresh() == 3
    assert pre.get("INFY")["iep"] == 1151.38
    assert pre.get(" infy ")["iep"] == 1151.38


def test_it_survives_a_restart(tmp_path):
    path = str(tmp_path / "p.json")
    PreOpen(fetcher=lambda url: PAYLOAD, store_path=path).refresh()
    assert PreOpen(fetcher=None, store_path=path).get("INFY") is not None


def test_a_failed_read_does_not_erase_what_was_already_held(tmp_path):
    """The pre-open happens once a day. Losing it to one bad request
    would mean losing it until tomorrow."""
    path = str(tmp_path / "p.json")
    PreOpen(fetcher=lambda url: PAYLOAD, store_path=path).refresh()

    def dead(url):
        raise RuntimeError("NSE timed out")

    pre = PreOpen(fetcher=dead, store_path=path)
    assert pre.refresh() == 0
    assert pre.get("INFY")["iep"] == 1151.38


def test_no_fetcher_collects_nothing_rather_than_crashing(tmp_path):
    assert _pre(tmp_path, None).refresh() == 0


def test_an_empty_book_outside_the_window_is_not_a_crash(tmp_path):
    """Outside 09:00-09:12 NSE returns an empty book. Normal, not an
    error."""
    pre = _pre(tmp_path, lambda url: '{"data": []}')
    assert pre.refresh() == 0


# ---------------------------------------------------------------
# The gap lists
# ---------------------------------------------------------------

def test_gaps_are_split_by_direction_and_sorted_by_size(tmp_path):
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    pre.refresh()
    up, down, _ = pre.gaps(minimum_pct=1.0)
    assert [r["symbol"] for r in up] == ["INFY"]
    assert [r["symbol"] for r in down] == ["TATAMOTORS"]


def test_a_flat_open_is_in_neither_direction(tmp_path):
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    pre.refresh()
    up, down, _ = pre.gaps(minimum_pct=1.0)
    symbols = [r["symbol"] for r in up + down]
    assert "FLAT" not in symbols


def test_a_flat_open_is_still_returned(tmp_path):
    """---- CHANGED 1 AUGUST 2026 ----

        "never throw away any symbol that gets in either direction"

    It is right that FLAT is not called a gap. It was wrong that it
    vanished: the IEP, the matched quantity and the book imbalance are
    all real and all published, and a stock opening flat on forty
    times its normal pre-open interest is worth a line.
    """
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    pre.refresh()
    _, _, unknown = pre.gaps(minimum_pct=1.0)
    assert "FLAT" in [r["symbol"] for r in unknown]


def test_every_symbol_in_the_book_comes_back_somewhere(tmp_path):
    """The guarantee, stated once. Three lists, and their union is the
    whole book -- no row can fall between them."""
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    pre.refresh()
    up, down, unknown = pre.gaps()
    got = {r["symbol"] for r in up + down + unknown}
    assert got == set(pre._data["stocks"].keys())


def test_there_is_no_cap_and_no_floor_unless_one_is_asked_for():
    """top=25 meant the 26th biggest gap of the day did not exist as
    far as the panel was concerned, and minimum_pct=1.0 hid a stock
    opening +0.8% on forty times its normal pre-open volume."""
    import inspect

    from core.preopen import PreOpen

    defaults = inspect.signature(PreOpen.gaps).parameters
    assert defaults["top"].default is None
    assert defaults["minimum_pct"].default == 0.0


def test_the_universe_filter_keeps_untradeable_names_out(tmp_path):
    """NSE's pre-open covers roughly 2,000 stocks. Most are not in the
    bot's universe and would only be noise."""
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    pre.refresh()
    up, down, _ = pre.gaps(symbols={"TATAMOTORS"}, minimum_pct=1.0)
    assert up == []
    assert [r["symbol"] for r in down] == ["TATAMOTORS"]


def test_the_snapshot_is_json_safe(tmp_path):
    pre = _pre(tmp_path, lambda url: PAYLOAD)
    pre.refresh()
    snap = pre.snapshot()
    assert snap["available"] is True
    assert snap["count"] == 3
    json.dumps(snap)


def test_the_snapshot_says_so_when_there_is_nothing(tmp_path):
    assert _pre(tmp_path, None).snapshot()["available"] is False


# ---------------------------------------------------------------
# It recommends NOTHING -- deliberately
# ---------------------------------------------------------------

def test_it_offers_no_opinion_on_whether_a_gap_is_tradeable():
    """Knowing a stock opens +4% and knowing whether to buy it are
    different questions. This module answers the first only; the
    second needs evidence the bot does not have yet."""
    import ast
    tree = ast.parse(open("core/preopen.py", encoding="utf-8").read())
    # The module docstring states the restraint out loud ("does not
    # rank, score, recommend or trade"), so a naive text search finds
    # its own disclaimer. Check the CODE instead: every function and
    # attribute name the module actually defines or calls.
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for word in ("score", "conviction", "recommend", "signal", "rank",
                 "buy_signal", "should_buy"):
        assert not any(word in n.lower() for n in names), \
            f"core/preopen.py defines or calls something named after {word!r}"


# ---------------------------------------------------------------
# THE SEQUENCING CONTRADICTION, 30 July 2026
# ---------------------------------------------------------------
# main.py builds PreOpen(fetcher=None), commented "reads what the 09:12
# run stored". But main.py must be RUNNING before the 09:15 open, and
# NSE's pre-open book does not exist until 09:12. _load() ran once in
# __init__, so a session started at 08:59 held an empty file and served
# it all day.
#
# Live that morning: tools/preopen_gaps.py ran at 09:09, collected 2,007
# stocks correctly, wrote data/preopen.json -- and the dashboard showed
# nothing, because the object in memory had already decided.
#
# There was no start time that worked. Late, and you miss the open; on
# time, and you never see the book.

def test_a_file_written_after_startup_is_picked_up(tmp_path):
    """The exact failure. Construct against an EMPTY file, then have the
    09:12 tool write it, and the panel must fill without a restart."""
    import json
    from core.preopen import PreOpen

    path = tmp_path / "preopen.json"
    path.write_text("{}", encoding="utf-8")

    pre = PreOpen(fetcher=None, store_path=str(path))
    assert pre.snapshot()["available"] is False, "should start empty"

    # What tools/preopen_gaps.py writes at 09:12, in a separate process.
    path.write_text(json.dumps({
        "stocks": {"INFY": {"iep": 1168.0, "prev_close": 1155.6,
                            "gap_pct": 1.07, "matched": 293245,
                            "imbalance": -0.23}},
        "date": "2026-07-30", "collected_at": "09:09:12",
    }), encoding="utf-8")

    snap = pre.snapshot()
    assert snap["available"] is True, \
        "the 09:12 book never reached the screen -- the whole bug"
    assert snap["count"] == 1
    assert snap["collected_at"] == "09:09:12"


def test_an_unchanged_file_is_not_re_parsed(tmp_path):
    """The reload must be a stat(), not a re-read on every refresh --
    the dashboard rebuilds this several times a minute."""
    import json
    from core.preopen import PreOpen

    path = tmp_path / "preopen.json"
    path.write_text(json.dumps({"stocks": {"INFY": {"iep": 1.0}},
                                "date": "d", "collected_at": "t"}),
                    encoding="utf-8")
    pre = PreOpen(fetcher=None, store_path=str(path))
    calls = []
    original = pre._load

    def counting():
        calls.append(1)
        return original()

    pre._load = counting
    pre.snapshot(); pre.snapshot(); pre.snapshot()
    assert not calls, "re-parsed a file that had not changed"


def test_a_deleted_file_does_not_blank_what_we_hold(tmp_path):
    """The pre-open happens once. Losing it to a missing file would mean
    losing it for the day."""
    import json
    from core.preopen import PreOpen

    path = tmp_path / "preopen.json"
    path.write_text(json.dumps({"stocks": {"INFY": {"iep": 1.0, "gap_pct": 1.0}},
                                "date": "d", "collected_at": "t"}),
                    encoding="utf-8")
    pre = PreOpen(fetcher=None, store_path=str(path))
    assert pre.snapshot()["available"] is True
    path.unlink()
    assert pre.snapshot()["available"] is True, "blanked a good book"
