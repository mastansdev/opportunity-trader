"""
Tests for core/index_members.py.

    "i'll check these NIFTY50, ALL NIFTY, FNO STOCKS for top
     gainers/loosers both in pre-open markets sessions"
                                    -- operator, 29 July 2026

The pre-open panel drew those group buttons on 29 July and clicking
one redrew the identical list, because nothing in the bot knew which
stock was in which index. A button that pretends to filter is worse
than no button -- it would have been trusted at 09:05.

THE RULE: an unknown group is EMPTY, never unfiltered. Serving every
stock under a "NIFTY 50" heading is the exact lie this prevents.

SOURCE CHANGED 30 July 2026. This used to test a JSON payload from
/api/equity-stockIndices. That endpoint returns NSE's 382-byte "Resource
not found" page for every index name and every encoding, and always has
-- there is no successful [INDEX] fetch in any log this project has
written. tools/nse_handshake.py proved it is neither a block nor an
encoding fault: on the same session /api/marketStatus and /api/allIndices
returned 200 JSON, so parameterless endpoints answer and parameterised
ones do not.

Membership now comes from NSE's published CSVs, so the fixtures below are
the real file shapes -- including fo_mktlots.csv's space-padded headers,
its index underlyings and its trailing footnote, each of which broke a
naive parser.
"""

import json
from datetime import datetime, timedelta

from core.index_members import IndexMembers, symbols_from_csv

# ind_nifty50list.csv -- header exactly as the live file serves it.
NIFTY_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Reliance Industries Ltd.,Oil Gas,RELIANCE,EQ,INE002A01018\n"
    "Infosys Ltd.,Information Technology,INFY,EQ,INE009A01021\n"
    "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n"
)

# fo_mktlots.csv -- the awkward one. Headers are padded with spaces, the
# file lists INDEX derivatives alongside stocks, and it ends with a note.
FNO_CSV = (
    "UNDERLYING                     ,SYMBOL    ,AUG-26     ,SEP-26\n"
    "NIFTY                          ,NIFTY     ,75         ,75\n"
    "NIFTY BANK                     ,BANKNIFTY ,30         ,30\n"
    "Reliance Industries Ltd        ,RELIANCE  ,500        ,500\n"
    "Infosys Ltd                    ,INFY      ,400        ,400\n"
    "Tata Consultancy Services Ltd  ,TCS       ,175        ,175\n"
    "Kaynes Technology India Ltd    ,KAYNES    ,150        ,150\n"
    "PCBL Chemical Ltd              ,PCBL      ,2700       ,2700\n"
    "Note: lot sizes revised wef    ,          ,           ,\n"
)


def _fetcher(mapping, fail=()):
    def fetch(url):
        for key, payload in mapping.items():
            if key in url:
                if key in fail:
                    raise RuntimeError("NSE said no")
                return payload
        return ""
    return fetch


# Keyed on a fragment of the real archive URLs.
BOTH = {"ind_nifty50list": NIFTY_CSV, "fo_mktlots": FNO_CSV}


def _members(tmp_path, fetcher=None, **kw):
    return IndexMembers(fetcher=fetcher,
                        cache_path=str(tmp_path / "members.json"), **kw)


# ---------------------------------------------------------------

def test_membership_is_fetched_and_split_by_group(tmp_path):
    m = _members(tmp_path, _fetcher(BOTH))
    m.refresh()
    assert m.members("nifty50") == {"RELIANCE", "INFY", "TCS"}
    assert m.members("fno") == {"RELIANCE", "INFY", "TCS", "KAYNES", "PCBL"}


def test_it_answers_the_question_the_panel_asks(tmp_path):
    m = _members(tmp_path, _fetcher(BOTH))
    m.refresh()
    assert m.contains("nifty50", "infy") is True
    assert m.contains("nifty50", "KAYNES") is False
    assert m.contains("fno", "KAYNES") is True


def test_an_unknown_group_is_empty_not_everything(tmp_path):
    """The whole point. dashboard/state.py hides a group with no
    membership; if this returned "all symbols" instead, the panel
    would show the full list under a NIFTY 50 heading."""
    m = _members(tmp_path)
    assert m.members("nifty50") == set()
    assert m.known_groups() == set()


# ---------------------------------------------------------------
# the cache -- twelve minutes is too precious to spend fetching
# ---------------------------------------------------------------

def test_it_is_written_to_disk_and_read_back(tmp_path):
    _members(tmp_path, _fetcher(BOTH)).refresh()
    again = _members(tmp_path)                       # no fetcher at all
    assert again.members("nifty50") == {"RELIANCE", "INFY", "TCS"}


def test_a_fresh_cache_is_not_re_fetched(tmp_path):
    calls = []

    def counting(url):
        calls.append(url)
        return NIFTY_CSV

    m = _members(tmp_path, counting)
    m.refresh()
    before = len(calls)
    m.refresh()
    assert len(calls) == before, "re-fetched a cache that was current"


def test_force_re_fetches_anyway(tmp_path):
    calls = []

    def counting(url):
        calls.append(url)
        return NIFTY_CSV

    m = _members(tmp_path, counting)
    m.refresh()
    m.refresh(force=True)
    assert len(calls) > 2


def test_an_old_cache_is_stale(tmp_path):
    path = tmp_path / "members.json"
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    path.write_text(json.dumps({"fetched_at": old,
                                "members": {"nifty50": ["INFY"]}}),
                    encoding="utf-8")
    assert _members(tmp_path).is_stale() is True


def test_a_corrupt_cache_does_not_stop_the_bot_starting(tmp_path):
    (tmp_path / "members.json").write_text("{not json", encoding="utf-8")
    m = _members(tmp_path)
    assert m.members("nifty50") == set()
    assert m.is_stale() is True


# ---------------------------------------------------------------
# a failed fetch must never empty a good list
# ---------------------------------------------------------------

def test_a_failed_fetch_keeps_yesterdays_list(tmp_path):
    """Yesterday's NIFTY 50 is almost certainly still correct. An
    empty one is not."""
    m = _members(tmp_path, _fetcher(BOTH))
    m.refresh()

    m.fetcher = _fetcher(BOTH, fail=("ind_nifty50list",))
    m.refresh(force=True)
    assert m.members("nifty50") == {"RELIANCE", "INFY", "TCS"}


def test_an_empty_response_is_not_treated_as_an_empty_index(tmp_path):
    """An empty body means the request was refused, not that NIFTY 50 has
    no constituents. This is the failure mode that actually happened: the
    old endpoint served a 382-byte HTML error page, which parses to zero
    symbols and would have wiped a good list every week."""
    m = _members(tmp_path, _fetcher(BOTH))
    m.refresh()
    m.fetcher = lambda url: ""
    m.refresh(force=True)
    assert len(m.members("nifty50")) == 3


def test_an_html_error_page_does_not_wipe_a_good_list(tmp_path):
    """The exact body NSE returns for the retired endpoint."""
    m = _members(tmp_path, _fetcher(BOTH))
    m.refresh()
    m.fetcher = lambda url: (
        '<!DOCTYPE html> <html lang="en"> <head> <meta charset="UTF-8"> '
        '<title>Resource not found</title> </head> <body></body></html>')
    m.refresh(force=True)
    assert m.members("nifty50") == {"RELIANCE", "INFY", "TCS"}


def test_one_group_failing_does_not_cost_the_other(tmp_path):
    m = _members(tmp_path, _fetcher(BOTH, fail=("ind_nifty50list",)))
    m.refresh()
    assert m.members("nifty50") == set()
    assert "PCBL" in m.members("fno")


def test_status_reports_what_is_actually_held(tmp_path):
    m = _members(tmp_path, _fetcher(BOTH))
    m.refresh()
    status = m.status()
    assert status["counts"] == {"nifty50": 3, "fno": 5}
    assert status["stale"] is False
    assert status["fetched_at"]


# ---------------------------------------------------------------
# parsing NSE's published CSVs
# ---------------------------------------------------------------

def test_padded_headers_are_matched(tmp_path):
    """fo_mktlots.csv's header is "UNDERLYING              ,SYMBOL    ,..."
    -- matching the raw name finds nothing and the group silently stays
    empty, which is indistinguishable from a blocked fetch."""
    assert symbols_from_csv(FNO_CSV, "SYMBOL") == {
        "RELIANCE", "INFY", "TCS", "KAYNES", "PCBL"}


def test_index_underlyings_are_not_stocks():
    """fo_mktlots.csv lists NIFTY and BANKNIFTY next to single stocks.
    The operator asked for FNO STOCKS; an index in a stock filter matches
    nothing in the pre-open book and reads as a bug."""
    got = symbols_from_csv(FNO_CSV, "SYMBOL")
    assert "NIFTY" not in got
    assert "BANKNIFTY" not in got


def test_the_trailing_footnote_is_not_a_ticker():
    assert "NOTE:" not in symbols_from_csv(FNO_CSV, "SYMBOL")


def test_a_repeated_header_row_is_not_a_ticker():
    """fo_mktlots.csv restates its column names partway down the file, so
    the literal "SYMBOL" was collected as a ticker and reached the live
    F&O list -- 209 members where there are 208.

    It defeated every other filter: no spaces, not an index underlying,
    plain alphanumeric, right length. Only cross-checking the result
    against master_stocks.csv found it, which is the argument for doing
    that check at all.
    """
    with_repeat = (
        "UNDERLYING                     ,SYMBOL    ,AUG-26\n"
        "Reliance Industries Ltd        ,RELIANCE  ,500\n"
        "UNDERLYING                     ,SYMBOL    ,AUG-26\n"
        "Infosys Ltd                    ,INFY      ,400\n"
    )
    got = symbols_from_csv(with_repeat, "SYMBOL")
    assert got == {"RELIANCE", "INFY"}
    assert "SYMBOL" not in got
    assert "UNDERLYING" not in got


def test_a_halted_stock_is_still_in_the_index():
    """Membership is a question about the index, not about today's
    trading. The CSV carries no price at all, which is precisely why it
    is a better source than a quote endpoint -- core/nse_quotes.py's
    parse_index_payload() drops any row with no lastPrice, so a stock
    suspended on fetch day used to vanish for a week."""
    csv_text = ("Company Name,Industry,Symbol,Series,ISIN Code\n"
                "Infosys Ltd.,IT,INFY,EQ,INE009A01021\n"
                "Halted Ltd.,IT,HALTED,EQ,INE000000000\n")
    assert symbols_from_csv(csv_text, "SYMBOL") == {"INFY", "HALTED"}


def test_a_wrong_column_name_is_survivable():
    """Better to report nothing and keep the cache than to guess which
    column holds the ticker."""
    assert symbols_from_csv("A,B,C\n1,2,3", "SYMBOL") == set()


def test_junk_payloads_are_survivable():
    assert symbols_from_csv(None) == set()
    assert symbols_from_csv("") == set()
    assert symbols_from_csv("not a csv at all") == set()
    assert symbols_from_csv("Symbol\n\n   \n") == set()


def test_the_retired_endpoints_html_page_yields_nothing():
    """382 bytes of HTML must parse to zero symbols, not to garbage
    tickers -- and refresh() then keeps the previous list."""
    page = ('<!DOCTYPE html> <html lang="en"> <head> '
            '<title>Resource not found</title> </head></html>')
    assert symbols_from_csv(page, "SYMBOL") == set()
