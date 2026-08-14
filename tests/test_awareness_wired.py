"""
==========================================================
Awareness and the shock alert reach the screen
==========================================================

    "place that next to POSITIONS 1/4 3 CLOSED"
    "bot must inform the situation like a caution not block"
                                    -- operator, 3 August 2026

core/awareness.py and core/shock.py were written, tested and wired to
NOTHING for an afternoon. Both had a hundred tests between them and
neither had a caller, so the fifth tile did not exist and no alert
could ever appear. An engine nothing reaches is a file, not a feature.

This file is the wire.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState, _Snapshot


class Store:
    def __init__(self, data):
        self.data = data

    def snapshot(self):
        return self.data


class News:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=25, hours=None):
        return self.rows


def state(**kw):
    st = DashboardState.__new__(DashboardState)
    st.premarket = kw.get("premarket")
    st.market_flows = kw.get("market_flows")
    st.telegram = kw.get("telegram")
    st.index_monitor = kw.get("index_monitor")
    st.news_impact = kw.get("news_impact")
    return st


def movers(n, side="losers", sector="Metal", pct=-1.2):
    rows = [{"symbol": "S%d" % i, "sector": sector, "recent_pct": pct,
             "change_pct": pct * 2} for i in range(n)]
    return {side: rows, "gainers" if side == "losers" else "losers": []}


class Indices:
    def __init__(self, pct):
        self.pct = pct

    def snapshot(self):
        return {"nifty": {"ltp": 24500, "pct": self.pct, "available": True}}


# ---------------------------------------------------------------
# 1. THE PAYLOAD CARRIES BOTH
# ---------------------------------------------------------------
def test_the_snapshot_exposes_awareness_and_shock():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"awareness": self.build_awareness(breadth, gainers_losers),' in src
    assert '"shock": self.build_shock(gainers_losers, open_positions),' in src


def test_awareness_returns_a_reading_with_nothing_wired():
    got = state().build_awareness({"advances": 10, "declines": 5}, {})
    assert got["available"] is True
    assert got["verdict"] in ("Good to trade", "Be careful", "Stay out")
    assert len(got["rows"]) == 5


def test_a_broken_input_does_not_take_the_screen_down():
    class Boom:
        def snapshot(self):
            raise RuntimeError("locked")

    got = state(premarket=Boom()).build_awareness({"advances": 1,
                                                   "declines": 1}, {})
    assert got["available"] is True
    world = next(r for r in got["rows"] if r["key"] == "world")
    assert world["verdict"] == "unknown"


# ---------------------------------------------------------------
# 2. ONE NUMBER, ONE SOURCE
# ---------------------------------------------------------------
def test_the_panel_and_the_ribbon_read_the_same_flow_figure():
    """     The ribbon draws _build_institutional(), which falls through
            NSE -> News Pulse -> config. Awareness first read
            self.market_flows, which is the NSE fetcher ALONE and has
            never returned anything.

    That would have put "FII bought 277" on the line and "no flow
    figure yet" in the panel beneath it, in the same second."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.index("def build_awareness"):src.index("def _recent_headlines")]
    assert "market_flows=_Snapshot(self._build_institutional())" in block
    assert "market_flows=self.market_flows" not in block


def test_the_adapter_just_hands_the_dict_back():
    data = {"available": True, "fii_cr": 277.48}
    assert _Snapshot(data).snapshot() is data
    assert _Snapshot(None).snapshot() == {}


# ---------------------------------------------------------------
# 3. THE SHOCK ALERT
# ---------------------------------------------------------------
def test_a_calm_market_produces_no_alert():
    """     "AN EMPTY LIST IS AN ANSWER"

    A screen that finds a crisis every day finds none on the day there
    is one."""
    got = state(index_monitor=Indices(-0.05),
                news_impact=News([{"headline": "Titan Q1 revenue up 18%"}])
                ).build_shock(movers(20), [])
    assert got == {}


def test_a_war_headline_with_the_tape_behind_it_is_an_alert():
    got = state(index_monitor=Indices(-1.3),
                news_impact=News([{"headline": "Missile strike near the "
                                               "Strait of Hormuz",
                                   "source": "Day Trader Telugu"}])
                ).build_shock(movers(700), [])
    assert got["tier"] == "alert"
    assert got["up"] and got["down"]


class Prices:
    def get_latest_price(self, symbol):
        return 3480.0


def test_his_open_positions_are_carried_into_the_alert():
    """     "During a shock, show them first, with EXIT ready"

    open_positions is a DICT KEYED BY SYMBOL, not a list of rows. I
    wrote the list version from memory and ten existing tests in
    test_dashboard_state.py caught it -- iterating a dict yields the
    keys, so every position arrived as a bare string and the whole
    snapshot raised."""
    st = state(index_monitor=Indices(-1.3),
               news_impact=News([{"headline": "Missile strike near Hormuz"}]))
    st.market_data = Prices()
    got = st.build_shock(movers(700),
                         {"TITAN": {"qty": 28, "entry_price": 3540.0,
                                    "direction": "LONG", "pnl": -2072}})
    assert got["positions"][0]["symbol"] == "TITAN"
    assert got["positions"][0]["qty"] == 28
    # 3540 -> 3480 is a 1.69% loss, computed rather than assumed present.
    assert got["positions"][0]["change_pct"] == pytest.approx(-1.69, abs=0.01)


def test_a_position_shaped_like_a_row_is_also_accepted():
    """build_shock is called directly by tests with plain rows."""
    st = state(index_monitor=Indices(-1.3),
               news_impact=News([{"headline": "Missile strike near Hormuz"}]))
    st.market_data = Prices()
    got = st.build_shock(movers(700),
                         [{"symbol": "CGPOWER", "qty": 140, "pnl": -420}])
    assert got["positions"][0]["symbol"] == "CGPOWER"


def test_the_headlines_come_from_the_channels():
    """     "bot needed live news, events which will get sourced from
             our news channels - Day trader & News Pulse" """
    st = state(news_impact=News([{"headline": "RBI cuts repo rate",
                                  "source": "News Pulse"}]))
    heads = st._recent_headlines()
    assert heads[0]["headline"] == "RBI cuts repo rate"
    assert heads[0]["source"] == "News Pulse"


def test_news_pulse_is_still_banned_for_stock_tagging():
    """It is fine for MARKET-WIDE events, where nothing is attached to a
    company. The tagging ban he set is untouched."""
    from core.stock_events import NO_STOCK_TAGGING
    assert "News Pulse" in NO_STOCK_TAGGING


# ---------------------------------------------------------------
# 4. WHAT REACHES THE GLASS
# ---------------------------------------------------------------
def _html():
    return open("dashboard/static/index.html", encoding="utf-8").read()


def test_the_awareness_tile_sits_beside_his_positions():
    """     "place that next to POSITIONS 1/4 3 CLOSED" """
    src = _html()
    assert "function awarenessTile" in src
    assert "+ awarenessTile(snap);" in src
    assert src.index("<b>POSITIONS</b>") < src.index("+ awarenessTile(snap);")


def test_the_shock_banner_is_at_the_very_top():
    src = _html()
    assert "function shockBanner" in src
    assert "shockBanner(snap)" in src
    # First thing in the strip, above NIFTY.
    strip = src[src.index("host.innerHTML =\n      shockBanner(snap)"):]
    assert strip.index("shockBanner(snap)") < strip.index('idx("NIFTY 50"')


def test_it_makes_a_sound_once_per_event_not_once_per_second():
    """The banner redraws with every snapshot. A siren on a one-second
    timer is its own emergency."""
    src = _html()
    block = src[src.index("function shockBanner"):src.index("function otBeep")]
    assert "OT_SHOCK_SEEN" in block
    assert "key !== OT_SHOCK_SEEN" in block


def test_the_sound_needs_no_file_and_fails_quietly():
    src = _html()
    block = src[src.index("function otBeep"):src.index("function renderTopStrip")]
    assert "AudioContext" in block
    assert "if (!Ctx) return;" in block


def test_the_alert_offers_buttons_and_never_a_block():
    src = _html()
    block = src[src.index("function shockBanner"):src.index("function otBeep")]
    assert "data-buy=" in block and "data-short=" in block
    assert 'data-sell="' in block          # EXIT on each open position
    for banned in ("disabled", "blocked", "cannot trade"):
        assert banned not in block, banned


def test_the_tile_says_a_verdict_he_can_act_on():
    src = _html()
    block = src[src.index("function awarenessTile"):src.index("SOMETHING BIG")]
    assert '"Good to trade"' in block and '"Stay out"' in block
    for word in ("regime", "risk-on", "z-score", "percentile"):
        assert word not in block, word
