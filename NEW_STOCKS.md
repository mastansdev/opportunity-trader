# New Stocks -- awaiting classification

Generated 2026-07-28 08:37 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**38 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|
| ORIENTTECH | 24961 | 279.17 | 215.77 | |
| MONARCH | 7679 | 397.60 | 201.53 | |
| SESHAPAPER | 3066 | 237.29 | 96.72 | |
| MANCREDIT | 24823 | 222.30 | 45.32 | |
| ASHIKAG | 762548 | 429.65 | 41.65 | |
| AGI | 1412 | 707.15 | 19.17 | |
| TEMBO | 3275 | 552.30 | 17.46 | |
| ROSSARI | 19410 | 519.95 | 11.85 | |
| TTKHLTCARE | 11369 | 1,088.80 | 11.40 | |
| RSYSTEMS | 13414 | 252.85 | 10.61 | |
| HESTERBIO | 7048 | 2,528.40 | 10.34 | |
| GULFOILLUB | 4391 | 1,048.20 | 9.36 | |
| PRAVEG | 762844 | 301.07 | 9.36 | |
| BHARATSE | 30244 | 211.85 | 9.35 | |
| DHANUKA | 24409 | 996.20 | 9.06 | |
| ALLDIGI | 11798 | 872.05 | 9.04 | |
| MEDIASSIST | 21705 | 347.15 | 9.02 | |
| RAMCOIND | 4587 | 336.85 | 8.84 | |
| TEAMLEASE | 12716 | 1,294.00 | 8.75 | |
| ASAHISONG | 25088 | 339.85 | 8.63 | |
| TALBROAUTO | 13648 | 386.85 | 7.56 | |
| GANESHHOU | 14339 | 819.85 | 7.39 | |
| EUROPRATIK | 759797 | 314.60 | 7.03 | |
| KENNAMET | 11841 | 2,837.30 | 6.94 | |
| CENTENKA | 619 | 577.80 | 6.92 | |
| MHRIL | 17333 | 223.83 | 6.87 | |
| TARSONS | 6943 | 320.90 | 6.70 | |
| BETA | 759842 | 2,230.70 | 6.68 | |
| IGPL | 14086 | 472.75 | 6.54 | |
| ASALCBR | 17598 | 791.70 | 6.12 | |
| APOLLOPIPE | 14361 | 505.35 | 5.91 | |
| CEINSYS | 761037 | 858.60 | 5.87 | |
| DODLA | 4822 | 1,031.90 | 5.75 | |
| ONWARDTEC | 2481 | 292.75 | 5.32 | |
| KIRLFER | 14466 | 480.95 | 5.26 | |
| SAIPARENT | 761675 | 559.75 | 5.12 | |
| JASH | 13982 | 516.80 | 5.12 | |
| INTERARCH | 24909 | 1,827.10 | 5.06 | |

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.
