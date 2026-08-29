"""A barrel is not Bharat Bijlee.

    "day trader telugu posts data images after 08 am daily bulk
     images"                          -- operator, 29 August 2026

Those bulk images carry macro and commodity lines, and three NSE
tickers are ordinary words inside them:

    "CRUDE OIL FUTURES SETTLE AT $84.94/BBL"
       -> OIL     Oil India
       -> BBL     Bharat Bijlee, out of the BARREL
    "NET PURCHASE OF US DOLLARS"
       -> DOLLAR  Dollar Industries

The capitals guard in symbols_in() cannot see these: the whole line is
shouted, so they read exactly like a real ticker mention. And since
REQUIRE_A_REASON_ALWAYS, an event is what makes a stock tradeable at
all -- so a crude price quoted per barrel was handing Bharat Bijlee a
reason to be traded on.

Measured on the 1,525 stored messages before shipping: 20 links
removed across 16 messages -- OIL x10, BBL x9, DOLLAR x1 -- every one
of them false.

WHY THE RULE IS THIS NARROW. The blunt version was tried on 1 August
-- ignore bare words on any all-caps line -- and reverted, because it
removed 83 links and most were TRUE. Day Trader Telugu writes every
post in capitals. So this masks the OCCURRENCE, never the symbol: a
message that also says "#OIL" or "OIL INDIA" still links.
"""

import pathlib

import pytest

from core.master_loader import MasterLoader
from core.telegram_feed import TelegramFeed

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def feed(tmp_path_factory):
    loader = MasterLoader()
    loader.load()
    got = TelegramFeed(
        db_path=str(tmp_path_factory.mktemp("tg") / "tg.db"),
        master_loader=loader)
    if not got._known_symbols():
        pytest.skip("no master list available in this environment")
    return got


def _real_tickers(feed, *names):
    known = feed._known_symbols()
    missing = [n for n in names if n not in known]
    if missing:
        pytest.skip(f"not in this master list: {missing}")


# ------------------------------------------------- the false ones go

@pytest.mark.parametrize("line", [
    "U.S. CRUDE OIL FUTURES SETTLE AT $84.94/BBL, UP 44 CENTS, OR 0.52%",
    "BRENT CRUDE FUTURES FALL MORE THAN $1 TO $87.03/BBL",
    "WEST ASIA CRISIS IS QUIETLY HITTING INDIAN FACTORIES - CRUDE OIL UP",
])
def test_a_commodity_line_names_no_company(feed, line):
    _real_tickers(feed, "OIL", "BBL")
    got = feed.symbols_in(line)
    assert "OIL" not in got, f"Oil India linked to a crude price: {got}"
    assert "BBL" not in got, f"Bharat Bijlee linked to a barrel: {got}"


def test_a_currency_line_names_no_company(feed):
    _real_tickers(feed, "DOLLAR")
    assert "DOLLAR" not in feed.symbols_in(
        "NET PURCHASE OF US DOLLARS IN THE CURRENCY MARKET")


@pytest.mark.parametrize("line", [
    "silver futures rose Rs 2,053 to Rs 2,46,180/kg",
    "Offer Floor Price Set At Rs 5,773.63/Sh, May Offer Discount",
    "Signs 130 MW PPA With REMC At Rs 4.35/kWh For 25 Yrs",
    "SAIL to increase its prices by another Rs 1,000/MT",
])
def test_a_unit_after_a_number_is_never_a_ticker(feed, line):
    """Only BBL is also a real ticker; the rest match nothing anyway.
    Asserted together because the RULE is what must hold, not the
    accident that most units are not listed companies."""
    for unit in ("KG", "SH", "KWH", "MT", "BBL"):
        assert unit not in feed.symbols_in(line)


# ------------------------------------------------- the true ones stay

@pytest.mark.parametrize("line,want", [
    ("OIL INDIA: Q1 CONS NET PROFIT RISES 18%", "OIL"),
    ("#BBL BHARAT BIJLEE SECURES ORDER WORTH RS 120 CR", "BBL"),
    ("DOLLAR INDUSTRIES: CO REPORTS 12% REVENUE GROWTH", "DOLLAR"),
])
def test_the_company_itself_still_links(feed, line, want):
    """The 1 August lesson: losing a true link to fix a false one is a
    bad trade."""
    _real_tickers(feed, want)
    assert want in feed.symbols_in(line)


def test_one_line_can_hold_both_the_unit_and_the_company(feed):
    """The occurrence is masked, not the symbol.

    A card that quotes a crude price AND names Bharat Bijlee must
    still link it. This is what makes the rule safe where the 1 August
    all-caps guard was not.
    """
    _real_tickers(feed, "BBL")
    got = feed.symbols_in(
        "CRUDE AT $84.94/BBL. #BBL BHARAT BIJLEE WINS RS 120 CR ORDER")
    assert "BBL" in got


def test_an_ordinary_order_win_is_untouched(feed):
    got = feed.symbols_in(
        "GOLDIAM INTERNATIONAL: CO WINS EXPORT ORDER WORTH RS 50 CR")
    assert "GOLDIAM" in got


# ------------------------------------------------- and the trap itself

def test_no_literal_backspace_survived_in_the_source():
    """This has now cost two debugging sessions in one day.

    Writing these patterns through a shell heredoc turned every `\\b`
    word boundary into byte 0x08 -- a real backspace -- so the regex
    silently matched almost nothing and the guard did no work while
    looking perfectly correct in a diff.
    """
    for name in ("core/telegram_feed.py", "core/stock_events.py"):
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        assert chr(8) not in text, (
            f"{name} contains a literal backspace byte -- a regex word "
            f"boundary was written through a shell and mangled")
