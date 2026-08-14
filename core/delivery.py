"""
==========================================================
Delivery percentage -- who is buying to KEEP
==========================================================

    "my gut feeling = without any info no one will buy even a 1 rs.
     in the stock market every thing is connected but never seen in
     that way by anyone"
                                -- operator, 7 August 2026

    "by seeing them many FII/DII, retail Algos started to accumalte
     stocks even some weak stocks will get locked in upper citcuits"

WHY THIS EXISTS
---------------
The bot can see that a stock moved and, since 8 August, why. It cannot
see the thing that happens BEFORE the move: someone quietly taking
stock off the market, day after day, while the price barely changes.

Delivery percentage is that footprint, and NSE publishes it free.

    delivery % = the share of a day's volume actually taken into a
                 demat account, rather than bought and sold the same
                 session

Intraday churn washes out of that number. What remains is conviction.
Published thresholds (researched 8 August, sources in the operator's
notes):

    large caps    above 50%   healthy
                  above 60%   strong institutional interest
    mid / small   above 40%   notable

And the pattern that matters most, which is NOT a single day:

    three to five consecutive sessions of above-average delivery, in a
    TIGHT price range, on DECLINING total volume

That is supply being absorbed without the price being chased -- the
shape that precedes the move rather than confirming it.

    delivery rising + price rising   = accumulation
    delivery rising + price falling  = distribution

WHY A SECOND DOWNLOAD
---------------------
The bot already pulls NSE's UDiFF bhavcopy nightly. Checked column by
column on the real file, 8 August: it carries OHLC, volume, turnover,
trade count -- and NO delivery figures at all. The Rsvd1-4 columns are
empty.

Delivery lives in a different published file:

    sec_bhavdata_full_DDMMYYYY.csv

Same host the bot already reaches for index constituents, so this is
known-good ground rather than a new dependency.

WHAT THIS DOES NOT CLAIM
------------------------
That high delivery predicts a rise. It does not, on its own, and this
module scores nothing and vetoes nothing. It reports a reading, the
same standing rule as the run-up check:

    "nothing from the guides becomes a rule until scored against real
     outcomes"

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

ARCHIVE = "https://nsearchives.nseindia.com"
URL = ARCHIVE + "/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"

DB_PATH = os.path.join("data", "delivery.db")
RAW_DIR = "data"

# NSE serves nothing to a client that does not look like a browser.
# Same header set core/news_watcher.py already uses successfully.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "text/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# The published bands. Kept as named constants because they are
# somebody else's numbers, not ours, and should be visible as such.
STRONG_LARGE = 60.0
HEALTHY_LARGE = 50.0
NOTABLE_SMALL = 40.0

# The accumulation pattern needs a run, not a day.
RUN_SESSIONS = 3
TIGHT_RANGE_PCT = 4.0       # price moved less than this across the run


def _ddmmyyyy(when):
    return when.strftime("%d%m%Y")


# ---------------------------------------------------------------
# 1. GET IT
# ---------------------------------------------------------------
def raw_path(when, folder=RAW_DIR):
    return os.path.join(folder, f"sec_bhavdata_full_{_ddmmyyyy(when)}.csv")


def download(when=None, folder=RAW_DIR, timeout=45):
    """Fetch one session's delivery file. Returns the path, or None.

    Never raises. A missing file on a holiday is normal and must not
    stop the nightly run.
    """
    when = when or date.today()
    if hasattr(when, "date") and not isinstance(when, date):
        when = when.date()
    target = raw_path(when, folder)
    if os.path.exists(target) and os.path.getsize(target) > 2000:
        return target

    import urllib.request
    url = URL.format(ddmmyyyy=_ddmmyyyy(when))
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except Exception:                                      # noqa: BLE001
        return None
    if not body or len(body) < 2000 or b"," not in body[:400]:
        return None
    try:
        with open(target, "wb") as handle:
            handle.write(body)
    except Exception:                                      # noqa: BLE001
        return None
    return target


# ---------------------------------------------------------------
# 2. READ IT
# ---------------------------------------------------------------
# NSE pads its headers with spaces -- " DELIV_PER", "SERIES  ". Every
# lookup here is done on a stripped, upper-cased key for that reason.
def _key(name):
    return re.sub(r"[^A-Z_%]", "", str(name or "").upper())


def parse(path):
    """[{symbol, series, close, volume, deliv_qty, deliv_pct}] for one
    session. Cash series only."""
    out = []
    try:
        handle = open(path, newline="", encoding="utf-8", errors="ignore")
    except Exception:                                      # noqa: BLE001
        return out
    with handle:
        reader = csv.reader(handle)
        try:
            header = [_key(c) for c in next(reader)]
        except StopIteration:
            return out
        index = {name: i for i, name in enumerate(header)}

        def get(row, *names):
            for name in names:
                i = index.get(name)
                if i is not None and i < len(row):
                    value = str(row[i]).strip()
                    if value and value not in ("-", "NA"):
                        return value
            return None

        for row in reader:
            if not row:
                continue
            series = (get(row, "SERIES") or "").upper()
            if series != "EQ":
                continue
            symbol = (get(row, "SYMBOL") or "").upper()
            if not symbol:
                continue
            try:
                pct = float(get(row, "DELIV_PER", "DELIVPER") or "nan")
            except ValueError:
                continue
            if pct != pct:                       # NaN
                continue
            def _num(*names):
                raw = get(row, *names)
                try:
                    return float(str(raw).replace(",", "")) if raw else None
                except ValueError:
                    return None
            out.append({
                "symbol": symbol,
                "close": _num("CLOSE_PRICE", "CLOSEPRICE", "CLOSE"),
                "volume": _num("TTL_TRD_QNTY", "TTLTRDQNTY"),
                "deliv_qty": _num("DELIV_QTY", "DELIVQTY"),
                "deliv_pct": pct,
            })
    return out


# ---------------------------------------------------------------
# 3. KEEP IT
# ---------------------------------------------------------------
def _connect(db_path=DB_PATH):
    con = sqlite3.connect(db_path)
    con.execute("""create table if not exists delivery (
        date text not null, symbol text not null,
        close real, volume real, deliv_qty real, deliv_pct real,
        primary key (date, symbol))""")
    con.execute("create index if not exists ix_deliv_symbol "
                "on delivery(symbol, date)")
    return con


def store(when, rows, db_path=DB_PATH):
    """Write one session. Returns how many rows landed."""
    if not rows:
        return 0
    day = when.isoformat() if hasattr(when, "isoformat") else str(when)
    con = _connect(db_path)
    con.executemany(
        "insert or replace into delivery "
        "(date, symbol, close, volume, deliv_qty, deliv_pct) "
        "values (?,?,?,?,?,?)",
        [(day, r["symbol"], r["close"], r["volume"],
          r["deliv_qty"], r["deliv_pct"]) for r in rows])
    con.commit()
    con.close()
    return len(rows)


def ingest(when=None, folder=RAW_DIR, db_path=DB_PATH):
    """download -> parse -> store, for one session."""
    when = when or date.today()
    if hasattr(when, "date") and not isinstance(when, date):
        when = when.date()
    path = download(when, folder=folder)
    if not path:
        return {"ok": False, "date": when.isoformat(),
                "why": "not published (holiday?) or the fetch was refused"}
    rows = parse(path)
    if not rows:
        return {"ok": False, "date": when.isoformat(),
                "why": f"{os.path.basename(path)} carried no EQ rows -- "
                       f"has the format changed?"}
    n = store(when, rows, db_path=db_path)
    return {"ok": True, "date": when.isoformat(), "rows": n,
            "file": os.path.basename(path)}


# ---------------------------------------------------------------
# 4. READ THE PATTERN
# ---------------------------------------------------------------
def history(symbol, on_date=None, sessions=10, db_path=DB_PATH):
    """The last N sessions of delivery for one stock, oldest first."""
    symbol = str(symbol or "").upper()
    if not symbol:
        return []
    on_date = on_date or date.today()
    if hasattr(on_date, "date") and not isinstance(on_date, date):
        on_date = on_date.date()
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "select date, close, volume, deliv_pct from delivery "
            "where symbol = ? and date <= ? order by date desc limit ?",
            (symbol, on_date.isoformat(), sessions)).fetchall()
        con.close()
    except Exception:                                      # noqa: BLE001
        return []
    return list(reversed(rows))


def reading(symbol, on_date=None, sessions=10, db_path=DB_PATH):
    """{"reading", "pct", "avg", "text"} or None if we cannot say.

    ACCUMULATION is the one worth waiting for: a run of above-average
    delivery while the price stays in a tight range and volume falls.
    That is stock being absorbed without the price being chased.
    """
    rows = history(symbol, on_date=on_date, sessions=sessions,
                   db_path=db_path)
    if len(rows) < RUN_SESSIONS + 1:
        return None

    pcts = [r[3] for r in rows if r[3] is not None]
    closes = [r[1] for r in rows if r[1]]
    volumes = [r[2] for r in rows if r[2]]
    if len(pcts) < RUN_SESSIONS + 1 or len(closes) < RUN_SESSIONS + 1:
        return None

    latest = pcts[-1]
    baseline = sum(pcts[:-RUN_SESSIONS]) / max(len(pcts) - RUN_SESSIONS, 1)
    run = pcts[-RUN_SESSIONS:]
    run_closes = closes[-RUN_SESSIONS:]

    above = all(p > baseline for p in run)
    span = ((max(run_closes) - min(run_closes)) / min(run_closes) * 100.0
            if min(run_closes) else 999.0)
    falling_volume = (len(volumes) >= RUN_SESSIONS + 1
                      and sum(volumes[-RUN_SESSIONS:]) / RUN_SESSIONS
                      < sum(volumes[:-RUN_SESSIONS])
                      / max(len(volumes) - RUN_SESSIONS, 1))
    price_up = run_closes[-1] > run_closes[0]

    if above and span <= TIGHT_RANGE_PCT and falling_volume:
        reading_name = "ACCUMULATION"
        text = (f"{RUN_SESSIONS} sessions of above-average delivery "
                f"({latest:.0f}% vs {baseline:.0f}% normal) in a "
                f"{span:.1f}% range on falling volume -- stock being "
                f"absorbed quietly")
    elif above and price_up:
        reading_name = "BUYING"
        text = (f"delivery rising ({latest:.0f}% vs {baseline:.0f}%) "
                f"with the price -- buyers are keeping it")
    elif above and not price_up:
        reading_name = "DISTRIBUTION"
        text = (f"delivery rising ({latest:.0f}% vs {baseline:.0f}%) "
                f"while the price falls -- stock changing hands on the "
                f"way down")
    elif latest >= STRONG_LARGE:
        reading_name = "HIGH"
        text = f"{latest:.0f}% delivered -- strong institutional interest"
    elif latest < baseline * 0.7:
        reading_name = "CHURN"
        text = (f"only {latest:.0f}% delivered against {baseline:.0f}% "
                f"normal -- mostly intraday hands")
    else:
        reading_name = "NORMAL"
        text = f"{latest:.0f}% delivered, about its usual {baseline:.0f}%"

    return {"reading": reading_name, "pct": round(latest, 1),
            "avg": round(baseline, 1), "sessions": len(pcts),
            "text": text}


def coverage(db_path=DB_PATH):
    """What is actually stored -- so an empty answer can be explained."""
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "select count(*), count(distinct symbol), min(date), max(date) "
            "from delivery").fetchone()
        con.close()
    except Exception:                                      # noqa: BLE001
        return {"rows": 0, "symbols": 0, "from": None, "to": None}
    return {"rows": row[0], "symbols": row[1], "from": row[2], "to": row[3]}
