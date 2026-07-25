"""
One-time cleanup: delete the NEUTRAL / no-signal rows that were stored
before the neutral-drop rule (2026-07-24). After this, the store holds
only directional (bullish/bearish) + HIGH items -- real signals, no
"Please refer attachment" fan-out noise.

Run:  py tools/clean_news.py
Safe to run more than once (it just deletes whatever neutral rows remain).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_bot.news_store import default_store


def main():
    store = default_store()
    before = store.count()
    removed = store.delete_neutral()
    after = store.count()
    print(f"Removed {removed} neutral/no-signal rows.")
    print(f"Store: {before} -> {after} rows (only directional + HIGH remain).")


if __name__ == "__main__":
    main()
