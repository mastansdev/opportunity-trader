"""
==========================================================
py tools/complete_master.py  --  fill the key
==========================================================

    "pls complete the master data its the key . without key where to
     land?"
                                -- operator, 8 August 2026

WHAT HE ASKED FOR, ON 8 AUGUST
------------------------------
    "how many stocks were there and whats their Market cap, CMP,
     Volumes, Delivery %, Sector, theme, industry, FnO, stocks
     affected by"

WHAT THE MASTER ACTUALLY HELD
-----------------------------
    SECURITY ID, SYMBOL, COMPANY NAME, SECTOR, INDUSTRY,
    CORE BUSINESS, BUSINESS_TYPE, OWNERSHIP, COMMODITY_EXPOSURE,
    ECONOMIC_SENSITIVITY, KEYWORDS, THEMES, SUBSCRIBE,
    SUBSCRIBE_REASON

Five of the nine he asked for were not there for ANY row: market cap,
CMP, volume, delivery %, F&O. And SECTOR and INDUSTRY were empty on
336 of 1,608 rows.

I reported this work complete. It was not.

WHERE EACH FIELD COMES FROM
---------------------------
    MCAP_CR         data/LIST_NSE.xlsx -- NSE's own SEBI-LODR filing,
                    average mcap Jul-Dec 2025, in lakhs. His file.
    CMP             data/daily_candles.db, most recent close
    AVG_VOL_20D     data/daily_candles.db, mean of the last 20 sessions
    AVG_TURNOVER_CR CMP x AVG_VOL_20D
    BAND_PCT        data/sec_list_*.csv -- NSE's daily price band
    FNO_LIKELY      band = "No Band". NSE removes the daily band from
                    F&O names, so no band is a STRONG HINT, not proof.
                    Named LIKELY for that reason.
    DELIVERY_PCT    data/delivery.db

WHAT IS DELIBERATELY LEFT BLANK
-------------------------------
SECTOR and INDUSTRY where no source has them. There is no local file
that carries an NSE sector for those 336 rows, and guessing one from
the company name would put "Pharmaceuticals" next to a company that
makes valves.

    "0 knowlede is far better than half knowledge"

A blank is a question the bot knows it cannot answer. An invented
sector is a wrong answer it will act on -- and core/news_impact.py
fans a sector event out to every stock in that sector, so one bad
label sends a pharma headline into a metals stock's chip.

Same for DELIVERY_PCT while data/delivery.db is empty. It is not
filled with zero, because zero means "nobody took delivery" and empty
means "we did not ask yet".

    py tools/fetch_delivery.py --days 30

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import glob
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MASTER = os.path.join("data", "master_stocks.csv")
MCAP_XLSX = os.path.join("data", "LIST_NSE.xlsx")
DAILY_DB = os.path.join("data", "daily_candles.db")
DELIVERY_DB = os.path.join("data", "delivery.db")
BAND_GLOB = os.path.join("data", "sec_list_*.csv")

NEW_COLUMNS = ("MCAP_CR", "CMP", "AVG_VOL_20D", "AVG_TURNOVER_CR",
               "BAND_PCT", "FNO_LIKELY", "DELIVERY_PCT", "DATA_AS_OF")


def _mcap():
    """{symbol: crore} from NSE's SEBI-LODR list. Values are in LAKHS."""
    try:
        import pandas as pd
        frame = pd.read_excel(MCAP_XLSX)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  ! market cap file unreadable ({exc})")
        return {}
    column = None
    for name in frame.columns:
        if "market capitalisation" in str(name).lower():
            column = name
            break
    if column is None:
        print("  ! no market-cap column in LIST_NSE.xlsx")
        return {}
    out = {}
    for _, row in frame.iterrows():
        symbol = str(row.get("Symbol") or "").strip().upper()
        try:
            out[symbol] = float(row[column]) / 100.0        # lakhs -> crore
        except (TypeError, ValueError):
            continue
    return out


def _prices():
    """{symbol: (cmp, avg_vol_20d)} from the daily bars."""
    out = {}
    if not os.path.exists(DAILY_DB):
        return out
    con = sqlite3.connect(DAILY_DB)
    con.execute("create index if not exists ix_sym_date_c "
                "on daily_bars(symbol, date)")
    rows = con.execute(
        "select symbol, close, volume from daily_bars "
        "where date >= (select max(date) from daily_bars) "
        "  or date > date((select max(date) from daily_bars), '-40 day') "
        "order by symbol, date").fetchall()
    con.close()
    bucket = {}
    for symbol, close, volume in rows:
        bucket.setdefault(symbol, []).append((close, volume or 0.0))
    for symbol, series in bucket.items():
        tail = series[-20:]
        out[symbol] = (series[-1][0],
                       sum(v for _c, v in tail) / max(len(tail), 1))
    return out


def _bands():
    """{symbol: band_pct or None} from NSE's securities list."""
    out = {}
    files = sorted(glob.glob(BAND_GLOB))
    if not files:
        return out
    with open(files[-1], newline="", encoding="utf-8", errors="ignore") as fh:
        for row in csv.DictReader(fh):
            if (row.get("Series") or "").strip().upper() != "EQ":
                continue
            symbol = (row.get("Symbol") or "").strip().upper()
            raw = (row.get("Band") or "").strip()
            if not symbol:
                continue
            if raw.upper().replace(" ", "") in ("NOBAND", ""):
                out[symbol] = None
            else:
                try:
                    out[symbol] = float(raw)
                except ValueError:
                    out[symbol] = None
    return out


def _delivery():
    """{symbol: percent} -- empty until he runs tools/fetch_delivery.py."""
    out = {}
    if not os.path.exists(DELIVERY_DB):
        return out
    try:
        con = sqlite3.connect(DELIVERY_DB)
        tables = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")]
        if not tables:
            con.close()
            return out
        for table in tables:
            cols = [r[1].lower() for r in con.execute(
                f"pragma table_info({table})")]
            if "symbol" not in cols:
                continue
            # ---- MATCH THE REAL COLUMN NAME. 8 August 2026. ----
            # The first version looked for "deliv" AND "per". The
            # column is deliv_pct, which contains neither "per" nor
            # "percent", so it matched nothing and reported 0 symbols
            # against a 50,327-row table that had just been filled.
            # A reader that silently finds nothing looks exactly like
            # data that is not there.
            pct = next((c for c in cols
                        if "deliv" in c and ("pct" in c or "per" in c)), None)
            if not pct:
                continue
            # The most recent 20 sessions, not all of history -- what
            # matters is whether delivery is running high NOW.
            for symbol, value in con.execute(
                    f"select symbol, avg({pct}) from ("
                    f"  select symbol, {pct}, "
                    f"    row_number() over (partition by symbol "
                    f"      order by date desc) as rn "
                    f"  from {table} where {pct} is not null"
                    f") where rn <= 20 group by symbol"):
                try:
                    out[str(symbol).strip().upper()] = round(float(value), 2)
                except (TypeError, ValueError):
                    continue
        con.close()
    except Exception:                                          # noqa: BLE001
        return {}
    return out


def run():
    rows = list(csv.DictReader(open(MASTER, encoding="utf-8", errors="ignore")))
    if not rows:
        print("  ! master_stocks.csv is empty")
        return 1
    columns = list(rows[0].keys())

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(MASTER, f"{MASTER}.{stamp}.bak")
    print(f"  backed up -> master_stocks.csv.{stamp}.bak\n")

    mcap, prices, bands, delivery = _mcap(), _prices(), _bands(), _delivery()
    print(f"  market cap file   {len(mcap):>5} symbols")
    print(f"  daily bars        {len(prices):>5} symbols")
    print(f"  price bands       {len(bands):>5} symbols")
    print(f"  delivery %        {len(delivery):>5} symbols"
          f"{'   <- run tools/fetch_delivery.py' if not delivery else ''}\n")

    for column in NEW_COLUMNS:
        if column not in columns:
            columns.append(column)

    today = datetime.now().date().isoformat()
    filled = {c: 0 for c in NEW_COLUMNS}
    for row in rows:
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        cap = mcap.get(symbol)
        px, vol = prices.get(symbol, (None, None))
        band = bands.get(symbol, "missing")
        dely = delivery.get(symbol)

        row["MCAP_CR"] = f"{cap:.2f}" if cap else ""
        row["CMP"] = f"{px:.2f}" if px else ""
        row["AVG_VOL_20D"] = f"{vol:.0f}" if vol else ""
        row["AVG_TURNOVER_CR"] = (f"{px * vol / 1e7:.2f}"
                                  if px and vol else "")
        # A missing band and a "No Band" band are different answers.
        row["BAND_PCT"] = ("" if band == "missing"
                           else ("" if band is None else f"{band:.0f}"))
        row["FNO_LIKELY"] = ("" if band == "missing"
                             else ("YES" if band is None else "NO"))
        row["DELIVERY_PCT"] = f"{dely:.2f}" if dely is not None else ""
        row["DATA_AS_OF"] = today
        for column in NEW_COLUMNS:
            if row[column]:
                filled[column] += 1

    with open(MASTER, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    print(f"  {total} rows written\n")
    print(f"  {'FIELD':<18}{'FILLED':>8}{'BLANK':>8}   COVERAGE")
    for column in NEW_COLUMNS:
        got = filled[column]
        print(f"  {column:<18}{got:>8}{total - got:>8}   "
              f"{got / total * 100:>5.1f}%")
    for column in ("SECTOR", "INDUSTRY", "THEMES"):
        got = sum(1 for r in rows if str(r.get(column) or "").strip())
        print(f"  {column:<18}{got:>8}{total - got:>8}   "
              f"{got / total * 100:>5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
