"""
==========================================================
FII / DII flows -- who is actually buying
==========================================================

config.py has carried FII_NET_CR = None and DII_NET_CR = None since the
dashboard was built. They were meant to be typed in by hand and never
were, so the Market Intelligence tile has read "set in config (EOD)"
every session since.

Operator, 2026-07-28: "they also play imp role, pls fix them too with
working conditions."

WHAT THIS IS AND IS NOT
-----------------------
NSE publishes FII and DII cash-market net figures once a day, AFTER the
close. There is no intraday feed of this anywhere -- the provisional
number lands in the evening. So this tile can only ever say what the
institutions did YESTERDAY (or, after the close, today).

That is still worth having: sustained FII selling is the backdrop to a
lot of weak sessions. But it is a CONTEXT number, not a trigger, and the
panel labels it with its own date so a stale figure can never be
mistaken for a live one -- which is exactly the failure this whole
dashboard was built to avoid.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn

CACHE_PATH = os.path.join("data", "market_flows.json")

# The nse package has renamed this over versions; try each.
# The nse package renames this between versions and none of the four
# names guessed on 2026-07-28 existed. Rather than guess a fifth time,
# ANY method whose name mentions fii/dii is tried, and the ones actually
# available are logged so the real name is visible once.
NSE_METHODS = ("fiiDiiTradeReact", "fii_dii", "fiiDii", "fiidiiTradeReact",
               "fiiDiiData", "fii_dii_data", "fiidii")


def _num(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("₹", "").strip()
    if not text or text in ("-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group()) if m else None


def parse_rows(rows):
    """NSE returns a list like:
        [{"category": "DII **", "date": "28-Jul-2026",
          "buyValue": "12345.67", "sellValue": "11000.00",
          "netValue": "1345.67"}, ...]
    Returns {"fii_cr": float|None, "dii_cr": float|None, "as_of": str}.
    """
    out = {"fii_cr": None, "dii_cr": None, "as_of": None}
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category") or row.get("Category") or "").upper()
        net = _num(row.get("netValue") or row.get("net_value")
                   or row.get("Net") or row.get("net"))
        date = str(row.get("date") or row.get("Date") or "").strip()
        if date and not out["as_of"]:
            out["as_of"] = date
        if net is None:
            continue
        if "FII" in cat or "FPI" in cat:
            out["fii_cr"] = round(net, 2)
        elif "DII" in cat:
            out["dii_cr"] = round(net, 2)
    return out


class MarketFlows:
    """Fetches once at startup and again after the close. Cached to disk
    so a restart shows yesterday's number instead of a dash."""

    def __init__(self, fetcher=None, cache_path=CACHE_PATH):
        self._fetcher = fetcher or self._fetch_nse
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._data = self._load_cache()
        self._error = None
        self._fetched_at = None

    # ------------------------------------------------------------

    @staticmethod
    def _fetch_nse():
        from nse import NSE
        with NSE(download_folder="data") as n:
            for name in NSE_METHODS:
                fn = getattr(n, name, None)
                if callable(fn):
                    return fn()
            # Nothing matched. Find anything fii/dii-ish and TRY it,
            # then report what the package really offers so the next
            # attempt is informed rather than another guess.
            candidates = [m for m in dir(n)
                          if not m.startswith("_")
                          and ("fii" in m.lower() or "dii" in m.lower())]
            for name in candidates:
                fn = getattr(n, name, None)
                if callable(fn):
                    decision(f"[FLOWS] Using nse.{name}() for FII/DII.")
                    try:
                        return fn()
                    except Exception:                      # noqa: BLE001
                        continue
            raise AttributeError(
                "no FII/DII method on the nse package. It offers: "
                + ", ".join(sorted(m for m in dir(n)
                                   if not m.startswith("_"))[:40]))

    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, data):
        try:
            d = os.path.dirname(self.cache_path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ------------------------------------------------------------

    def refresh(self):
        """Never raises. On failure the cached figure stays on screen and
        the error is surfaced, because a blank tile and a broken feed
        must not look the same."""
        try:
            parsed = parse_rows(self._fetcher())
        except Exception as exc:                           # noqa: BLE001
            self._error = str(exc)[:140]
            warn(f"[FLOWS] FII/DII fetch failed ({self._error}). "
                 f"Showing the last figure held.")
            return None
        if parsed["fii_cr"] is None and parsed["dii_cr"] is None:
            self._error = "feed returned no FII/DII rows"
            warn("[FLOWS] FII/DII feed returned nothing usable.")
            return None
        parsed["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock:
            self._data = parsed
            self._error = None
            self._fetched_at = datetime.now()
        self._save_cache(parsed)
        decision(f"[FLOWS] FII {parsed['fii_cr']} cr / DII "
                 f"{parsed['dii_cr']} cr (as of {parsed['as_of']}).")
        return parsed

    def snapshot(self):
        with self._lock:
            d = dict(self._data)
        fii, dii = d.get("fii_cr"), d.get("dii_cr")
        return {
            "available": fii is not None or dii is not None,
            "fii_cr": fii, "dii_cr": dii,
            "as_of": d.get("as_of"),
            "fetched_at": d.get("fetched_at"),
            "error": self._error,
            # NSE publishes this after the close, so it is ALWAYS about a
            # completed session. Labelled so a stale number can never be
            # read as a live one.
            "note": ("EOD figure, published after the close"
                     if fii is not None or dii is not None
                     else "not fetched yet"),
        }
