# New Stocks -- awaiting classification

Generated 2026-09-03 16:04 by `py tools/morning_universe.py`.

These passed every market test (EQ series, Rs 200-10,000, 
liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,
so they are sitting at **SUBSCRIBE = NO** and are not being traded.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the
next morning's run flips it to **YES** on its own.

**15 waiting.**

| Symbol | Security ID | Close | Turnover (cr) | Sector? |
|---|---|---|---|---|
| DEN | 17722 | 27.85 | 1.21 | |
| ISFT | 18479 | 87.81 | 1.17 | |
| AXITA | 9902 | 7.97 | 1.03 | |
| MEDICAMEQ | 6278 | 265.25 | 0.99 | |
| GOKUL | 16705 | 41.37 | 0.99 | |
| LANCORHOL | 23027 | 33.15 | 0.97 | |
| TGVSL | 764955 | 103.35 | 0.96 | |
| KHAICHEM | 896 | 54.00 | 0.92 | |
| JYOTIRES | 764733 | 857.60 | 0.92 | |
| BIRLAPREC | 762593 | 43.11 | 0.88 | |
| SHREDIGCEM | 3099 | 70.95 | 0.87 | |
| HERANBA | 2614 | 175.23 | 0.86 | |
| HALDER | 760715 | 293.90 | 0.81 | |
| ALBERTDAVD | 17256 | 871.70 | 0.81 | |
| KSOLVES | 11060 | 273.20 | 0.77 | |

Rows with no Dhan security ID cannot be subscribed to at 
all -- the feed is keyed on that ID, not the symbol.

## MANBRO removed, 3 September 2026

`data/master_stocks.csv` carried a row for MANBRO INDUSTRIES LIMITED,
security id **765105**, marked `SUBSCRIBE=YES` — tradeable.

765105 belongs to **KDGREEN (KD GREEN INDUSTRIES LTD)**, confirmed
against Dhan's own `api-scrip-master.csv`, NSE / EQ. The master carried
KDGREEN separately with the same id, queued as a new listing.

MANBRO appears **nowhere** in Dhan's scrip master — not on NSE, not on
any segment, under no trading symbol, custom symbol or company name.

So the row was a tradeable entry pointing at another company's
instrument. An order for MANBRO would have bought KD Green Industries.
It is removed rather than corrected because there is no correct id to
give it: the instrument does not exist at the broker.

The KDGREEN row keeps 765105 and stays `SUBSCRIBE=NO` — "new listing,
awaiting sector classification" — until it is classified like any
other.
