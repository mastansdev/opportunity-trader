# New Stocks -- awaiting classification

Generated 2026-08-22 08:55 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**6 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|
| PONNIERODE | 10661 | 419.55 | 4.05 | |
| MYSORPETRO | 4377 | 166.11 | 3.65 | |
| DCMSRIND | 7325 | 51.24 | 1.87 | |
| KMSUGAR | 14667 | 33.55 | 1.82 | |
| 3BBLACKBIO | 762518 | 1,202.50 | 1.64 | |
| HATHWAY | 18154 | 10.68 | 1.51 | |

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.
