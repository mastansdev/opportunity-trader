# New Stocks -- awaiting classification

Generated 2026-09-02 15:34 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**0 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.
