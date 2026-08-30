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


def inspect_feed(sample_symbol="TMB", limit=3):
    """Print the RAW shape. Interprets nothing.

    Round 1 of this (2026-07-27) assumed resultsSnapshot() was a bulk
    feed. It is not:

        resultsSnapshot() missing 1 required positional argument: 'scripcode'

    So it is ONE CALL PER COMPANY, keyed on the BSE scrip code -- a
    different number from the NSE symbol this bot uses everywhere else.
    That means a symbol -> scripcode map is needed before anything can be
    fetched, which is why this now inspects the lookup path too.
    """
    import inspect as _inspect
    print("=" * 74)
    print("  RAW BSE FEED -- nothing interpreted")
    print("=" * 74)
    try:
        from bse import BSE
    except ImportError:
        print("\n  The `bse` package is not installed here.")
        print("  Install it where the bot runs:  py -m pip install bse\n")
        return

    print("\n  EVERY PUBLIC METHOD ON BSE, with its arguments:")
    for name in sorted(m for m in dir(BSE) if not m.startswith("_")):
        fn = getattr(BSE, name, None)
        if not callable(fn):
            continue
        try:
            print(f"      {name}{_inspect.signature(fn)}"[:110])
        except (TypeError, ValueError):
            print(f"      {name}(...)")

    with BSE(download_folder="data") as b:
        # 1. How do we turn an NSE symbol into a BSE scrip code?
        # getScripCode is the one that works -- confirmed 2026-07-27,
        # getScripCode('TMB') -> "543596".
        print(f"\n  SCRIP CODE FOR {sample_symbol}:")
        code = None
        try:
            code = b.getScripCode(sample_symbol)
            print(f"      getScripCode({sample_symbol!r}) -> {code!r}")
        except Exception as exc:                           # noqa: BLE001
            print(f"      getScripCode raised: {str(exc)[:100]}")
        if code is None:
            print("\n  Re-run with a known code, e.g. TMB:")
            print("      py tools/fetch_quarterly.py --inspect --scripcode 543596")
            return

        # 2. The results themselves, for that one company.
        print(f"\n  resultsSnapshot({code!r}):")
        try:
            _dump(b.resultsSnapshot(code), limit)
        except Exception as exc:                           # noqa: BLE001
            print(f"      raised: {exc}")

        # 3. Two more that showed up in the method list and may carry
        #    the figures or the filing dates we need.
        for name, args in (("resultCalendar", {"scripcode": str(code)}),
                           ("equityMetaInfo", {"scripcode": str(code)})):
            fn = getattr(b, name, None)
            if fn is None:
                continue
            print(f"\n  {name}(scripcode={code!r}):")
            try:
                _dump(fn(**args), limit)
            except Exception as exc:                       # noqa: BLE001
                print(f"      raised: {str(exc)[:120]}")


def _dump(data, limit=3, indent="      "):
    """Print whatever came back, without assuming its shape.

    Round 2 of this got it wrong (2026-07-27): resultsSnapshot returns a
    DICT -- the record itself -- and this function did
    `list(data.values())[0]`, took the first value (a string), and then
    iterated its characters. The operator's output read:

        6 rows. FIELDS ON ROW 0:
          value  = i
        FIRST ROWS RAW:  "i"  "n"  " "

    A dict is now printed as a dict. Only a LIST is treated as rows.
    """
    print(f"{indent}-> {type(data).__name__}")

    if isinstance(data, dict):
        if not data:
            print(f"{indent}(empty dict)")
            return
        print(f"{indent}{len(data)} keys:")
        for k in data:
            v = data[k]
            if isinstance(v, (list, dict)):
                print(f"{indent}  {str(k):<30} = {type(v).__name__} "
                      f"({len(v)} items)")
                # One level down -- quarterly figures usually arrive as a
                # nested list of periods.
                inner = v[0] if isinstance(v, list) and v else (
                    v if isinstance(v, dict) else None)
                if isinstance(inner, dict):
                    for ik in sorted(inner):
                        print(f"{indent}      {str(ik):<26} = "
                              f"{str(inner[ik])[:40]}")
            else:
                print(f"{indent}  {str(k):<30} = {str(v)[:44]}")
        print(f"\n{indent}RAW: {json.dumps(data, default=str)[:900]}")
        return

    if isinstance(data, list):
        if not data:
            print(f"{indent}(empty list)")
            return
        first = data[0]
        if isinstance(first, dict):
            print(f"{indent}{len(data)} rows. FIELDS ON ROW 0:")
            for k in sorted(first):
                print(f"{indent}  {str(k):<30} = {str(first[k])[:42]}")
        print(f"\n{indent}FIRST ROWS RAW:")
        for r in data[:limit]:
            print(f"{indent}  {json.dumps(r, default=str)[:260]}")
        return

    print(f"{indent}RAW: {str(data)[:400]}")


def fetch_symbol(bse, symbol, store, verbose=False):
    """One company. getScripCode -> resultsSnapshot -> parse -> store.

    Confirmed against the live API 2026-07-27. Returns a counts dict; a
    failure on one name never stops a universe walk.
    """
    from core.quarterly_results import parse_results_snapshot
    counts = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
    try:
        code = bse.getScripCode(symbol)
    except Exception as exc:                               # noqa: BLE001
        if verbose:
            print(f"   {symbol:<12} no scrip code ({str(exc)[:50]})")
        counts["failed"] += 1
        return counts
    try:
        payload = bse.resultsSnapshot(str(code))
    except Exception as exc:                               # noqa: BLE001
        if verbose:
            print(f"   {symbol:<12} snapshot failed ({str(exc)[:50]})")
        counts["failed"] += 1
        return counts

    for rec in parse_results_snapshot(payload):
        period_end, label = parse_period(rec["period_label"])
        if period_end is None:
            counts["failed"] += 1
            continue
        outcome = store.remember(
            symbol=symbol, period_end=period_end, period_label=label,
            source="bse:resultsSnapshot",
            sales=rec.get("sales"), pat=rec.get("pat"), eps=rec.get("eps"),
            operating_profit=rec.get("operating_profit"),
            opm_pct=rec.get("opm_pct"), other_income=rec.get("other_income"),
            # Which set of books, decided from the payload's own
            # full-year column. See core/quarterly_results.py.
            basis=rec.get("basis"))
        counts[outcome] += 1
    if verbose:
        print(f"   {symbol:<12} code {code}  "
              f"new {counts['new']} updated {counts['updated']} "
              f"unchanged {counts['unchanged']}")
    return counts


def walk_universe(store, symbols, pause=1.0, verbose=True):
    """One HTTP call per company, so this is an OVERNIGHT job -- 750
    names at a polite one per second is about twelve minutes. It is
    useless for reacting to a filing that lands at 13:22, and it does not
    need to be: resultsSnapshot lags anyway (TMB reported 2026-07-27 and
    the snapshot still showed Mar-26). This builds HISTORY."""
    import time
    try:
        from bse import BSE
    except ImportError:
        print("The `bse` package is not installed. py -m pip install bse")
        return
    total = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
    with BSE(download_folder="data") as b:
        for i, sym in enumerate(symbols, 1):
            for k, v in fetch_symbol(b, sym, store, verbose=False).items():
                total[k] += v
            if verbose and i % 25 == 0:
                print(f"   {i}/{len(symbols)}  new {total['new']} "
                      f"updated {total['updated']} failed {total['failed']}")
            time.sleep(pause)
    print(f"\nDone. new {total['new']}, updated {total['updated']}, "
          f"unchanged {total['unchanged']}, failed {total['failed']}")
    return total


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
    ap.add_argument("--scripcode",
                    help="BSE scrip code to inspect directly, e.g. 543596")
    ap.add_argument("--pause", type=float, default=1.0,
                    help="seconds between companies on a universe walk")
    ap.add_argument("--resume", action="store_true",
                    help="skip symbols already stored (after a Ctrl+C)")
    a = ap.parse_args()

    if a.inspect:
        if a.scripcode:
            try:
                from bse import BSE
            except ImportError:
                print("The `bse` package is not installed.")
                return
            with BSE(download_folder="data") as b:
                print(f"resultsSnapshot({a.scripcode!r}):")
                try:
                    _dump(b.resultsSnapshot(a.scripcode))
                except Exception as exc:                   # noqa: BLE001
                    print(f"   raised: {exc}")
            return
        inspect_feed(sample_symbol=a.symbol or "TMB")
        return

    store = QuarterlyResults()
    if a.report:
        report(store, a.symbol)
        return

    if a.symbol:
        try:
            from bse import BSE
        except ImportError:
            print("The `bse` package is not installed. py -m pip install bse")
            return
        with BSE(download_folder="data") as b:
            fetch_symbol(b, a.symbol.upper(), store, verbose=True)
        report(store, a.symbol.upper())
        return

    # Whole universe. One call per company -- see walk_universe().
    # load() must be called before all_symbols() -- a fresh MasterLoader
    # is empty, which the first version of this read as "no universe".
    symbols = []
    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
        symbols = sorted(loader.all_symbols())
    except Exception as exc:                               # noqa: BLE001
        print(f"Could not load the universe ({exc}).")
        return
    if not symbols:
        print("No symbols in the master universe after load().")
        return
    if a.resume:
        known = store.symbols()
        before = len(symbols)
        symbols = [s for s in symbols if s not in known]
        print(f"--resume: skipping {before - len(symbols)} already stored.")
        if not symbols:
            print("Nothing left to fetch.")
            report(store)
            return

    mins = len(symbols) * a.pause / 60.0
    print(f"Walking {len(symbols)} symbols at {a.pause}s each "
          f"(~{mins:.0f} minutes). Ctrl+C is safe -- each name is stored "
          f"as it arrives; re-run with --resume to pick up where you "
          f"stopped.")
    try:
        walk_universe(store, symbols, pause=a.pause)
    except KeyboardInterrupt:
        print("\nStopped. Everything fetched so far is stored. "
              "Re-run with --resume to continue.")
    report(store)


if __name__ == "__main__":
    main()
