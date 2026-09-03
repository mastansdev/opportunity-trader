"""
Tests for the pre-market SUBSCRIBE = YES/NO gate
(core/subscribe_list.py + MasterLoader's handling of the column).

The costly bug this whole feature exists to prevent: on 2026-07-24 the
bot took trades in STLTECH and SUDEEPPHRM, both T2T (BE series), which
cannot be traded intraday at all. Invisible in PAPER; in LIVE it becomes
compulsory delivery and the short is impossible. test_t2t_is_blocked
is the regression guard for exactly that.
"""

import csv
import os

import pytest

from core.master_loader import MasterLoader
from core.subscribe_list import (
    MIN_TURNOVER_RS,
    NO, REASON_COL, SUBSCRIBE_COL, UNCLASSIFIED_REASON, YES, apply,
    build_bhav_index, decide, find_new_listings, read_master, write_master,
    write_new_stocks_md,
)

# ---- THIN IS RELATIVE TO THE POSITION. 3 September 2026. ----
#
# Five tests in this file used a literal 1.2e7 (Rs 1.2cr) to mean "too
# illiquid", which was true while MIN_TURNOVER_RS was Rs 1.5cr.
# core/subscribe_list.py DERIVES that floor:
#
#     MIN_TURNOVER_RS = _POSITION_RS / MAX_POSITION_SHARE_OF_DAY
#
# so halving the slot to Rs 15,000 on 3 September halved it to
# Rs 0.75cr, and Rs 1.2cr became perfectly liquid. The tests then said
# "assert False is True" about stocks they were no longer describing.
#
# The floor moving is the intended effect -- a smaller position needs
# less of the day's turnover to fill, so MORE stocks are tradeable.
# Pinning it in a fixture was the mistake.
THIN = MIN_TURNOVER_RS / 2               # cannot clear the floor
GOOD = dict(series="EQ", close=850.0, turnover=MIN_TURNOVER_RS * 12)


# ---------------------------------------------------------------
# decide() -- the whole rule set, one symbol at a time
# ---------------------------------------------------------------

def test_a_normal_liquid_eq_stock_is_yes():
    ok, reason = decide("RELIANCE", bhav=GOOD, sector="ENERGY")
    assert ok is True
    assert reason == ""


def test_t2t_is_blocked():
    """The STLTECH / SUDEEPPHRM regression. BE series = no intraday."""
    for series in ("BE", "BZ"):
        ok, reason = decide("STLTECH", bhav=dict(GOOD, series=series),
                            sector="TELECOM")
        assert ok is False
        assert "T2T" in reason
        assert "NO intraday" in reason


def test_etf_and_sgb_are_blocked():
    """Operator: 'do not subscribe to any other (silverbees/gold/inrusd)'."""
    for symbol in ("SILVERBEES", "NIFTYBEES", "GOLDETF", "SGBAUG28"):
        ok, reason = decide(symbol, bhav=GOOD, sector="FUND")
        assert ok is False, symbol
        assert "not on our board" in reason


def test_nse_classified_etf_is_blocked_even_with_a_company_like_name():
    ok, reason = decide("MOTILALFUND", bhav=GOOD, sector="FINANCE",
                        excluded={"MOTILALFUND"})
    assert ok is False
    assert "not on our board" in reason


def test_real_companies_with_fund_like_names_survive():
    """GOLDIAM makes jewellery, SILVERLINE is a real company -- the
    fallback name matcher must not eat them."""
    for symbol in ("GOLDIAM", "SILVERLINE", "GOLDMEDAL"):
        ok, _ = decide(symbol, bhav=GOOD, sector="CONSUMER")
        assert ok is True, symbol


def test_price_alone_no_longer_excludes_a_stock():
    """Both bounds removed 2026-07-29 on the operator's instruction:
    "Remove cap on below 200 & above 10,000 rs as we have moved from
    MIS to MTF we left these two unchanged."

    Rs 200 was a tick-granularity argument and Rs 10,000 a sizing-
    quantisation one. Both were about same-day round trips and neither
    survives multi-day MTF holding."""
    ok, _ = decide("PENNY", bhav=dict(GOOD, close=45.0), sector="X")
    assert ok is True

    ok, _ = decide("MRF", bhav=dict(GOOD, close=130850.0), sector="X")
    assert ok is True


def test_liquidity_still_excludes_a_cheap_scrip_that_barely_trades():
    """Dropping the price floor must not quietly admit scrips nobody
    can get out of. Turnover, not price, is the rule that matters."""
    ok, reason = decide("PENNY", bhav=dict(GOOD, close=45.0, turnover=THIN),
                        sector="X")
    assert ok is False
    assert "%.2fcr" % (THIN / 1_00_00_000) in reason


def test_illiquid_is_blocked_and_the_reason_carries_the_number():
    ok, reason = decide("THINCO", bhav=dict(GOOD, turnover=THIN), sector="X")
    assert ok is False
    assert "%.2fcr" % (THIN / 1_00_00_000) in reason
    assert "illiquid" in reason.lower() or "enter and exit" in reason


def test_narrow_price_band_is_blocked():
    """ASM/GSM surveillance names get banded to 2% or 5% -- a 2% band
    cannot produce a tradeable ORB breakout."""
    ok, reason = decide("WATCHED", bhav=GOOD, sector="X",
                        bands={"WATCHED": 2.0})
    assert ok is False
    assert "2% price band" in reason

    ok, _ = decide("NORMAL", bhav=GOOD, sector="X", bands={"NORMAL": 20.0})
    assert ok is True


def test_corporate_action_today_is_blocked():
    ok, reason = decide("JLHL", bhav=GOOD, sector="X",
                        corporate_actions={"JLHL"})
    assert ok is False
    assert "corporate action today" in reason


def test_an_unclassified_stock_is_NOT_watched():
    """---- AND THE RULE CHANGED BACK. 24 August 2026 ----

    On 23 August I made a blank sector stop blocking a liquid stock,
    for a reason that was real: on 20 August, 22 of the day's top 50
    gainers were invisible to the bot, KRONOX +20% among them, and 100
    of the 262 blocked symbols traded over Rs 2cr a day. That cost is
    NOT disputed and this test is not a claim that it was imaginary.

    What that change did not check is that core/master_loader.py holds
    the OPPOSITE as a hard invariant, and RAISES:

        Master database has 20 TRADEABLE row(s) with missing
        classification ... a tradeable stock with no SECTOR silently
        breaks the sector-strength gate. Either classify them or mark
        them SUBSCRIBE=NO.

    So the change manufactured the exact state the loader forbids. On
    24 August the nightly produced twenty such rows -- JNPR, SIGACHI,
    TNPETRO, MILKYMIST, SHIPROCKET and the rest -- and at 16:20 the
    collector could not start at all:

        Could not start: Master database has 20 TRADEABLE row(s)
        with missing classification

    main.py would have died on its next restart too.

    The invariant wins, and not because it is better reasoned. The
    failure modes are not comparable. An unwatched stock costs one
    missed opportunity, visibly. A stock inside the sector-strength
    gate with no sector mis-ranks silently, with real money -- and a
    bot that will not start costs every opportunity there is.

    The coverage must come back through a SECTOR, not an exception.
    NSE's equityMetaInfo returns name and ISIN only, so that needs a
    different source; guessing a sector from a company name would be
    inventing data.
    """
    ok, reason = decide("NEWIPO", bhav=GOOD, sector="")
    assert ok is False
    assert "awaiting sector classification" in reason


def test_a_classified_stock_on_the_same_data_is_watched():
    # So the assertion above is failing on the SECTOR and nothing else.
    assert decide("NEWIPO", bhav=GOOD, sector="CHEMICALS")[0] is True


def test_the_loader_invariant_and_this_gate_now_agree():
    """The contradiction itself, pinned.

    Any symbol this gate lets through must be one master_loader.py
    will accept. It refuses SUBSCRIBE=YES with a blank SECTOR, so this
    must never return True on a blank sector -- at any liquidity.
    """
    rich = dict(GOOD)
    for key in ("turnover", "value", "traded_value"):
        if key in rich:
            rich[key] = 10 ** 12
    assert decide("HUGE", bhav=rich, sector="")[0] is False


def test_an_unclassified_stock_answers_a_HIGHER_bar():
    """Not no bar. A feed slot is a real resource and we know less
    about these, so they must trade more than a classified name to
    earn one."""
    from core.subscribe_list import UNCLASSIFIED_MIN_TURNOVER_RS
    thin = dict(GOOD, turnover=UNCLASSIFIED_MIN_TURNOVER_RS - 1)
    ok, reason = decide("NEWIPO", bhav=thin, sector="")
    assert ok is False
    assert reason == UNCLASSIFIED_REASON


def test_missing_from_bhavcopy_fails_OPEN():
    """A stock absent from the bhavcopy might be delisted -- or the
    download might simply have been incomplete. Never mark NO on a
    maybe."""
    ok, reason = decide("SOMETHING", bhav=None, sector="X")
    assert ok is True
    assert reason == ""


def test_symbol_case_and_whitespace_do_not_matter():
    ok, _ = decide("  reliance  ", bhav=GOOD, sector="ENERGY")
    assert ok is True


def test_turnover_threshold_is_injectable():
    thin = dict(GOOD, turnover=3e7)          # Rs 3cr
    assert decide("X", bhav=thin, sector="S", min_turnover=5e7)[0] is False
    assert decide("X", bhav=thin, sector="S", min_turnover=2e7)[0] is True


# ---------------------------------------------------------------
# build_bhav_index()
# ---------------------------------------------------------------

def test_eq_row_wins_over_a_non_eq_row_for_the_same_symbol():
    """
    The SUDEEPPHRM case, real data, 2026-07-24. It appears TWICE in the
    bhavcopy: once as series BL (the block-deal window) and once as EQ.
    The old universe tool judged whichever row it saw first and declared
    it T2T -- which was simply wrong; BL is a block deal, not
    trade-to-trade, and the stock is perfectly tradeable intraday.

    An EQ row must always win, or we block good stocks for no reason.
    """
    rows = [
        {"TckrSymb": "SUDEEPPHRM", "SctySrs": "BL", "ClsPric": "800.00",
         "TtlTrfVal": "1600000000"},
        {"TckrSymb": "SUDEEPPHRM", "SctySrs": "EQ", "ClsPric": "825.15",
         "TtlTrfVal": "103161082.55"},
    ]
    index = build_bhav_index(rows)
    assert index["SUDEEPPHRM"]["series"] == "EQ"
    assert index["SUDEEPPHRM"]["close"] == 825.15
    assert decide("SUDEEPPHRM", bhav=index["SUDEEPPHRM"],
                  sector="PHARMA")[0] is True


def test_a_symbol_that_is_ONLY_in_a_non_eq_series_is_still_blocked():
    """STLTECH is BE and nothing else -- genuinely T2T."""
    index = build_bhav_index([
        {"TckrSymb": "STLTECH", "SctySrs": "BE", "ClsPric": "564.15",
         "TtlTrfVal": "2056530992.95"},
    ])
    assert index["STLTECH"]["series"] == "BE"
    assert decide("STLTECH", bhav=index["STLTECH"], sector="TELECOM")[0] is False


def test_turnover_is_derived_when_the_column_is_absent():
    rows = [{"SYMBOL": "X", "SERIES": "EQ", "CLOSE": "200",
             "TOTTRDQTY": "1000"}]
    assert build_bhav_index(rows)["X"]["turnover"] == 200_000


# ---------------------------------------------------------------
# apply() -- stamping the columns onto real rows
# ---------------------------------------------------------------

def _row(symbol, sector="ENERGY", subscribe=None):
    row = {c: "x" for c in
           ("SECURITY ID", "SYMBOL", "COMPANY NAME", "SECTOR", "INDUSTRY",
            "CORE BUSINESS", "BUSINESS_TYPE", "OWNERSHIP",
            "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY", "KEYWORDS",
            "THEMES")}
    row["SYMBOL"] = symbol
    row["SECTOR"] = sector
    row["SECURITY ID"] = str(abs(hash(symbol)) % 100000)
    if subscribe is not None:
        row[SUBSCRIBE_COL] = subscribe
    return row


def test_apply_stamps_both_columns_and_counts():
    rows = [_row("GOOD"), _row("BAD")]
    index = {"GOOD": GOOD, "BAD": dict(GOOD, series="BE")}
    rows, summary = apply(rows, index)

    assert rows[0][SUBSCRIBE_COL] == YES
    assert rows[0][REASON_COL] == ""
    assert rows[1][SUBSCRIBE_COL] == NO
    assert "T2T" in rows[1][REASON_COL]
    assert summary["yes"] == 1 and summary["no"] == 1


def test_apply_reports_what_flipped_since_yesterday():
    rows = [_row("FELL", subscribe=YES), _row("ROSE", subscribe=NO)]
    # Was close=50.0 -- a price that no longer fails anything since
    # the bounds were removed. Turnover is the rule that still bites.
    index = {"FELL": dict(GOOD, turnover=THIN), "ROSE": GOOD}
    _, summary = apply(rows, index)

    assert summary["flipped_off"] and summary["flipped_off"][0][0] == "FELL"
    assert summary["flipped_on"] == ["ROSE"]


def test_apply_is_idempotent():
    rows = [_row("A"), _row("B", sector="")]
    index = {"A": GOOD, "B": GOOD}
    once, _ = apply([dict(r) for r in rows], index)
    twice, summary = apply([dict(r) for r in once], index)

    assert [r[SUBSCRIBE_COL] for r in once] == [r[SUBSCRIBE_COL] for r in twice]
    # nothing "changed" on the second run
    assert summary["flipped_on"] == [] and summary["flipped_off"] == []


# ---------------------------------------------------------------
# write_master() -- the file the bot refuses to start without
# ---------------------------------------------------------------

def test_write_master_roundtrips_and_adds_the_columns(tmp_path):
    path = str(tmp_path / "master.csv")
    rows = [_row("AAA"), _row("BBB")]
    rows, _ = apply(rows, {"AAA": GOOD, "BBB": dict(GOOD, series="BE")})
    write_master(rows, path)

    back, fieldnames = read_master(path)
    assert SUBSCRIBE_COL in fieldnames
    assert REASON_COL in fieldnames
    assert [r[SUBSCRIBE_COL] for r in back] == [YES, NO]
    # no temp file left behind
    assert not os.path.exists(path + ".tmp")


def test_write_master_never_loses_the_hand_built_columns(tmp_path):
    """The whole reason we mark instead of delete: SECTOR / KEYWORDS /
    THEMES are expensive to rebuild."""
    path = str(tmp_path / "master.csv")
    row = _row("KEEPME", sector="PHARMA")
    row["KEYWORDS"] = "ONCOLOGY | GENERICS"
    row["THEMES"] = "HEALTHCARE"
    rows, _ = apply([row], {"KEEPME": dict(GOOD, turnover=THIN)})  # -> NO
    write_master(rows, path)

    back, _ = read_master(path)
    assert back[0][SUBSCRIBE_COL] == NO
    assert back[0]["KEYWORDS"] == "ONCOLOGY | GENERICS"
    assert back[0]["SECTOR"] == "PHARMA"


# ---------------------------------------------------------------
# find_new_listings() + NEW_STOCKS.md
# ---------------------------------------------------------------

def test_find_new_listings_skips_what_we_already_have():
    # PENNY at Rs 12 is a genuine new listing now that price alone
    # excludes nothing -- ILLIQUID is the one that still gets skipped.
    index = {"HAVE": GOOD, "NEW": GOOD,
             "ILLIQUID": dict(GOOD, turnover=THIN)}
    found = find_new_listings(index, known_symbols={"HAVE"})
    assert [r["symbol"] for r in found] == ["NEW"]


def test_find_new_listings_sorts_by_turnover():
    index = {"SMALL": dict(GOOD, turnover=6e7),
             "BIG": dict(GOOD, turnover=9e8)}
    found = find_new_listings(index, known_symbols=set())
    assert [r["symbol"] for r in found] == ["BIG", "SMALL"]


def test_new_stocks_md_flags_rows_with_no_dhan_id(tmp_path):
    path = str(tmp_path / "NEW_STOCKS.md")
    write_new_stocks_md(
        [dict(symbol="WITHID", close=500.0, turnover=9e7),
         dict(symbol="NOID", close=500.0, turnover=9e7)],
        path=path, security_ids={"WITHID": "12345"},
    )
    text = open(path, encoding="utf-8").read()
    assert "| WITHID | 12345 |" in text
    assert "cannot trade" in text          # the NOID row is flagged
    assert "2 waiting" in text


# ---------------------------------------------------------------
# MasterLoader honours the column
# ---------------------------------------------------------------

def _write_csv(path, rows, with_subscribe=True):
    cols = ["SECURITY ID", "SYMBOL", "COMPANY NAME", "SECTOR", "INDUSTRY",
            "CORE BUSINESS", "BUSINESS_TYPE", "OWNERSHIP",
            "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY", "KEYWORDS",
            "THEMES"]
    if with_subscribe:
        cols += [SUBSCRIBE_COL, REASON_COL]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "x") for c in cols})


def test_loader_subscribes_to_yes_only(tmp_path):
    path = str(tmp_path / "m.csv")
    _write_csv(path, [
        dict(_row("TRADEME"), **{SUBSCRIBE_COL: YES, REASON_COL: ""}),
        dict(_row("SKIPME"), **{SUBSCRIBE_COL: NO,
                                REASON_COL: "series BE (T2T)"}),
    ])
    loader = MasterLoader(path)
    loader.load()

    assert loader.all_symbols() == ["TRADEME"]
    assert loader.blocked_symbols() == {"SKIPME": "series BE (T2T)"}
    assert loader.has_subscribe_column is True
    # still fully looked-up-able for sector / news purposes
    assert loader.get_by_symbol("SKIPME") is not None
    assert set(loader.all_symbols(include_blocked=True)) == {"TRADEME",
                                                             "SKIPME"}


def test_loader_without_the_column_treats_everything_as_tradeable(tmp_path):
    """Backward compatibility: the bot must never refuse to start just
    because the morning tool hasn't been run."""
    path = str(tmp_path / "m.csv")
    _write_csv(path, [_row("A"), _row("B")], with_subscribe=False)
    loader = MasterLoader(path)
    loader.load()

    assert sorted(loader.all_symbols()) == ["A", "B"]
    assert loader.blocked_symbols() == {}
    assert loader.has_subscribe_column is False


@pytest.mark.parametrize("value", ["", "  ", "yes", "Yes", "maybe"])
def test_loader_fails_open_on_a_blank_or_garbled_cell(tmp_path, value):
    """Only an explicit NO blocks. A blank cell must not silently drop a
    stock from the feed."""
    path = str(tmp_path / "m.csv")
    _write_csv(path, [dict(_row("X"), **{SUBSCRIBE_COL: value,
                                         REASON_COL: ""})])
    loader = MasterLoader(path)
    loader.load()
    assert loader.all_symbols() == ["X"]


def test_loader_blocks_on_lowercase_no(tmp_path):
    path = str(tmp_path / "m.csv")
    _write_csv(path, [dict(_row("X"), **{SUBSCRIBE_COL: " no ",
                                         REASON_COL: "illiquid"})])
    loader = MasterLoader(path)
    loader.load()
    assert loader.all_symbols() == []
    assert loader.blocked_symbols() == {"X": "illiquid"}
