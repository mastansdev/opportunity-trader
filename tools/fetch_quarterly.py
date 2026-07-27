"""
==========================================================
Fetch quarterly results into the bot's memory
==========================================================

    py tools/fetch_quarterly.py --inspect      # SHOW the raw feed first
    py tools/fetch_quarterly.py                # fetch and store
    py tools/fetch_quarterly.py --symbol TMB   # one name
    py tools/fetch_quarterly.py --report       # what do we already know

WHY --inspect EXISTS AND WHY YOU SHOULD RUN IT FIRST
-----------------------------------------------------
The parser below is written against the field names BSE's resultsSnapshot
is BELIEVED to use. That belief has not been checked against a live
response, because the `bse` package is not installed where this file was
written. A parser written from memory against a feed nobody looked at is
exactly how this project ended up storing 296 results dates and ZERO
timestamps (see tools/inspect_results_feed.py, which exists for the same
reason on the NSE side).

So: run --inspect once, paste the output back, and the field mapping gets
corrected in minutes instead of guessed at. Until then, expect --inspect
to work and the parser to need a nudge.

WHAT IT IS FOR
--------------
core/results_calendar.py knows WHO reports and WHEN.
core/announcement_watcher.py knows a filing just LANDED.
Neither knows whether the numbers were good.

2026-07-27, the day that made this necessary:

    KFINTECH    filed, revenue +30% YoY, profit beat    +9.2%
    ACUTAAS     filed the same week                    -Rs 1,593 for us

Both had a results event in the calendar. Only the numbers separate them.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.quarterly_results import QuarterlyResults  # noqa: E402

# Field names to try, most likely first. BSE's JSON is not consistent
# across endpoints, so each target accepts several spellings rather than
# one guess that silently stores None.
FIELD_MAP = {
    "sales": ("sales", "revenue", "net_sales", "total_income",
              "revenue_from_operations", "NetSales", "Revenue"),
    "other_income": ("other_income", "otherincome", "OtherIncome"),
    "operating_profit": ("operating_profit", "op", "ebitda",
                         "OperatingProfit", "PBIDT"),
    "opm_pct": ("opm", "opm_pct", "operating_margin", "OPM"),
    "pat": ("pat", "net_profit", "profit_after_tax", "NetProfit",
            "profit_for_the_period", "PAT"),
    "eps": ("eps", "basic_eps", "earnings_per_share", "EPS"),
}

PERIOD_FIELDS = ("period_end", "period", "quarter_end", "end_date",
                 "PeriodEnded", "quarter", "Period")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def pick(row, names):
    for n in names:
        if n in row and row[n] not in (None, "", "-"):
            return row[n]
    lowered = {str(k).lower().replace(" ", "_"): v for k, v in row.items()}
    for n in names:
        key = n.lower().replace(" ", "_")
        if key in lowered and lowered[key] not in (None, "", "-"):
            return lowered[key]
    return None


def to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_period(value):
    """'Jun-26' / '2026-06-30' / '30-06-2026' -> (date, label).

    A quarter LABEL is not sortable ('Dec' < 'Jun' alphabetically), so
    everything is normalised to the quarter's last day.
    """
    raw = str(value or "").strip()
    if not raw:
        return None, None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(raw[:10], fmt).date()
            return d, d.strftime("%b-%y")
        except ValueError:
            pass
    parts = raw.replace("'", "-").replace(" ", "-").split("-")
    if len(parts) >= 2 and parts[0][:3].lower() in _MONTHS:
        month = _MONTHS[parts[0][:3].lower()]
        try:
            year = int(parts[1])
        except ValueError:
            return None, None
        year += 2000 if year < 100 else 0
        last = {3: 31, 6: 30, 9: 30, 12: 31}.get(month, 30)
        return date(year, month, last), f"{parts[0][:3].title()}-{year % 100:02d}"
    return None, None


def inspect_feed(limit=3):
    """Print the RAW shape. Interprets nothing."""
    print("=" * 74)
    print("  RAW BSE RESULTS FEED -- nothing interpreted")
    print("=" * 74)
    try:
        from bse import BSE
    except ImportError:
        print("\n  The `bse` package is not installed here.")
        print("  Install it where the bot runs:  py -m pip install bse\n")
        return
    with BSE(download_folder="data") as b:
        for name in ("resultsSnapshot", "results", "corporateActions"):
            fn = getattr(b, name, None)
            if fn is None:
                print(f"\n  BSE has no method `{name}`")
                continue
            try:
                data = fn()
            except Exception as exc:                       # noqa: BLE001
                print(f"\n  {name}() raised: {exc}")
                continue
            print(f"\n  {name}() -> {type(data).__name__}")
            rows = data if isinstance(data, list) else (
                list(data.values())[0] if isinstance(data, dict) and data else [])
            if isinstance(rows, dict):
                rows = [rows]
            if not rows:
                print("    (empty)")
                continue
            print(f"    {len(rows)} rows. FIELDS ON ROW 0:")
            first = rows[0] if isinstance(rows[0], dict) else {"value": rows[0]}
            for k in sorted(first):
                print(f"      {str(k):<28} = {str(first[k])[:46]}")
            print("\n    FIRST ROWS RAW:")
            for r in rows[:limit]:
                print(f"      {json.dumps(r, default=str)[:200]}")


def store_rows(rows, store, source="bse", verbose=True):
    counts = {"new": 0, "updated": 0, "unchanged": 0, "unparsed": 0}
    for row in rows:
        if not isinstance(row, dict):
            counts["unparsed"] += 1
            continue
        symbol = pick(row, ("symbol", "scrip_id", "SC_NAME", "security_id"))
        period_end, label = parse_period(pick(row, PERIOD_FIELDS))
        if not symbol or period_end is None:
            counts["unparsed"] += 1
            continue
        outcome = store.remember(
            symbol=symbol, period_end=period_end, period_label=label,
            source=source,
            **{k: to_float(pick(row, names)) for k, names in FIELD_MAP.items()})
        counts[outcome] += 1
    if verbose:
        print(f"  new {counts['new']}, updated {counts['updated']}, "
              f"unchanged {counts['unchanged']}, could not parse "
              f"{counts['unparsed']}")
        if counts["unparsed"] and not (counts["new"] or counts["updated"]):
            print("  -> nothing stored. Run --inspect and paste the output; "
                  "the field names are almost certainly different.")
    return counts


def report(store, symbol=None):
    if symbol:
        cmp_ = store.compare(symbol)
        hist = store.history(symbol)
        print(f"\n{symbol}: {len(hist)} quarters stored")
        for h in hist:
            print(f"   {h['period_label'] or h['period_end']}  "
                  f"sales {h['sales']}  PAT {h['pat']}  EPS {h['eps']}")
        if cmp_:
            print(f"\n   grade: {cmp_['grade']}   {cmp_['summary']}")
        else:
            print("\n   not enough quarters stored to compare yet")
        return
    print(f"\n{store.count()} quarters stored across "
          f"{len(store.symbols())} symbols")
    graded = {}
    for s in sorted(store.symbols()):
        c = store.compare(s)
        if c and c["grade"]:
            graded.setdefault(c["grade"], []).append(s)
    for g in ("STRONG", "GOOD", "MIXED", "WEAK"):
        names = graded.get(g, [])
        if names:
            print(f"   {g:<8}{len(names):>4}   "
                  + ", ".join(names[:10])
                  + ("..." if len(names) > 10 else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true",
                    help="print the raw feed and store nothing")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--symbol")
    a = ap.parse_args()

    if a.inspect:
        inspect_feed()
        return

    store = QuarterlyResults()
    if a.report or a.symbol:
        report(store, a.symbol)
        return

    try:
        from bse import BSE
    except ImportError:
        print("The `bse` package is not installed. py -m pip install bse")
        return
    print("Fetching BSE results snapshot...")
    with BSE(download_folder="data") as b:
        data = b.resultsSnapshot()
    rows = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
    flat = []
    for r in rows:
        flat.extend(r) if isinstance(r, list) else flat.append(r)
    print(f"  {len(flat)} rows returned")
    store_rows(flat, store)
    report(store)


if __name__ == "__main__":
    main()
