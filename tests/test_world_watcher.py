"""
==========================================================
The overnight numbers stop being overnight numbers
==========================================================

    "bot need to monitor continuously the news, events, global risks =
     bond yields, currency, commodities"
    "Market Situational Awareness is the ability to understand the
     complete market environment before making any trading decision &
     during open position"
                                    -- operator, 3 August 2026

main.py builds PreMarket(fetcher=None): it reads what the 08:45 job
wrote and never fetches again. Crude, gold, the dollar and both US
yields were frozen from before the open, so at 14:00 the awareness tile
was reporting a morning snapshot as though it were current. The
"during open position" half of his definition was not covered at all.

The refresh lives in the COLLECTOR, never in main.py.

    "PLS DO NOT COMBINE MAIN.PY"

Eighteen HTTP calls to a third party on a timer do not belong in the
process that places orders -- the same reason the channels moved out.

Author : H&M Opportunity Trader
==========================================================
"""

import tools.collector as collector


def _source():
    return open("tools/collector.py", encoding="utf-8").read()


def test_the_collector_refreshes_the_world_feed():
    assert hasattr(collector, "world_watcher")
    assert isinstance(collector.WORLD_REFRESH_MINUTES, int)
    assert 1 <= collector.WORLD_REFRESH_MINUTES <= 30


def test_it_runs_in_its_own_thread():
    """A refresh takes tens of seconds with the throttle spacing. On the
    main loop it would hold up a Telegram poll, and the channels are
    the faster-moving half of the job."""
    src = _source()
    assert 'threading.Thread(target=world_watcher' in src
    assert "daemon=True" in src


def test_main_py_never_fetches_the_world_itself():
    """     "PLS DO NOT COMBINE MAIN.PY"

    main.py may READ data/premarket.json. It may not reach over the
    internet for it."""
    main = open("main.py", encoding="utf-8").read()
    assert "PreMarket(fetcher=None)" in main
    # main.py does import core.nse_quotes.requests_fetcher, which is a
    # different function for a different feed. What must never appear
    # is the WORLD fetcher reaching Yahoo from inside the trading loop.
    assert "PreMarket(fetcher=requests_fetcher" not in main
    assert "from core.premarket import PreMarket, requests_fetcher" not in main


def test_a_failed_refresh_is_loud_but_not_fatal():
    """A total failure was previously invisible: the file kept an old
    number and a fresh-looking timestamp. It has to be said out loud
    and it must not stop the collector."""
    src = _source()
    block = src[src.index("def world_watcher"):src.index("def _sleep")]
    assert "Refresh collected nothing" in block
    assert "except Exception" in block
    assert "sys.exit" not in block


def test_a_single_pass_run_does_not_start_it():
    """--once is for checking the plumbing. Starting a ten-minute
    background loop inside a one-shot run leaves a thread behind."""
    src = _source()
    assert "if not once:" in src
    assert src.index("if not once:") < src.index("threading.Thread(target=world_watcher")


def test_the_watcher_survives_a_broken_import(monkeypatch):
    """A missing requests library must degrade to 'the morning numbers
    stand', never to a crash that takes the channels down with it."""
    import builtins
    real = builtins.__import__

    def boom(name, *args, **kwargs):
        if name == "core.premarket":
            raise ImportError("no requests")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", boom)
    collector.world_watcher(minutes=0)          # returns, does not raise


def test_it_stops_when_the_collector_is_asked_to_stop(monkeypatch):
    calls = {"n": 0}

    class Store:
        def refresh(self):
            calls["n"] += 1
            collector._STOP["now"] = True
            return 18

    monkeypatch.setattr(collector, "_STOP", {"now": False})

    import core.premarket as premarket
    monkeypatch.setattr(premarket, "PreMarket", lambda **kw: Store())
    monkeypatch.setattr(premarket, "requests_fetcher", lambda: None)

    collector.world_watcher(minutes=0)
    assert calls["n"] == 1
