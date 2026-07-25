"""
==========================================================
Transaction cost model -- intraday equity (MIS)
==========================================================

Estimates the real brokerage + statutory charges on a completed
intraday equity round trip (buy leg + sell leg), Dhan/discount-
broker rates (config.py's transaction-cost block). Used purely for
DISPLAY -- the dashboard shows gross P&L, the charges, and the real
NET-of-cost P&L, so a Rs 30 "profit" is honestly shown as the net
LOSS it becomes once costs are paid (the operator's own point,
RELIANCE/HDFCBANK partials, 2026-07-24).

Charge sides:
  - Brokerage: both legs, Rs 20 or 0.03% per order, whichever LOWER.
  - STT: SELL leg only (0.025% intraday). A LONG sells at exit; a
    SHORT sells at entry.
  - Exchange txn + SEBI: both legs.
  - Stamp duty: BUY leg only (0.003%). LONG buys at entry, SHORT
    buys (covers) at exit.
  - GST: 18% on (brokerage + exchange txn + SEBI).

Approximation note: partial-exit records are each treated as their
own round trip, so a trade that was trimmed once slightly
over-counts the buy-side brokerage/stamp (one real buy, counted per
partial). Conservative (overstates cost a touch) and fine for a
display estimate.

Author : H&M Opportunity Trader
==========================================================
"""

from config import (
    BROKERAGE_PER_ORDER_RS, BROKERAGE_PCT, STT_SELL_PCT,
    EXCHANGE_TXN_PCT, SEBI_CHARGES_PCT, STAMP_DUTY_BUY_PCT, GST_PCT,
)


def _brokerage(turnover):
    return min(BROKERAGE_PER_ORDER_RS, BROKERAGE_PCT * turnover)


def round_trip_charges(entry_price, exit_price, qty, direction="LONG"):
    """Total estimated charges for one completed intraday round
    trip. Returns 0.0 for a degenerate (zero qty / non-positive
    price) record rather than raising."""
    if not entry_price or not exit_price or not qty or qty <= 0:
        return 0.0

    entry_turnover = entry_price * qty
    exit_turnover = exit_price * qty

    if direction == "SHORT":
        sell_turnover, buy_turnover = entry_turnover, exit_turnover
    else:
        sell_turnover, buy_turnover = exit_turnover, entry_turnover

    brokerage = _brokerage(entry_turnover) + _brokerage(exit_turnover)
    stt = STT_SELL_PCT * sell_turnover
    exchange = EXCHANGE_TXN_PCT * (entry_turnover + exit_turnover)
    sebi = SEBI_CHARGES_PCT * (entry_turnover + exit_turnover)
    stamp = STAMP_DUTY_BUY_PCT * buy_turnover
    gst = GST_PCT * (brokerage + exchange + sebi)

    return brokerage + stt + exchange + sebi + stamp + gst
