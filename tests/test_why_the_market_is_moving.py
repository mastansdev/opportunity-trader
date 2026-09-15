"""---- WHY THE WHOLE MARKET IS MOVING. 15 September 2026. ----

    "as of now market is in sell mode. lets see . does bot knows any
     specific reason triggered all markets are falling ?"  -- the operator

The stories were on disk that morning; nothing asked them about the
market. core/market_cause.py groups them by driver next to what NIFTY and
the sectors are doing. Display only -- it never changes a trade.
"""

from datetime import datetime, timezone

from core import market_cause as mc

NOW = datetime(2026, 9, 15, 7, 30, tzinfo=timezone.utc)      # 13:00 IST

# Real headlines stored on 15 Sep (stock_events, scope MARKET).
STORIES = [
    {"at": "2026-09-15T04:09:00+00:00", "headline":
     "The Indian Rupee weakened by 20 paise against the US Dollar on "
     "September 15, driven by rising crude oil prices and anticipation of "
     "a US Fed rate hike"},
    {"at": "2026-09-15T06:52:00+00:00", "headline":
     "Raamdeo Agrawal stated that rising global bond yields pose a greater "
     "concern than crude oil prices."},
    {"at": "2026-09-15T06:57:00+00:00", "headline":
     "The Federal Reserve's upcoming rate decision is under scrutiny amid a "
     "global bond market selloff, persistent inflation, and rising oil prices"},
    {"at": "2026-09-15T06:58:00+00:00", "headline":
     "The Federal Reserve's upcoming rate decision is under scrutiny amid a "
     "global bond market selloff, persistent inflation, and rising oil prices"},
    {"at": "2026-09-15T05:48:00+00:00", "headline":
     "August passenger vehicle sales rose 37% year-over-year to 4.39 lakh units"},
    {"at": "2026-09-14T09:00:00+00:00", "headline":
     "Crude oil falls 4% overnight"},                       # yesterday
]

INDICES = {"nifty": {"pct": -0.9}, "banknifty": {"pct": -1.1},
           "vix": {"pct": 6.2}}
SECTORS = [{"avg_change_pct": -1.2}, {"avg_change_pct": -0.4},
           {"avg_change_pct": 0.3}, {"avg_change_pct": -2.0}]


def test_a_falling_market_is_named_with_its_drivers():
    got = mc.explain(INDICES, SECTORS, None, STORIES, now=NOW)
    assert got["direction"] == "FALLING"
    names = [d["driver"] for d in got["drivers"]]
    assert "Crude oil" in names
    assert "US Fed / US rates" in names or "Bond yields" in names
    assert "NIFTY -0.90%" in got["facts"]
    assert "3 sectors down, 1 up" in got["facts"]


def test_the_same_story_from_two_channels_counts_once():
    got = mc.drivers(STORIES, now=NOW, direction="FALLING", top=10)
    fed = next(d for d in got if d["driver"] == "US Fed / US rates")
    assert fed["stories"] == 2       # rupee story + one copy of the Fed story


def test_an_old_story_is_not_todays_reason():
    got = mc.drivers([STORIES[-1]], now=NOW)
    assert got == []


def test_no_story_says_so_honestly():
    got = mc.explain(INDICES, SECTORS, None, [], now=NOW)
    assert "does not know why" in got["sentence"]


def test_nifty_and_sectors_disagreeing_is_mixed():
    got = mc.market_now({"nifty": {"pct": 0.2}},
                        [{"avg_change_pct": -1}, {"avg_change_pct": -1}])
    assert got["direction"] == "MIXED"


def test_fii_is_labelled_end_of_day():
    got = mc.explain(INDICES, SECTORS,
                     {"available": True, "fii_cr": -2300.0, "dii_cr": 1800.0,
                      "as_of": "14-Sep-2026"}, STORIES, now=NOW)
    assert any("FII -2,300 cr" in f and "end of day" in f for f in got["facts"])


def test_it_never_raises():
    assert mc.explain({"nifty": "junk"}, [None], "junk", [None, {}], now=NOW)
