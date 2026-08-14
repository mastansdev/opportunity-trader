"""
==========================================================
Universe Builder -- keep the tradeable list honest
==========================================================

The 750-symbol master list was built once and never maintained. Three
problems the operator identified (2026-07-25), all real:

  1. **New listings are missing.** A stock that IPO'd last month simply
     isn't in the file, so the bot cannot see it, ever.
  2. **Dead weight is still in.** Measured on 2026-07-24's real closes:
     **132 of 747 symbols (17.7%) trade below Rs 200** and are rejected
     by the price floor on every single tick -- pure overhead.
  3. **T2T / BE-series stocks may be in the list.** Those cannot be
     traded intraday AT ALL. In PAPER that's a silently invalid trade;
     in LIVE it becomes compulsory delivery, and shorting is impossible.
     This is the one that would actually cost real money.

The fix is NSE's own daily bhavcopy: one file, every trading day, listing
every security that traded, with OHLC, volume, turnover and -- critically
-- the SERIES code. `EQ` means normal rolling settlement (intraday
allowed); `BE`/`BZ` are trade-to-trade.

So the universe becomes self-maintaining: new listings appear the day
they list, delisted names simply stop appearing, and liquidity is
measured rather than assumed.

WHY THE PRICE BAND IS WHAT IT IS (measured, not guessed):

  Lower Rs 200 -- NOT because cheap stocks are quiet; they actually move
      MOST (2.71% median day range vs 2.4-2.7% elsewhere). It's TICK
      GRANULARITY: at Rs 50 one tick is 0.10% of price, at Rs 500 it's
      0.01%. Cheap stocks jump in coarse increments a 0.4% stop cannot
      survive.

  Upper Rs 10,000 -- two independent reasons. Movement declines (1.93%
      median above Rs 10k), and SIZING BREAKS: a Rs 2L position buys
      just 11 shares at Rs 10k, and 1 share of MRF at Rs 1,30,850.
      Whole-share rounding then throws the Rs 800 risk model off by
      30-50%. Not set at Rs 2,000 deliberately -- Rs 2k-10k still gives
      28-69 shares and 2.0-2.4% movement, which is perfectly tradeable;
      cutting there would drop 136 good stocks for no measured benefit.

SAFETY: this NEVER edits the live universe by itself. It writes a
PROPOSAL (data/universe_review.csv) plus a summary, for the operator to
review and apply. Nothing here runs on the trading path.

Run:  py tools/refresh_universe.py

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn

# --- the rules, all measured (see the module docstring) ---
# Price bounds REMOVED 2026-07-29, operator's decision: "Remove cap on
# below 200 & above 10,000 rs as we have moved from MIS to MTF we left
# these two unchanged." Both were MIS-era rules -- tick granularity
# and sizing quantisation inside a same-day round trip -- and neither
# argument survives the move to multi-day MTF holds.
#
# 0 and infinity rather than deleting the checks: the reasons still
# print in SUBSCRIBE_REASON for every other rule, and restoring a
# bound is a one-number change.
#
# THIS ONLY TAKES EFFECT ON A REBUILD. As of tonight the universe is
# still the 668 symbols built under the old bounds. Rebuilding admits
# 193 stocks under Rs 200 and 21 over Rs 10,000 -- a 32% larger,
# entirely untested universe. That is a deliberate act, not a side
# effect of editing this file. MIN_TURNOVER_RS below still applies to
# all of them, so genuinely illiquid scrips stay out either way.
MIN_PRICE = 0.0
MAX_PRICE = float("inf")
# Rs 5cr/day -- real liquidity, not a print. NOT the same rule as
# config.MIN_TURNOVER_RS (Rs 2cr traded so far TODAY, read by the
# engine); one is a property of the stock, the other of the session.
from core.rules import MIN_UNIVERSE_TURNOVER_RS as MIN_TURNOVER_RS
TRADEABLE_SERIES = {"EQ"}      # BE/BZ = trade-to-trade, NO intraday

# ETFs, SGBs and SME scrips trade in the EQ series too, so the series
# check alone lets them through -- the first live run proposed
# SILVERBEES, LIQUIDBEES and SBIFUNDS as "additions" (operator caught
# it, 2026-07-25). We trade COMPANY EQUITY only: an ETF has no sector,
# no earnings, no corporate actions and no relative strength versus its
# peers, so every selection rule in this bot is meaningless for one.
#
# Primary defence is NSE's own ETF/SGB/SME lists (fetched live). The
# name patterns below are a FALLBACK for when that fetch fails -- crude
# but effective, since Indian ETFs are named with remarkable
# consistency.
#
# TIGHTENED 2026-07-25: the first draft matched bare substrings
# ("GOLD", "SILVER", "LIQUID", "NIFTY") and would have wrongly dropped
# GOLDIAM (a jewellery manufacturer) and SILVERLINE -- real companies.
# Because this tool only writes a PROPOSAL a human reviews, a false
# NEGATIVE (an ETF slips into the list for review) costs almost nothing,
# while a false POSITIVE silently deletes a tradeable company. So the
# fallback now fires only on markers no operating company uses.
_ETF_SUFFIXES = ("BEES",)                    # NIFTYBEES, GOLDBEES, LIQUIDBEES
_ETF_TOKENS = ("ETF", "GSEC", "SDL", "SGB")  # unambiguous fund markers


def looks_like_a_fund(symbol):
    """Fallback ETF/SGB detector for when NSE's own list is unavailable.
    Deliberately narrow -- NSE's live list is the primary defence; this
    only catches the names no real company would carry."""
    s = (symbol or "").upper()
    if s.endswith(_ETF_SUFFIXES):
        return True
    return any(t in s for t in _ETF_TOKENS)


def fetch_excluded_symbols(folder="data"):
    """
    Every symbol NSE itself classifies as an ETF, sovereign gold bond, or
    SME scrip. Returns a set (empty on any failure -- the caller then
    falls back to looks_like_a_fund()).
    """
    out = set()
    try:
        from nse import NSE
        with NSE(download_folder=folder) as n:
            for getter in ("listEtf", "listSgb", "listSme"):
                try:
                    payload = getattr(n, getter)() or {}
                except Exception:
                    continue
                rows = payload.get("data") or payload.get("value") or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    sym = (row.get("symbol") or row.get("Symbol")
                           or row.get("SYMBOL"))
                    if sym:
                        out.add(str(sym).strip().upper())
    except Exception as exc:
        warn(f"[UNIVERSE] Could not fetch NSE ETF/SGB/SME lists ({exc}); "
             f"falling back to name patterns.")
    return out

# Bhavcopy column names differ between the legacy and UDIFF formats.
_COL = {
    "symbol": ("SYMBOL", "TckrSymb"),
    "series": ("SERIES", "SctySrs"),
    "close": ("CLOSE", "ClsPric"),
    "volume": ("TOTTRDQTY", "TtlTradgVol"),
    "turnover": ("TOTTRDVAL", "TtlTrfVal"),
}


def _pick(row, key):
    for name in _COL[key]:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def fetch_bhavcopy(date=None, folder="data", quiet=False):
    """Download one day's equity bhavcopy. Returns a list of dicts, or
    [] on any failure (never raises -- this is a pre-market convenience,
    not a trading dependency).

    quiet=True suppresses the warning. The backfill walks back over past
    weekdays and a trading holiday simply has no file, which is normal
    and not worth shouting about -- it decides for itself whether a miss
    is a holiday or a real problem (see tools/build_daily_history.py)."""
    date = date or datetime.now()
    try:
        from nse import NSE
        with NSE(download_folder=folder) as n:
            path = n.equityBhavcopy(date=date, folder=folder)
    except Exception as exc:
        if not quiet:
            warn(f"[UNIVERSE] Bhavcopy fetch failed for "
                 f"{date:%Y-%m-%d} ({exc}). Try an earlier trading day.")
        return []

    rows = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v)
                             for k, v in row.items() if k})
    except Exception as exc:
        warn(f"[UNIVERSE] Could not read {path}: {exc}")
        return []
    return rows


def classify(rows, current_symbols, excluded=None):
    """
    Split every bhavcopy row into keep / reject buckets, and find the
    symbols we're missing entirely. Pure function -- easy to test, no I/O.

    Returns a dict of lists; every rejected row carries a `reason`.
    """
    keep, rejected = [], []
    seen = set()
    excluded = excluded or set()

    for row in rows:
        symbol = _pick(row, "symbol")
        if not symbol:
            continue
        symbol = str(symbol).strip().upper()
        series = str(_pick(row, "series") or "").strip().upper()
        close = _num(_pick(row, "close"))
        volume = _num(_pick(row, "volume")) or 0.0
        turnover = _num(_pick(row, "turnover"))
        if turnover is None and close is not None:
            turnover = close * volume

        # Only judge each symbol once (bhavcopy can carry several series
        # rows for the same name).
        if symbol in seen and series not in TRADEABLE_SERIES:
            continue
        seen.add(symbol)

        rec = dict(symbol=symbol, series=series, close=close,
                   volume=volume, turnover=turnover or 0.0,
                   in_universe=symbol in current_symbols)

        if series not in TRADEABLE_SERIES:
            rec["reason"] = f"series {series or '?'} -- NO INTRADAY (T2T)"
            rejected.append(rec); continue
        # ETFs / SGBs / SME trade in EQ too -- but they are not company
        # equity, and every selection rule here (sector, relative
        # strength, corporate actions, news) is meaningless for a fund.
        if symbol in excluded or looks_like_a_fund(symbol):
            rec["reason"] = "ETF / SGB / SME -- not on our board"
            rejected.append(rec); continue
        if close is None or close <= 0:
            rec["reason"] = "no usable close"
            rejected.append(rec); continue
        if close < MIN_PRICE:
            rec["reason"] = f"price {close:.1f} < {MIN_PRICE:.0f} (tick noise)"
            rejected.append(rec); continue
        if close > MAX_PRICE:
            rec["reason"] = f"price {close:,.0f} > {MAX_PRICE:,.0f} (sizing breaks)"
            rejected.append(rec); continue
        if (turnover or 0) < MIN_TURNOVER_RS:
            rec["reason"] = (f"turnover {(turnover or 0)/1e7:.2f}cr < "
                             f"{MIN_TURNOVER_RS/1e7:.0f}cr (illiquid)")
            rejected.append(rec); continue

        keep.append(rec)

    keep_symbols = {r["symbol"] for r in keep}
    return dict(
        keep=keep,
        rejected=rejected,
        # in our list but no longer qualifies -> propose REMOVE
        to_remove=sorted(
            [r for r in rejected if r["in_universe"]],
            key=lambda r: r["symbol"]),
        # qualifies but we don't have it -> propose ADD (new listings)
        to_add=sorted(
            [r for r in keep if not r["in_universe"]],
            key=lambda r: -(r["turnover"] or 0)),
        # in our list and still fine
        unchanged=[r for r in keep if r["in_universe"]],
        # in our list but absent from the bhavcopy entirely
        missing_from_bhavcopy=sorted(current_symbols - seen),
    )


def write_review(result, path=os.path.join("data", "universe_review.csv")):
    """Write the PROPOSAL for the operator. Never edits the live
    master file."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["action", "symbol", "series", "close", "turnover_cr",
                    "reason"])
        for r in result["to_add"]:
            w.writerow(["ADD", r["symbol"], r["series"],
                        f"{r['close']:.2f}", f"{r['turnover']/1e7:.2f}",
                        "qualifies but missing from our universe"])
        for r in result["to_remove"]:
            w.writerow(["REMOVE", r["symbol"], r["series"],
                        f"{r['close']:.2f}" if r["close"] else "",
                        f"{r['turnover']/1e7:.2f}", r["reason"]])
        for s in result["missing_from_bhavcopy"]:
            w.writerow(["CHECK", s, "", "", "",
                        "not in the bhavcopy at all (delisted/suspended/renamed?)"])
    return path


def summarise(result):
    decision("=" * 58)
    decision("  UNIVERSE REVIEW  (proposal only -- nothing changed)")
    decision("=" * 58)
    decision(f"  Qualify today          : {len(result['keep'])}")
    decision(f"  Already in our universe: {len(result['unchanged'])}")
    decision(f"  PROPOSE ADD (new)      : {len(result['to_add'])}")
    decision(f"  PROPOSE REMOVE         : {len(result['to_remove'])}")
    decision(f"  Not in bhavcopy at all : {len(result['missing_from_bhavcopy'])}")

    t2t = [r for r in result["to_remove"] if "T2T" in r["reason"]]
    if t2t:
        warn(f"  !! {len(t2t)} of our symbols are T2T/BE -- intraday is NOT "
             f"allowed on these: "
             + ", ".join(r["symbol"] for r in t2t[:10])
             + ("..." if len(t2t) > 10 else ""))

    if result["to_add"]:
        decision("  Biggest additions by turnover: "
                 + ", ".join(f"{r['symbol']}({r['turnover']/1e7:.0f}cr)"
                             for r in result["to_add"][:8]))
