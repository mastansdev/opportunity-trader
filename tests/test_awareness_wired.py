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
# ---------------------------------------------------------------
# 2. ONE NUMBER, ONE SOURCE
# ---------------------------------------------------------------
def test_the_adapter_just_hands_the_dict_back():
    data = {"available": True, "fii_cr": 277.48}
    assert _Snapshot(data).snapshot() is data
    assert _Snapshot(None).snapshot() == {}


# ---------------------------------------------------------------
# 3. THE SHOCK ALERT
# ---------------------------------------------------------------
class Prices:
    def get_latest_price(self, symbol):
        return 3480.0


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


