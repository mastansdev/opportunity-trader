# New Stocks -- awaiting classification

Generated 2026-08-19 15:54 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**7 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|
| MOLBIO | 764548 | 1,110.90 | 1,252.20 | |
| DHOOTTRANS | 764553 | 1,305.75 | 1,158.95 | |
| SALSTEEL | 11634 | 72.02 | 5.58 | |
| FREDUN | 764683 | 1,436.70 | 2.10 | |
| KAYA | 10276 | 338.75 | 1.89 | |
| ANNAPURNA | 764471 | 157.60 | 1.72 | |
| ARIES | 15204 | 442.70 | 1.59 | |

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.
