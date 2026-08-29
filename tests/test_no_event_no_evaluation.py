"""A stock with no event is not walked through nine gates.

    "the problem is for non events / no volume stocks are being
     processed continously ? does the bot goona trade on 1500 trades
     each day?"
    "if 100 stocks were there at morning & by 11 5 stocks got news .
     then bot must include those stocks too & check for the
     opportunity like volume , our entry rules & so on until 15:15"
                                    -- operator, 29 August 2026

24 August, one session: 355,089 refusals recorded to reach three
decisions. The largest single reason, 164,988 of them, was "no event
behind it" -- the same reasonless stocks re-refused on every one of
~1,400 cycles. 31,924 more were "under the Rs 50 floor", a permanent
property of a stock rediscovered twenty-five times a day.

REQUIRE_A_REASON_ALWAYS means such a stock can never be taken. Walking
it to that conclusion is work whose answer is known before it starts.
"""

from datetime import datetime

from core.ranker import rank

NOW = datetime(2026, 8, 26, 11, 0)


def _mover(symbol, change=6.0, price=500.0):
    return {"symbol": symbol, "change_pct": change, "ltp": price,
            "day_open": price * 0.97, "volume": 4_000_000,
            "sector": "CHEMICALS"}


def _reason(text="Bags Rs 500 crore order from NHAI"):
    return {"text": text, "weight": 0.9, "direction": "POSITIVE",
            "source": "NSE filing"}


def test_a_stock_with_no_event_is_not_evaluated():
    got = rank([_mover("NOEVENT")], mechanism_of=lambda s: None,
               adv_of=lambda s: 50.0, now=NOW)
    assert got["rows"] == []
    assert got["refusals"].get("no event -- not evaluated") == 1
    # One aggregate line, NOT one refusal per gate.
    assert "not moving enough" not in got["refusals"]
    assert "no volume behind it" not in got["refusals"]


def test_the_symbol_is_still_remembered():
    """"Why was X not named?" must keep an answer. The ranker used to
    count reasons and forget the stock."""
    got = rank([_mover("NOEVENT")], mechanism_of=lambda s: None,
               adv_of=lambda s: 50.0, now=NOW)
    assert "NOEVENT" in (got.get("refused_by_symbol") or {})


def test_a_stock_WITH_an_event_is_evaluated_fully():
    got = rank([_mover("HASEVENT")], mechanism_of=lambda s: _reason(),
               adv_of=lambda s: 50.0, now=NOW)
    assert [r["symbol"] for r in got["rows"]] == ["HASEVENT"]


def test_news_at_eleven_puts_a_stock_INTO_the_set():
    """His 100-at-the-open plus 5-at-eleven. Membership is decided by
    the reason lookup on every call, so a stock that had nothing at
    09:30 is evaluated from the moment its news lands."""
    movers = [_mover("QUIET"), _mover("LATER")]
    at_open = rank(movers, mechanism_of=lambda s: None,
                   adv_of=lambda s: 50.0, now=NOW)
    assert at_open["rows"] == []

    # 11:00 -- LATER gets news, QUIET still has nothing.
    at_eleven = rank(movers,
                     mechanism_of=lambda s: _reason() if s == "LATER" else None,
                     adv_of=lambda s: 50.0, now=NOW)
    assert [r["symbol"] for r in at_eleven["rows"]] == ["LATER"]
    assert at_eleven["refusals"].get("no event -- not evaluated") == 1


def test_the_market_context_still_sees_every_mover():
    """Sector strength and breadth need the FULL list, including the
    stocks that are not candidates. Filtering candidates must not
    quietly narrow the market view."""
    movers = [_mover(f"S{i}", change=5.0) for i in range(6)]
    movers.append(_mover("REAL", change=8.0))
    got = rank(movers,
               mechanism_of=lambda s: _reason() if s == "REAL" else None,
               adv_of=lambda s: 50.0, now=NOW)
    assert [r["symbol"] for r in got["rows"]] == ["REAL"]
    # market_pct is computed before the filter, from all seven.
    assert got["market_pct"] is not None


def test_the_reason_lookup_runs_once_per_symbol():
    """It is asked to decide membership and again inside the loop.
    Twice per cycle across ~130 stocks is fine; twice per GATE is not."""
    calls = []

    def counting(symbol):
        calls.append(symbol)
        return _reason()

    rank([_mover("ONE"), _mover("TWO")], mechanism_of=counting,
         adv_of=lambda s: 50.0, now=NOW)
    assert calls.count("ONE") == 1, calls
    assert calls.count("TWO") == 1, calls
