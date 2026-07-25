"""
Decision-correctness tests for NSE/BSE exchange announcement
fetching (news_bot/exchange_announcements.py).

No real network calls -- the `nse.NSE` and `bse.BSE` classes
are monkeypatched with fakes built from the REAL sample row
shapes published in each package's own GitHub repo (see the
module docstring for the source URLs), not invented data.
"""

import news_bot.exchange_announcements as ea


# --------------------------------------------------
# NSE
# --------------------------------------------------

_NSE_SAMPLE_ROW = {
    "symbol": "IDEA",
    "desc": "Updates",
    "dt": "18102023221142",
    "attchmntFile": "https://nsearchives.nseindia.com/corporate/IDEA_x.pdf",
    "sm_name": "Vodafone Idea Limited",
    "sm_isin": "INE669E01016",
    "an_dt": "18-Oct-2023 22:11:42",
    "sort_date": "2023-10-18 22:11:42",
    "seq_id": "105647960",
    "smIndustry": "Telecommunication - Services",
    "attchmntText": (
        "Vodafone Idea Limited has informed the Exchange regarding "
        "'Intimation under Regulation 30 of the SEBI (LODR)Reg, 2015'."
    ),
}


class _FakeNSEClient:
    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows if rows is not None else [_NSE_SAMPLE_ROW]
        self._raise_exc = raise_exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def announcements(self, index=None, from_date=None, to_date=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._rows


def test_fetch_nse_announcements_sets_known_symbol(monkeypatch):
    import nse

    monkeypatch.setattr(nse, "NSE", lambda **kwargs: _FakeNSEClient())

    items = ea.fetch_nse_announcements(lookback_days=1)

    assert len(items) == 1
    item = items[0]
    assert item.source == "NSE_ANNOUNCEMENTS"
    assert item.known_symbol == "IDEA"
    assert "Vodafone Idea" in item.title
    assert item.guid == "105647960"


def test_fetch_nse_announcements_raises_on_client_failure(monkeypatch):
    import nse

    monkeypatch.setattr(
        nse, "NSE", lambda **kwargs: _FakeNSEClient(raise_exc=ConnectionError("down"))
    )

    try:
        ea.fetch_nse_announcements()
        assert False, "expected ExchangeFetchError"
    except ea.ExchangeFetchError:
        pass


def test_fetch_nse_announcements_skips_rows_with_no_usable_text(monkeypatch):
    import nse

    bad_row = dict(_NSE_SAMPLE_ROW)
    bad_row["attchmntText"] = ""
    bad_row["sm_name"] = ""
    bad_row["desc"] = ""
    bad_row["symbol"] = ""

    monkeypatch.setattr(nse, "NSE", lambda **kwargs: _FakeNSEClient(rows=[bad_row]))

    items = ea.fetch_nse_announcements()
    assert items == []


# --------------------------------------------------
# BSE
# --------------------------------------------------

_BSE_SAMPLE_ROW_MATERIAL = {
    "NEWSID": "abc-123",
    "SCRIP_CD": 500325,
    "HEADLINE": "Reliance Industries announces Board Meeting for Q1 results",
    "MORE": "Board to consider financial results",
    "CATEGORYNAME": "Board Meeting",
    "SUBCATNAME": "Board Meeting",
    "CRITICALNEWS": 1,
    "News_submission_dt": "2023-10-20T23:44:22",
    "NSURL": "https://www.bseindia.com/x",
    "SLONGNAME": "Reliance Industries Ltd",
}

_BSE_SAMPLE_ROW_IGNORED = {
    "NEWSID": "def-456",
    "SCRIP_CD": 517397,
    "HEADLINE": "Newspaper publication of some routine notice",
    "MORE": "",
    "CATEGORYNAME": None,
    "SUBCATNAME": "Newspaper Publication",
    "CRITICALNEWS": 0,
    "News_submission_dt": "2023-10-20T23:44:22",
    "NSURL": "https://www.bseindia.com/y",
    "SLONGNAME": "Pan Electronics India Ltd",
}


class _FakeBSEClient:
    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows if rows is not None else []
        self._raise_exc = raise_exc
        self.exited = False

    def announcements(self, page_no=1):
        if self._raise_exc:
            raise self._raise_exc
        return {"Table": self._rows, "Table1": [{"ROWCNT": len(self._rows)}]}

    def exit(self):
        self.exited = True


def test_fetch_bse_announcements_keeps_material_rows_and_drops_ignored(monkeypatch):
    import bse

    fake_client = _FakeBSEClient(
        rows=[_BSE_SAMPLE_ROW_MATERIAL, _BSE_SAMPLE_ROW_IGNORED]
    )
    monkeypatch.setattr(bse, "BSE", lambda **kwargs: fake_client)

    items = ea.fetch_bse_announcements(page_no=1)

    assert len(items) == 1
    assert items[0].source == "BSE_ANNOUNCEMENTS"
    assert "Reliance Industries" in items[0].title
    assert items[0].known_symbol == ""  # BSE never sets this -- see module docstring
    assert fake_client.exited is True


def test_fetch_bse_announcements_raises_on_client_failure(monkeypatch):
    import bse

    fake_client = _FakeBSEClient(raise_exc=ConnectionError("down"))
    monkeypatch.setattr(bse, "BSE", lambda **kwargs: fake_client)

    try:
        ea.fetch_bse_announcements()
        assert False, "expected ExchangeFetchError"
    except ea.ExchangeFetchError:
        pass

    # Even on failure, the client's session must still be closed.
    assert fake_client.exited is True


def test_fetch_bse_announcements_raises_on_missing_package(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "bse":
            raise ImportError("no module named bse")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    try:
        ea.fetch_bse_announcements()
        assert False, "expected ExchangeFetchError"
    except ea.ExchangeFetchError:
        pass
