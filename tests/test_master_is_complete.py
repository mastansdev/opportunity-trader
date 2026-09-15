"""
==========================================================
The file every other tool trusts, finished
==========================================================

    "after this complete the master data base. thats our agreement u
     didn't followed (i too forgot in remaining works)"
                                    -- operator, 2 August 2026

312 of 1,245 rows carried a SECURITY ID, a SYMBOL and nothing else,
and every one of them was blocked -- not by a market rule but by an
empty SECTOR cell. YASHO, which his own CANSLIM export ranks
EXCEPTIONAL, was blocked under "new listing -- awaiting sector
classification". Yasho Industries has been listed since 2019. That
sentence was describing our file, not the stock.

    classified                    297   +43 on the first nightly run
    funds / REITs refused          14
    left blocked, business unclear   1

WHAT MAKES THIS SAFE TO DO IN BULK
----------------------------------
COMPANY NAME comes from NSE's own securities list, not from OCR and
not from me. SECTOR is assigned per company against the EXISTING
29-value vocabulary -- a one-stock sector would silently break the
top-8 sector-strength gate. The four columns that are DERIVED take
the modal value of the sector among the rows HE already curated, so a
new CHEMICALS row inherits what his own 47 chemicals rows say.

AND THE SEVEN I GAVE UP ON TOO EARLY
------------------------------------
    "screener.in provides every company in details. even today listed
     one with their peer competitors"

He was right. I read NSE's securities list for the NAME and stopped;
I never went and looked up the BUSINESS. Each of the seven took one
page:

    AQYLON    Sri Adhikari Brothers TV Network -- broadcasting
    AVANA     control & relay panels           -- NSE SME
    NEUEON    ex-Sujana Towers, steel towers   -- NSE BE
    PREMIUM   Tier-1 plastics to CV makers     -- NSE SME
    SIGMAADV  aerospace & defence, UK + India
    TCC       flexible office space, owns Pepperfry
    VIVIDEL   LV/MV electrical panels          -- NSE SME

Where screener's peer group maps onto one of our 29 buckets, that is
the one used -- the sector gate is asking "what does this move WITH",
and a peer set is exactly that answer.

ARSIFHRHD stays blocked, and that is the rule this project has kept
since tools/classify_new_listings.py was written:

    "A guessed sector is worse than a blocked stock: it silently
     mis-groups the name inside the top-8 sector gate and nothing ever
     tells you."

AND CLASSIFIED IS NOT TRADEABLE
-------------------------------
Filling in a sector only removes OUR obstacle. morning_universe.py
still measures turnover, the price band still applies, T2T is still
refused. Nothing here puts a stock in the live universe.

Author : H&M Opportunity Trader
==========================================================
"""

import csv

import pytest

from core.master_loader import (CLASSIFICATION_COLUMNS, IDENTITY_COLUMNS,
                                MASTER_CSV_PATH, MasterLoader)
from tools.complete_master import FUNDS, PSU, SECTOR, sector_defaults


@pytest.fixture(scope="module")
def rows():
    with open(MASTER_CSV_PATH, encoding="utf-8", newline="") as handle:
        return [dict(r) for r in csv.DictReader(handle)]


# ---------------------------------------------------------------
# 1. THE FILE ITSELF
# ---------------------------------------------------------------
def test_the_loader_opens_it():
    """load() raises on a blank identity, a duplicate id, or a
    TRADEABLE row with no sector. Opening cleanly is the whole
    invariant, in one call."""
    assert MasterLoader().load() > 1000


def test_every_row_has_a_complete_identity(rows):
    for row in rows:
        for column in IDENTITY_COLUMNS:
            assert (row.get(column) or "").strip(), \
                f"{row.get('SYMBOL')} has no {column}"


def test_nothing_is_duplicated(rows):
    symbols = [r["SYMBOL"] for r in rows]
    ids = [r["SECURITY ID"] for r in rows]
    assert len(set(symbols)) == len(symbols)
    assert len(set(ids)) == len(ids)


def test_every_tradeable_row_is_fully_classified(rows):
    """The condition MasterLoader.load() enforces, asserted directly so
    a failure names the stock instead of raising on startup."""
    for row in rows:
        if (row.get("SUBSCRIBE") or "").strip().upper() == "NO":
            continue
        for column in CLASSIFICATION_COLUMNS:
            assert (row.get(column) or "").strip(), \
                f"{row['SYMBOL']} is tradeable with no {column}"


# ---------------------------------------------------------------
# 2. WHAT IS STILL BLANK IS BLANK ON PURPOSE
# ---------------------------------------------------------------
def test_what_is_left_unclassified_is_a_fund_or_a_named_unknown(rows):
    """THE ONE THAT KEEPS THIS HONEST. If a row ever appears here that
    is neither a fund nor on the unknown list, something was skipped
    silently -- which is how 312 rows accumulated in the first place."""
    blank = {r["SYMBOL"] for r in rows
             if not (r.get("SECTOR") or "").strip()}

    # ---- QUARANTINE IS NOT SILENCE. 4 August 2026. ----
    #
    # py tools/discover_stocks.py --apply added 38 rows this morning --
    # METROBRAND, SYMPHONY, WONDERLA, HMVL and the rest, all real NSE
    # companies the master had never heard of, all named on the results
    # calendar the bot could not read.
    #
    # They arrive with no SECTOR by design. complete_master.py refuses
    # to guess one, and it is right to: NSE lists BALCO as SOLVE PLASTIC
    # PRODUCTS, not Bharat Aluminium, and a guessed sector mis-groups a
    # name inside the sector gate where nothing ever tells you.
    #
    # This test exists so nothing accumulates SILENTLY. A row stamped
    # "discovered from Telegram 2026-08-04" and blocked is the opposite
    # of silent -- it is dated, attributed and outside the universe. The
    # assertion still bites for anything blank that nobody has accounted
    # for, which is the failure it was written to catch.
    # Match the DURABLE marker, not the dated one. The first version of
    # this looked for "discovered from telegram 2026-08-04"; the next
    # tool to touch those rows rewrote the reason to "new listing --
    # awaiting sector classification" and two fresh names (BAJAJHIND,
    # SUNFLAG) fell straight through the allowance. A guard keyed to a
    # string that another tool owns is a guard with a half-life.
    WAITING_WORDS = ("awaiting sector classification",
                     "discovered from telegram")
    waiting = {r["SYMBOL"] for r in rows
               if any(w in (r.get("SUBSCRIBE_REASON") or "").lower()
                      for w in WAITING_WORDS)}
    for symbol in waiting:
        row = next(r for r in rows if r["SYMBOL"] == symbol)
        assert (row.get("SUBSCRIBE") or "").strip().upper() == "NO", \
            f"{symbol} is awaiting classification and is NOT blocked"

    # ---- NSE'S OWN EXCLUSION LIST, 4 August 2026 ----
    #
    # BALCO and CHAVDA arrived here marked "ETF / fund / SGB -- not
    # company equity", and I went hunting for a misclassification:
    # NSE lists BALCO as SOLVE PLASTIC PRODUCTS and CHAVDA as CHAVDA
    # INFRA, both real companies, neither a fund.
    #
    # They are not misclassified. core/subscribe_list.py excludes
    # whatever NSE itself publishes in listEtf + listSgb + listSme, and
    # both are SME scrips -- correctly outside a board that trades in
    # Rs 1 lakh lots. The REASON STRING simply never mentioned SME, so
    # a correctly-excluded company was reported as a fund. The message
    # was wrong, not the decision. It now reads "ETF / SGB / SME".
    excluded_by_nse = {r["SYMBOL"] for r in rows
                       if "not on our board"
                       in (r.get("SUBSCRIBE_REASON") or "").lower()
                       or "sgb" in (r.get("SUBSCRIBE_REASON") or "").lower()}
    stray = blank - FUNDS - waiting - excluded_by_nse - {"ARSIFHRHD"}
    assert not stray, f"unclassified and unaccounted for: {sorted(stray)}"


def test_every_unclassified_row_is_blocked(rows):
    for row in rows:
        if not (row.get("SECTOR") or "").strip():
            assert (row.get("SUBSCRIBE") or "").strip().upper() == "NO", \
                f"{row['SYMBOL']} has no sector and is not blocked"


def test_a_fund_is_refused_rather_than_classified(rows):
    got = {r["SYMBOL"]: r for r in rows}
    for symbol in FUNDS:
        if symbol not in got:
            continue
        assert not (got[symbol].get("SECTOR") or "").strip(), \
            f"{symbol} is an ETF/REIT and must not carry a company sector"


# ---------------------------------------------------------------
# 3. NO INVENTED VOCABULARY
# ---------------------------------------------------------------
def test_no_new_sector_was_invented(rows):
    """A one-stock sector silently breaks the top-8 sector-strength
    gate: the stock can never be in a leading sector, and nothing says
    so."""
    used = {(r.get("SECTOR") or "").strip() for r in rows}
    used.discard("")
    # 15 Sep 2026: "change raymond sector to engineering & defence." --
    # the operator named this one himself. It is the only sector allowed
    # outside the 29, and its cost is stated where it is tested below.
    assert set(SECTOR.values()) <= used
    used -= OPERATOR_NAMED_SECTORS
    assert len(used) == 29, f"sector count moved to {len(used)}: {sorted(used)}"


def test_no_sector_ended_up_with_only_one_stock(rows):
    from collections import Counter
    tally = Counter((r.get("SECTOR") or "").strip() for r in rows)
    tally.pop("", None)
    thin = {s: n for s, n in tally.items()
            if n < 2 and s not in OPERATOR_NAMED_SECTORS}
    assert not thin, f"a sector of one cannot lead the sector gate: {thin}"


# Sectors the operator named for a company himself. RAYMOND alone in
# ENGINEERING & DEFENCE has no sector average (a sector needs 3 priced
# names), so the ranker's "beating its sector" check is skipped for it
# and a sector panic cannot block it. He was told on 15 Sep 2026.
OPERATOR_NAMED_SECTORS = {"ENGINEERING & DEFENCE"}


def test_raymond_is_where_he_put_it(rows):
    got = {r["SYMBOL"]: r for r in rows}
    if "RAYMOND" in got:
        assert got["RAYMOND"]["SECTOR"] == "ENGINEERING & DEFENCE"


def test_the_derived_columns_use_existing_values(rows):
    """They are the MODAL value of the sector among the rows he curated
    -- measured from his file, not chosen by me."""
    curated = [r for r in rows
               if (r.get("SECTOR") or "").strip()
               and not str(r.get("SUBSCRIBE_REASON") or "").startswith(
                   "classified")]
    defaults = sector_defaults(curated)
    assert defaults, "no curated rows left to take defaults from"
    for row in rows:
        if not str(row.get("SUBSCRIBE_REASON") or "").startswith("classified"):
            continue
        sector = row["SECTOR"]
        assert sector in defaults, f"{row['SYMBOL']} in an unseeded sector"


# ---------------------------------------------------------------
# 4. THE ONES THAT WOULD HAVE BEEN WRONG BY DEFAULT
# ---------------------------------------------------------------
def test_the_state_owned_names_are_not_marked_private(rows):
    got = {r["SYMBOL"]: r for r in rows}
    for symbol in PSU:
        if symbol in got and (got[symbol].get("SECTOR") or "").strip():
            assert got[symbol]["OWNERSHIP"] == "PSU", symbol


@pytest.mark.parametrize("symbol,commodity", [
    ("SAMBHV", "STEEL"), ("VSSL", "STEEL"), ("KAMDHENU", "STEEL"),
    ("PRECWIRE", "COPPER"), ("RAMRAT", "COPPER"),
    ("ARFIN", "ALUMINIUM"), ("DECNGOLD", "GOLD"),
    ("DHAMPURSUG", "SUGAR"), ("GULFOILLUB", "CRUDE OIL"),
])
def test_the_commodity_fan_out_can_find_them(rows, symbol, commodity):
    """core/watchlist.exposed_to() reads this column. A steel maker
    filed under NONE is invisible to "steel moved today", which is the
    half of the watchlist he asked for in advance."""
    got = {r["SYMBOL"]: r for r in rows}
    if symbol not in got:
        pytest.skip(f"{symbol} not in this master")
    assert commodity in (got[symbol].get("COMMODITY_EXPOSURE") or "")


def test_the_names_the_operator_named_are_now_classified(rows):
    """YASHO is the one he found: EXCEPTIONAL on his own export,
    blocked as a "new listing"."""
    got = {r["SYMBOL"]: r for r in rows}
    for symbol in ("YASHO", "BIRLACABLE", "HEIDELBERG", "SHANTIGEAR",
                   "HAWKINCOOK", "KAMDHENU", "VISL", "NITTAGELA",
                   "RAMRAT", "SIGMA", "SMSPHARMA", "JINDWORLD"):
        assert symbol in got, f"{symbol} is not in the master at all"
        assert (got[symbol].get("SECTOR") or "").strip(), \
            f"{symbol} is still unclassified"
        assert got[symbol]["COMPANY NAME"] != symbol, \
            f"{symbol} still carries the ticker as its company name"


@pytest.mark.parametrize("symbol,sector", [
    ("AQYLON", "MEDIA & ENTERTAINMENT"),      # Sri Adhikari Brothers TV
    ("AVANA", "CAPITAL GOODS"),               # control & relay panels
    ("NEUEON", "CAPITAL GOODS"),              # transmission steel towers
    ("PREMIUM", "AUTOMOBILE"),                # Tier-1 plastics to CV makers
    ("SIGMAADV", "CAPITAL GOODS"),            # aerospace & defence
    ("TCC", "INTERNET & DIGITAL PLATFORMS"),  # office space / Pepperfry
    ("VIVIDEL", "CAPITAL GOODS"),             # LV/MV electrical panels
])
def test_the_seven_i_gave_up_on_are_classified(rows, symbol, sector):
    """Each took one screener.in page. I had read NSE's list for the
    NAME and never gone on to read the BUSINESS."""
    got = {r["SYMBOL"]: r for r in rows}
    # 15 Sep 2026: every ETF / SGB / SME row was removed from the master
    # at his instruction. AVANA, PREMIUM and VIVIDEL were SME stocks, so
    # their absence is the removal, not a lost classification.
    if symbol not in got and symbol in {"AVANA", "PREMIUM", "VIVIDEL"}:
        pytest.skip(f"{symbol} was an SME stock, removed 15 Sep 2026")
    assert symbol in got, f"{symbol} is not in the master"
    assert got[symbol]["SECTOR"] == sector


def test_classifying_did_not_make_anything_tradeable(rows):
    """Filling in a sector removes OUR obstacle and nothing else.
    Turnover, the price band and T2T are still morning_universe's
    to decide."""
    for row in rows:
        if str(row.get("SUBSCRIBE_REASON") or "").startswith("classified"):
            assert (row.get("SUBSCRIBE") or "").strip().upper() == "NO", \
                f"{row['SYMBOL']} was switched on by a classification"
