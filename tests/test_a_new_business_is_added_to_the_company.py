"""---- A COMPANY THAT ENTERS A BUSINESS CARRIES IT. 15 September 2026. ----

    "add newly entering sectors to the stocks like = ULTRATECH cement add
     wires, cables business along with cement; RAYMOND = Textile, now
     DEFENCE adding into raymond"                   -- the operator

The detector over 14,745 stored events found ~50 "entries"; about four
were real. These tests pin the real ones in and the false shapes out.
"""

import csv
import shutil

import pytest

from core import sector_impact as si


REAL = [
    ("ULTRACEMCO", "ULTRATECH CEMENT: CO. COMMENCES COMMERCIAL PRODUCTION OF "
                   "11 LAKH KM WIRES & CABLES PLANT AT BHARUCH"),
    ("VOLTAS", "VOLTAS: CO TO FORM 50:50 JV WITH ATOMBERG TO MANUFACTURE ~2.8 "
               "MILLION AC COMPRESSORS ANNUALLY IN INDIA"),
]
FALSE = [
    # hedged
    ("RELIANCE", "RELIANCE MULLS FORAY INTO ALUMINIUM INDUSTRY: MINT"),
    # a place, not a business; and ELECTRONICS is its own name
    ("EMIL", "ELECTRONICS MART: CO EXPANDS INTO EASTERN INDIA; SCALES PREMIUM "
             "LIFESTYLE FORMATS"),
    # the business named is the one it is leaving behind
    ("SWIGGY", "SWIGGY: CO'S CREW ENTERS TRAVEL SEGMENT, EXPANDING ITS "
               "CONCIERGE SERVICES BEYOND FOOD AND QUICK COMMERCE"),
    # a results card is not an announcement
    ("GODREJIND", "#GODREJIND - Weak Results - Diversified | Diversified "
                  "Pulse Rating : Weak"),
]


@pytest.fixture(autouse=True)
def _before_they_were_learned(monkeypatch):
    """ULTRACEMCO and VOLTAS carry these businesses in the live master
    since 15 Sep, which makes them (correctly) no longer entrants. The
    detector is tested against the state before that."""
    real = si.business_tags

    def before():
        drop = {"WIRES": "ULTRACEMCO", "CABLES": "ULTRACEMCO",
                "COMPRESSORS": "VOLTAS"}
        return {t: (frozenset(s - {drop[t]}) if t in drop else s)
                for t, s in real().items()}
    monkeypatch.setattr(si, "business_tags", before)


@pytest.mark.parametrize("symbol,headline", REAL)
def test_a_real_entry_is_confirmed(symbol, headline):
    assert si.confirmed_entry(symbol, headline), headline


@pytest.mark.parametrize("symbol,headline", FALSE)
def test_a_false_entry_is_not(symbol, headline):
    assert si.confirmed_entry(symbol, headline) == [], headline


def test_adding_touches_only_themes_and_never_removes(tmp_path, monkeypatch):
    path = tmp_path / "master.csv"
    shutil.copy("data/master_stocks.csv", path)
    before = {r["SYMBOL"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}
    monkeypatch.setattr(si, "reset", lambda: None)
    added = si.add_businesses("ULTRACEMCO", ["WIRES", "CABLES", "CEMENT"],
                              path=str(path))
    after = {r["SYMBOL"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}
    assert "CEMENT" not in added, "a business it already carries is not added twice"
    old, new = before["ULTRACEMCO"], after["ULTRACEMCO"]
    for column in old:
        if column != "THEMES":
            assert old[column] == new[column], column
    for tag in [t.strip() for t in old["THEMES"].split("|") if t.strip()]:
        assert tag in new["THEMES"], "a business was removed"
    assert len(before) == len(after)


def test_the_business_goes_to_themes_not_keywords():
    """KEYWORDS is the company's identity in core/news_impact.py --
    DEFENCE there would file every defence headline as Raymond's news."""
    import pathlib
    src = pathlib.Path("core/sector_impact.py").read_text(encoding="utf-8")
    body = src.split("def add_businesses")[1].split("\ndef ")[0]
    assert 'row["THEMES"]' in body
    assert "KEYWORDS" not in body.split('"""', 2)[2]


def test_it_runs_every_close():
    import pathlib
    src = pathlib.Path("tools/nightly.py").read_text(encoding="utf-8")
    assert '"tools/record_sector_impact.py"' in src
    assert src.index('("businesses"') < src.index('("universe"')
