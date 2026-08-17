"""
==========================================================
Which names are actually tradeable
==========================================================

    "what you want ? = One weakness I'll repeat rather than bury: ??"
                                    -- operator, 3 August 2026

Nothing, as it turned out. I had said the fan-out's fallback ordering
was alphabetical because the master carries no size column, and that
fixing it needed another input. It did not. data/history_candles.db has
held a volume column on all nineteen million rows the whole time.

That is the same mistake as reporting 2,818 broken tags when the real
answer was 188, and as inventing a security id instead of reading it:
describing a gap without first looking at what is already on disk.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3

import pytest

from core import liquidity, sector_map


@pytest.fixture
def candles(tmp_path):
    """A tiny DAILY store: one huge name, one small one.

    ---- THE SOURCE CHANGED, 4 August 2026 ----
    This used to build a fake data/history_candles.db. That store's
    only writer is tools/fetch_history.py, so in real life it froze on
    31 July and every ADV the bot used was a week old -- while the
    fixture here kept passing, because the fixture was always fresh.

    DailyStore is what tools/build_daily_history.py refreshes nightly
    from NSE's bhavcopy, and it carries the exchange's own TURNOVER
    rather than an estimate from close x volume.
    """
    from core.daily_store import DailyStore
    url = "sqlite:///" + str(tmp_path / "daily.db")
    store = DailyStore(url=url)
    rows = []
    for day in ("2026-07-28", "2026-07-29", "2026-07-30"):
        rows.append({"date": day, "symbol": "BIGONE", "series": "EQ",
                     "open": 100.0, "high": 100.0, "low": 100.0,
                     "close": 100.0, "prev_close": 100.0,
                     "volume": 10_000_000.0, "turnover": 1_000_000_000.0})
        rows.append({"date": day, "symbol": "SMALLONE", "series": "EQ",
                     "open": 100.0, "high": 100.0, "low": 100.0,
                     "close": 100.0, "prev_close": 100.0,
                     "volume": 1000.0, "turnover": 100_000.0})
    store.upsert_many(rows)
    return url


@pytest.fixture(autouse=True)
def clean():
    liquidity.reset()
    sector_map.reset()
    yield
    liquidity.reset()
    sector_map.reset()


def test_it_measures_traded_value_not_share_count(tmp_path, candles):
    """A 30,000 rupee share trading 1,000 times is a bigger name than a
    5 rupee share trading 100,000 times. Volume alone gets that
    backwards."""
    store = str(tmp_path / "liq.json")
    import core.daily_store as ds
    real = ds.DailyStore
    ds.DailyStore = lambda url=None: real(url=candles)
    try:
        assert liquidity.refresh(store_path=store, sessions=3) == 2
    finally:
        ds.DailyStore = real
    assert liquidity.adv("BIGONE", store) > liquidity.adv("SMALLONE", store)


def test_the_numbers_are_per_day_not_a_total(tmp_path, candles):
    store = str(tmp_path / "liq.json")
    import core.daily_store as ds
    real = ds.DailyStore
    ds.DailyStore = lambda url=None: real(url=candles)
    try:
        liquidity.refresh(store_path=store, sessions=3)
    finally:
        ds.DailyStore = real
    # Rs 1,000,000,000 of turnover a day = 100 crore.
    assert liquidity.adv("BIGONE", store) == pytest.approx(100.0, rel=0.01)


def test_an_unknown_symbol_is_zero_not_an_error(tmp_path, candles):
    store = str(tmp_path / "liq.json")
    import core.daily_store as ds
    real = ds.DailyStore
    ds.DailyStore = lambda url=None: real(url=candles)
    try:
        liquidity.refresh(store_path=store, sessions=3)
    finally:
        ds.DailyStore = real
    assert liquidity.adv("NEVERTRADED", store) == 0.0
    assert liquidity.adv(None, store) == 0.0


def test_a_missing_file_is_survivable():
    """Without it the fan-out orders by name, which is what it did
    before this existed. Not an error."""
    assert liquidity.adv("INFY", "data/does_not_exist.json") == 0.0
    assert liquidity.available("data/does_not_exist.json") is False


def test_an_empty_daily_store_does_not_raise(tmp_path):
    import core.daily_store as ds
    real = ds.DailyStore
    ds.DailyStore = lambda url=None: real(url="sqlite:///" + str(tmp_path / "e.db"))
    try:
        assert liquidity.refresh(store_path=str(tmp_path / "l.json")) == 0
    finally:
        ds.DailyStore = real


def test_it_reads_the_store_the_nightly_actually_refreshes():
    """The whole bug in one assertion: measure_liquidity must not read
    a file nothing writes."""
    src = open("core/liquidity.py", encoding="utf-8").read()
    block = src[src.index("def refresh("):src.index("def _load(")]
    # Executable lines only. The docstring EXPLAINS the old store by
    # name, and asserting against prose inside a docstring is a mistake
    # this project has now made five times.
    code, in_doc = [], False
    for line in block.splitlines():
        t = line.strip()
        if t.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or t.startswith("#"):
            continue
        code.append(line)
    code = "\n".join(code)
    assert "DailyStore" in code
    assert "history_candles" not in code


def test_the_biggest_names_come_first(tmp_path, candles):
    store = str(tmp_path / "liq.json")
    import core.daily_store as ds
    real = ds.DailyStore
    ds.DailyStore = lambda url=None: real(url=candles)
    try:
        liquidity.refresh(store_path=store, sessions=3)
    finally:
        ds.DailyStore = real
    liquidity._CACHE = None
    with open(store) as handle:
        table = json.load(handle)["adv_cr"]
    order = sorted(["SMALLONE", "BIGONE"],
                   key=lambda s: (-table.get(s, 0), s))
    assert order[0] == "BIGONE"


def test_the_order_is_stable_between_refreshes(tmp_path, candles):
    """A list that reshuffles under a cursor about to click BUY is a
    hazard of its own. Equal-sized names fall back to alphabetical."""
    store = str(tmp_path / "liq.json")
    names = ["ZED", "ALPHA", "MID"]         # none of them measured
    assert liquidity.by_size(names, store) == ["ALPHA", "MID", "ZED"]


# ---------------------------------------------------------------
# Against the real store
# ---------------------------------------------------------------
REAL = os.path.exists(liquidity.STORE_PATH)


@pytest.mark.skipif(not REAL, reason="run py tools/measure_liquidity.py")
def test_the_real_file_puts_the_liquid_names_at_the_top():
    """     Before this, the first seconds of a shock offered 63MOONS
            and AFFLE for IT because nothing had ticked yet."""
    sector_map.reset()
    it = liquidity.by_size(sector_map.members("IT"))

    # ---- IT ASSERTED AN ORDER, NOT THE POINT. 4 August 2026. ----
    #
    # This was `it[:2] == ["INFY", "TCS"]` and went red the night
    # measure_liquidity ran with fresh bars: REDINGTON did Rs 1,148
    # crore a day against TCS's Rs 1,082 -- six percent apart, and
    # REDINGTON had just traded up 8.3% on heavy volume. The data was
    # right; the assertion was on a coin-flip.
    #
    # What this test is FOR is that a shock does not offer 63MOONS or
    # AFFLE for IT because nothing has ticked yet. That is a question
    # about magnitude, not about which of two Rs 1,000-crore names is
    # ahead on the day.
    # ---- AND IT DID IT AGAIN. 17 August 2026. ----
    #
    # measure_liquidity ran with fresh bars and TECHM came fourth at
    # Rs 459 crore -- under a flat Rs 500 line, so red. The comment
    # above had already diagnosed this exact shape and the fix put an
    # absolute number back in, which is the same coin flip one place
    # to the left.
    #
    # Measured rather than guessed: the thin names this test exists to
    # keep out do Rs 29 (AFFLE) and Rs 34 crore (63MOONS). TECHM at
    # Rs 459 is SIXTEEN TIMES either of them. The question is
    # magnitude, so the assertion is now magnitude -- relative to the
    # very names it names, and no fresh bar can move that by 16x.
    top = it[:4]
    thin = max(liquidity.adv("AFFLE") or 0.0,
               liquidity.adv("63MOONS") or 0.0)
    assert thin > 0, "the thin benchmarks have no liquidity reading"
    assert all((liquidity.adv(name) or 0.0) > thin * 3 for name in top), \
        [(name, liquidity.adv(name), f"thin={thin:.0f}") for name in top]
    assert "INFY" in top, top
    # And the thin names it used to OFFER are not at the front. The
    # failure this guards was them being handed to him first; where
    # exactly they land after that is not the bot's problem.
    for thin in ("63MOONS", "AFFLE"):
        assert thin not in top, (thin, top)
    assert liquidity.adv("INFY") > liquidity.adv("63MOONS")


@pytest.mark.skipif(not REAL, reason="run py tools/measure_liquidity.py")
def test_the_fan_out_uses_it():
    from core.shock import assess
    movers = [{"symbol": "ZZ%d" % i, "sector": "Metal", "recent_pct": -1.1,
               "change_pct": -2.0} for i in range(700)]
    got = assess(headlines=[{"headline": "Missile strike near Hormuz"}],
                 movers=movers, index_pct=-1.2)
    shown = [r["symbol"] for r in got["up"]]
    assert "INFY" in shown and "TCS" in shown
    assert "63MOONS" not in shown


def test_it_is_in_the_nightly_run():
    """It takes seconds over the whole store, so it belongs after the
    close and nowhere near a one-second dashboard refresh."""
    from tools.nightly import STEPS
    joined = " ".join(" ".join(step[2]) for step in STEPS)
    assert "measure_liquidity" in joined


def test_nothing_measures_liquidity_inside_main():
    main = open("main.py", encoding="utf-8").read()
    assert "liquidity.refresh" not in main
    assert "measure_liquidity" not in main
