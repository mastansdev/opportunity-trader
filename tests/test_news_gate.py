"""
Decision-correctness tests for NewsGate -- the thin, advisory-
only reader Engine consults. Proves it never crashes on a
missing symbol and formats what it finds.
"""

from core.news_gate import NewsGate


class _FakeReader:
    def __init__(self, data=None):
        self.data = data or {}
        self.refreshed = False

    def refresh(self):
        self.refreshed = True

    def high_priority_for(self, symbol):
        return self.data.get(symbol, [])

    def all_symbols_today(self):
        return {s: items[-1] for s, items in self.data.items() if items}


def test_describe_returns_none_when_no_high_priority_news():
    gate = NewsGate(reader=_FakeReader())
    assert gate.describe("TCS") is None


def test_describe_formats_the_latest_item():
    reader = _FakeReader({
        "TCS": [
            {"direction": "bullish", "confidence": 80, "reason": "Older item."},
            {"direction": "bearish", "confidence": 90, "reason": "Newer item."},
        ]
    })
    gate = NewsGate(reader=reader)

    description = gate.describe("TCS")

    assert description == "bearish (90%) -- Newer item."


def test_refresh_delegates_to_the_reader():
    reader = _FakeReader()
    gate = NewsGate(reader=reader)
    gate.refresh()
    assert reader.refreshed is True


def test_all_news_stocks_delegates_to_the_reader():
    reader = _FakeReader({
        "TCS": [{"direction": "bullish", "confidence": 80, "reason": "x"}],
    })
    gate = NewsGate(reader=reader)

    assert gate.all_news_stocks() == {
        "TCS": {"direction": "bullish", "confidence": 80, "reason": "x"}
    }


def test_latest_high_priority_returns_none_when_nothing_for_the_symbol():
    gate = NewsGate(reader=_FakeReader())
    assert gate.latest_high_priority("TCS") is None


def test_latest_high_priority_returns_the_raw_latest_item():
    reader = _FakeReader({
        "TCS": [
            {"direction": "bullish", "confidence": 80, "reason": "Older item."},
            {"direction": "bearish", "confidence": 90, "reason": "Newer item."},
        ]
    })
    gate = NewsGate(reader=reader)

    item = gate.latest_high_priority("TCS")

    assert item == {"direction": "bearish", "confidence": 90, "reason": "Newer item."}
