# New Stocks -- awaiting classification

Generated 2026-08-31 15:56 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**4 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|
| GAJA | 765396 | 158.66 | 119.57 | |
| JAYSREETEA | 1720 | 98.84 | 2.54 | |
| RANASUG | 2837 | 15.31 | 1.82 | |
| NILASPACES | 7411 | 12.55 | 1.74 | |

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.
