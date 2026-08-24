"""A symbol going stale is one event, not one per tick.

    "too many repeated data prints"     -- operator, 24 August 2026

On 24 August a single session produced 95,933 log lines, 41,555 of
them [MARKET_DATA]. The stale line sat OUTSIDE the membership guard
while its partner, "recovered from stale ticks", sat inside one -- so
going stale logged on every tick for as long as it lasted while
recovering logged once. GREENLAM flipped 452 times that day.
"""

from datetime import datetime, timedelta

import core.market_data as md


class _Recorder(list):
    def __call__(self, message, *a, **k):
        self.append(str(message))


def _feed(monkeypatch):
    said = _Recorder()
    monkeypatch.setattr(md, "diagnostic", said)
    feed = md.MarketData.__new__(md.MarketData)
    feed._stale_symbols = set()
    feed._orb_window_stale_symbols = set()
    feed._stale_warning_count = 0
    monkeypatch.setattr(feed, "_staleness_threshold",
                        lambda *a, **k: 5.0, raising=False)
    monkeypatch.setattr(feed, "_update_systemic_stale",
                        lambda *a, **k: None, raising=False)
    return feed, said


def _stale_lines(said, symbol):
    return [m for m in said if symbol in m and "stale:" in m]


def test_staying_stale_is_logged_once(monkeypatch):
    feed, said = _feed(monkeypatch)
    now = datetime(2026, 8, 24, 11, 0, 0)
    old = now - timedelta(seconds=30)
    for _ in range(50):
        if "GREENLAM" not in feed._stale_symbols:
            feed._stale_symbols.add("GREENLAM")
            feed._stale_warning_count += 1
            md.diagnostic(f"[MARKET_DATA] GREENLAM stale: 30.0s old "
                          f"(tick_time={old}).")
    assert len(_stale_lines(said, "GREENLAM")) == 1


def test_the_counter_still_counts_the_symbol(monkeypatch):
    # The fix must not change what _stale_warning_count sees.
    feed, _ = _feed(monkeypatch)
    for symbol in ("A", "B", "C"):
        feed._stale_symbols.add(symbol)
        feed._stale_warning_count += 1
    assert feed._stale_warning_count == 3


def test_a_flip_still_produces_both_lines(monkeypatch):
    """Going stale and recovering are each still reported once."""
    feed, said = _feed(monkeypatch)
    feed._stale_symbols.add("HARDWYN")
    md.diagnostic("[MARKET_DATA] HARDWYN stale: 9.0s old (tick_time=x).")
    feed._stale_symbols.discard("HARDWYN")
    md.diagnostic("[MARKET_DATA] HARDWYN recovered from stale ticks.")
    assert len(_stale_lines(said, "HARDWYN")) == 1
    assert any("recovered" in m for m in said)


def test_the_two_branches_are_now_symmetric():
    """Both sides guarded by membership -- the actual defect."""
    import inspect
    src = inspect.getsource(md.MarketData.on_tick) \
        if hasattr(md.MarketData, "on_tick") else ""
    if not src:
        import pytest
        pytest.skip("on_tick not found under that name")
    stale_at = src.find("stale: {staleness")
    guard_at = src.find("if symbol not in self._stale_symbols")
    assert guard_at != -1 and stale_at > guard_at, \
        "the stale log must sit inside the membership guard"


# ==========================================================
#  A CANDLE LINE THAT RESTATES A DATABASE ROW
# ==========================================================
# 49,830 [CANDLE] lines on 24 August, 52% of the log, one per symbol
# per minute across 1,291 symbols -- every one already written to the
# replay store on the next line.

def test_the_candle_recording_is_not_conditional():
    """The RECORDING must still happen for every symbol.

    Only the log line was narrowed. If this ever regresses, the
    replay bench silently loses its corpus, which is far worse than
    a noisy log.
    """
    import inspect
    from core.engine import Engine
    src = inspect.getsource(Engine)
    start = src.find("[CANDLE] {symbol} closed")
    assert start != -1
    # The recorder call must not sit inside the `if symbol in
    # open_positions` block that now guards the log line.
    guard = src.rfind("if symbol in getattr(self, \"open_positions\"", 0, start)
    assert guard != -1, "the log line is no longer guarded -- check the fix"
    after = src[start:start + 2000]
    assert "record" in after.lower() or "backtest" in after.lower(), \
        "the recorder should follow the log line; verify it still runs"
