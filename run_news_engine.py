"""
==========================================================
Opportunity Trader -- Standalone 24/7 News Engine
==========================================================

Runs the News Bot pipeline FOREVER, on its own, independent of
the trading bot, the Dhan feed, the dashboard, and market hours.
This is the process you run on Railway (or locally in its own
window) so news is captured 24/7 -- overnight, weekends, holidays
-- and is already waiting in the store when the market opens.

It touches NO broker API and needs NO market data. Its only job:

    every POLL_INTERVAL_SECONDS:
        fetch RSS + NSE/BSE announcements
        match against the 750-stock universe (drop DUMMY)
        classify (free keyword now, paid Haiku when configured)
        tier (HIGH / MID)
        store, deduped, in the shared database (news_store.py)

The trading bot (main.py) and the dashboard just READ that same
store. See news_bot/news_store.py for how one database lets the
engine run in the cloud while the brain bot runs on your PC.

Run:
    python run_news_engine.py

Stop: Ctrl-C (clean shutdown). On Railway it's a managed worker,
restarted automatically if it ever exits.

Author : H&M Opportunity Trader
==========================================================
"""

import signal
import sys
import threading
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional -- on Railway the env vars are injected
    # directly, there's no .env file to load.
    pass

from core.logger import decision, warn
from core.master_loader import MasterLoader
from news_bot import pipeline as news_pipeline
from news_bot.call_budget import CallBudget
from news_bot.config import POLL_INTERVAL_SECONDS
from news_bot.matching import NewsMatcher
from news_bot.news_store import default_store, resolve_database_url


def _install_signal_handlers(stop_event):
    def _handle(signum, _frame):
        decision(
            f"[NEWS_ENGINE] Signal {signum} received -- finishing the "
            f"current cycle and shutting down cleanly."
        )
        stop_event.set()

    # SIGINT = Ctrl-C locally; SIGTERM = how Railway/containers ask a
    # process to stop. Handle both so shutdown is always graceful.
    signal.signal(signal.SIGINT, _handle)
    try:
        signal.signal(signal.SIGTERM, _handle)
    except (ValueError, AttributeError):
        # SIGTERM isn't settable on some platforms (e.g. Windows in
        # certain shells) -- not fatal, Ctrl-C still works.
        pass


def run(stop_event=None, max_cycles=None):
    """
    The forever loop. `stop_event` and `max_cycles` exist so a test
    can run exactly one cycle and stop; production passes neither and
    runs until a signal fires.
    """
    stop_event = stop_event or threading.Event()

    # Fail LOUD on startup if the store can't be reached -- better to
    # crash immediately (Railway will restart and surface it) than to
    # silently poll for hours writing nowhere.
    store = default_store()
    url = resolve_database_url()
    safe_url = url.split("@")[-1] if "@" in url else url   # hide credentials
    decision(
        f"[NEWS_ENGINE] Starting 24/7 news engine. Store: {safe_url}. "
        f"Poll every {POLL_INTERVAL_SECONDS}s. Existing rows: {store.count()}."
    )

    loader = MasterLoader()
    loader.load()
    matcher = NewsMatcher(loader=loader)
    budget = CallBudget()

    cycles = 0
    while not stop_event.is_set():
        try:
            summary = news_pipeline.run_once(matcher=matcher, budget=budget)
            decision(
                f"[NEWS_ENGINE] cycle {cycles + 1}: "
                f"{summary.get('ingested', 0)} ingested, "
                f"{summary.get('matched', 0)} matched, "
                f"{summary.get('high', 0)} HIGH, {summary.get('mid', 0)} MID. "
                f"Store now holds {store.count()} rows."
            )
        except Exception as exc:  # never let one bad cycle kill the engine
            warn(f"[NEWS_ENGINE] cycle failed, will retry next interval: {exc}")

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break

        # Interruptible sleep -- a signal during the wait breaks out
        # immediately instead of hanging for the full interval.
        stop_event.wait(POLL_INTERVAL_SECONDS)

    decision(f"[NEWS_ENGINE] Stopped after {cycles} cycle(s).")
    return cycles


def main():
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    run(stop_event=stop_event)


if __name__ == "__main__":
    sys.exit(main())
