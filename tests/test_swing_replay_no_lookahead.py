"""
The swing backtest must never see a price from outside its window.

2026-07-27: it did. run()'s end-of-window force-close used
s["closes"][-1] -- the last close of the symbol's whole history
(2026-07-24) -- instead of the last close inside the window being
replayed. A --train run ending 2021-12-31 sold every still-open
position at its 2026 price, and printed BSE as 212.88 -> 3,549.70 in
20 days.

It was not caught by any summary statistic. It was caught by the
operator asking to see the individual trades. These tests exist so it
cannot come back silently.
"""

import backtest.swing_replay as sr


def _series(sym, prices, start_index=0):
    """Builds the indicator dict run() expects, with straight-line
    prices so every number below is checkable by hand."""
    dates = [f"2020-01-{i+1:02d}" for i in range(start_index,
                                                 start_index + len(prices))]
    n = len(prices)
    return {
        "dates": dates,
        "opens": list(prices),
        "highs": [p * 1.001 for p in prices],
        "lows": [p * 0.999 for p in prices],
        "closes": list(prices),
        "atr": [1.0] * n,
        # Deliberately BELOW every close, so the entry test
        # (close > prior N-day high AND close > trend MA) actually
        # fires. With these as None the candidate loop skips the
        # symbol entirely and the whole test passes without ever
        # opening a position -- which is how the first version of
        # this file was green while proving nothing.
        "hi_prev": [min(prices) - 5.0] * n,
        "ma": [min(prices) - 10.0] * n,
        "adv": [1e12] * n,
        "idx": {d: i for i, d in enumerate(dates)},
    }


def _params(**over):
    p = dict(capital=10_00_000, risk_pct=0.01, stop_atr=2.5, trail_atr=5.0,
             max_positions=5, max_leverage=4.0, mtf_rate=0.0,
             min_price=0.0, min_adv=0.0)
    p.update(over)
    return p


def test_end_of_window_exit_never_uses_a_price_after_the_window():
    """The exact bug. A symbol whose price EXPLODES after the window
    must be closed at the in-window price, not the later one."""
    # flat at 100 through the window, then rockets to 5000 afterwards
    prices = [100.0] * 12 + [5000.0] * 5
    ind = {"X": _series("X", prices)}
    # replay ONLY the flat part
    window = ind["X"]["dates"][:12]

    # force a position open by hand at the first date
    p = _params()
    trades, _ = sr.run(ind, window, p)

    assert trades, "no position ever opened -- this test proves nothing"
    for t in trades:
        assert t["exit"] < 200.0, (
            f"exit price {t['exit']} came from outside the window -- "
            f"the window never traded above ~100"
        )


def test_no_trade_carries_an_exit_date_beyond_the_window():
    prices = [100.0 + i for i in range(20)]
    ind = {"X": _series("X", prices)}
    window = ind["X"]["dates"][:10]
    trades, _ = sr.run(ind, window, _params())
    assert trades, "no position ever opened -- this test proves nothing"
    for t in trades:
        assert t["exit_date"] <= window[-1]
        assert t["entry_date"] <= window[-1]


def test_a_symbol_with_no_bar_on_the_final_day_walks_BACKWARD():
    """Illiquid name with no print on the last session must be valued
    from an EARLIER in-window bar, never a later out-of-window one."""
    prices = [100.0] * 8 + [9999.0] * 4
    s = _series("X", prices)
    # delete the final in-window bar so the fallback path runs
    missing = s["dates"][7]
    del s["idx"][missing]
    ind = {"X": s}
    window = s["dates"][:8]
    trades, _ = sr.run(ind, window, _params())
    assert trades, "no position ever opened -- this test proves nothing"
    for t in trades:
        assert t["exit"] < 200.0
