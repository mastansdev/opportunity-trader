"""
==========================================================
Deal Flow -- who bought size yesterday
==========================================================

Operator, 2026-07-25: "can we get Block/Bulk deals from nse ? it may be
useful too". Yes -- NSE publishes all three of these daily, free:

  BULK DEALS    a single client trading more than 0.5% of a company's
                listed shares in one day, on the normal market. Reported
                after the close with client name, buy/sell, quantity and
                average price.

  BLOCK DEALS   a negotiated trade of at least Rs 10 crore (or 5 lakh
                shares) executed in the special 08:45-09:00 window,
                before the normal market opens.

  SHORT SELLING NSE's daily report of securities-wise short positions.

WHY IT MIGHT MATTER, AND WHY IT MIGHT NOT
-----------------------------------------
The honest case FOR: a bulk BUY at above the previous close is a real
institution committing real money and having to keep committing --
large positions are built over days, not minutes. That is a plausible
reason a stock keeps trending, which is exactly what this bot trades.

The honest case AGAINST: the data arrives AFTER the close, so it is
always at least one day stale; a bulk deal is often two counterparties
crossing a block, so a "buyer" implies an equally large seller; and
plenty of bulk deals are promoters, exits, or pledge unwinds that mean
the opposite of conviction.

So this is recorded as CONTEXT, not as a signal, and it does not vote
on any entry. Same discipline as core/trend_structure.py and
core/trade_memory.py: describe first, measure later, wire in only if
the measurement supports it.

BLOCK DEALS HAVE A SECOND, MORE CONCRETE USE: they happen at 08:45-09:00,
before the open. A stock that traded a Rs 200cr block at a discount is
very likely to gap -- and knowing that BEFORE 09:15 is worth more than
any statistical edge.

Everything here fails open: an empty result on any error, and no caller
ever depends on it.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

from core.logger import warn

BULK = "bulk_deals"
BLOCK = "block_deals"
SHORT = "short_selling"


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _first(row, *keys):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    # NSE's column names drift; fall back to a loose match.
    lowered = {str(k).lower().replace("_", "").replace(" ", ""): v
               for k, v in row.items()}
    for key in keys:
        probe = key.lower().replace("_", "").replace(" ", "")
        if probe in lowered and lowered[probe] not in (None, ""):
            return lowered[probe]
    return None


def normalise(row, kind):
    """One NSE deal row -> a flat dict we control the shape of."""
    symbol = _first(row, "symbol", "BD_SYMBOL", "symbol_name")
    qty = _num(_first(row, "quantity", "BD_QTY_TRD", "qty"))
    price = _num(_first(row, "tradePrice", "BD_TP_WATP", "price",
                        "averagePrice"))
    side = str(_first(row, "buySell", "BD_BUY_SELL", "type") or "").strip()
    return dict(
        kind=kind,
        symbol=str(symbol or "").strip().upper(),
        date=str(_first(row, "date", "BD_DT_DATE", "mTIMESTAMP") or "").strip(),
        client=str(_first(row, "clientName", "BD_CLIENT_NAME",
                          "client") or "").strip(),
        side="BUY" if side.upper().startswith("B") else
             ("SELL" if side.upper().startswith("S") else side.upper()),
        qty=qty,
        price=price,
        value=(qty * price) if (qty and price) else None,
    )


def fetch(kind=BULK, days_back=1, folder="data"):
    """
    Recent deals of one kind. Returns a list of normalised dicts, or []
    on any failure -- never raises, never blocks anything.
    """
    to_date = datetime.now()
    from_date = to_date - timedelta(days=max(1, days_back))
    try:
        from nse import NSE
        with NSE(download_folder=folder) as n:
            rows = n.bulkdeals(option_type=kind, fromdate=from_date,
                               todate=to_date) or []
    except Exception as exc:
        warn(f"[DEALS] Could not fetch {kind} ({exc}). Skipped -- nothing "
             f"depends on it.")
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rec = normalise(row, kind)
        if rec["symbol"]:
            out.append(rec)
    return out


def fetch_todays_blocks(folder="data"):
    """
    TODAY's block-deal window (08:45-09:00), via NSE's live endpoint.
    This is the one genuinely pre-market read: a large block crossed at
    a discount very often precedes a gap down, and we can know it before
    09:15.
    """
    try:
        from nse import NSE
        with NSE(download_folder=folder) as n:
            payload = n.blockDeals() or {}
    except Exception as exc:
        warn(f"[DEALS] Live block-deal window unavailable ({exc}).")
        return []
    rows = payload.get("data") or []
    return [normalise(r, BLOCK) for r in rows
            if isinstance(r, dict) and normalise(r, BLOCK)["symbol"]]


def summarise_by_symbol(deals):
    """
    Collapse many deals into one row per symbol:

        {symbol: dict(buy_value, sell_value, net_value, deals, clients)}

    net_value > 0 means more was bought than sold in reported deals.
    Note the caveat in the module docstring: a block deal has a buyer
    AND a seller, so "net" is only meaningful for BULK deals on the
    normal market.
    """
    out = {}
    for d in deals:
        rec = out.setdefault(d["symbol"], dict(
            buy_value=0.0, sell_value=0.0, deals=0, clients=set()))
        rec["deals"] += 1
        if d["client"]:
            rec["clients"].add(d["client"])
        value = d.get("value") or 0.0
        if d["side"] == "BUY":
            rec["buy_value"] += value
        elif d["side"] == "SELL":
            rec["sell_value"] += value
    for rec in out.values():
        rec["net_value"] = rec["buy_value"] - rec["sell_value"]
        rec["clients"] = sorted(rec["clients"])
    return out
