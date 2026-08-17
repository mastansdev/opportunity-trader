# New Stocks -- awaiting classification

Generated 2026-08-17 22:56 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**12 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|
| LEAPIND | 764523 | 144.93 | 1,458.90 | |
| TECHNOCRAF | 764532 | 311.15 | 879.73 | |
| XTRANET | 764312 | 172.50 | 6.30 | |
| SHUKRAPHAR | 764537 | 41.42 | 4.66 | |
| MAWANASUG | 17022 | 116.04 | 3.14 | |
| ACSTECH | 762533 | 49.98 | 2.67 | |
| RPPINFRA | 20760 | 59.65 | 2.51 | |
| AMBALALSA | 762543 | 42.27 | 2.20 | |
| DOLPHIN | 18139 | 508.10 | 2.04 | |
| 5PAISA | 445 | 383.80 | 1.79 | |
| VPRPL | 18341 | 32.86 | 1.70 | |
| STEELXIND | 21339 | 10.87 | 1.57 | |

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.
