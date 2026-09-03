"""
==========================================================
Transaction cost model -- intraday AND overnight/MTF
==========================================================

Estimates the real brokerage + statutory charges on a completed equity
round trip. Used for DISPLAY: the dashboard shows gross P&L, the
charges, and the real NET-of-cost P&L, so a Rs 30 "profit" is honestly
shown as the net LOSS it becomes once costs are paid (the operator's own
point, RELIANCE/HDFCBANK partials, 2026-07-24).

WHY THIS WAS REWRITTEN, 2026-07-28
----------------------------------
The old model was intraday-only, hard-coded. Its own header said so:
"Transaction cost model -- intraday equity (MIS)". The operator had
already moved to MTF, so every figure on the dashboard was wrong for any
position held past the close.

Then the operator caught the opposite error in my correction:

    "do not consider mtf charges right away on closed positions too ....
     pls check with dhan / resources for intraday closing even in
     trading mtf segment first"

He was right. I had applied MTF interest to trades that lived between 6
seconds and 37 minutes. Interest does not start until T+1.

WHAT WAS VERIFIED AT SOURCE
---------------------------
Zerodha's STT page and MTF FAQ, 28 Jul 2026:

    Equity INTRADAY   STT 0.025%  SELL side only
    Equity DELIVERY   STT 0.1%    BOTH buy and sell sides
    MTF interest      applied FROM T+1 until the stock is sold
    MTF pledge        stock auto-pledged on buy, unpledged on sell,
                      ~Rs 15 + GST each way, per ISIN, per day

So a same-day round trip pays NO interest and NO extra STT. Only a
position that actually crosses a session pays the overnight costs.

STILL UNRESOLVED -- READ BEFORE TRUSTING THE OVERNIGHT NUMBER
-------------------------------------------------------------
Whether a same-day MTF exit is charged INTRADAY or DELIVERY STT is not
stated plainly anywhere public. Zerodha says MTF trades are "treated
like any other delivery trade (CNC)", but that line is about P&L and
capital-gains reporting, not STT. Dhan's page says MTF is not for
intraday at all.

Nobody here has seen a real MTF contract note. Until the operator places
one live MTF buy and sell (planned 30 Jul) and reads the STT line, the
same-day path uses INTRADAY rates -- which is what the operator
instructed, and is the honest default given a same-day trade never
reaches delivery settlement.

Charge sides:
  - Brokerage: both legs, Rs 20 or 0.03% per order, whichever LOWER.
  - STT: intraday = SELL leg only; delivery/overnight = BOTH legs.
  - Exchange txn + SEBI: both legs, unchanged either way.
  - Stamp duty: BUY leg only.
  - GST: 18% on (brokerage + exchange txn + SEBI).
  - MTF interest: funded amount x daily rate x nights held. T+1 onward.
  - Pledge/unpledge: flat, per stock, each way. Hurts small positions
    most because it does not scale with size.

Approximation note: partial-exit records are each treated as their own
round trip, so a trade that was trimmed once slightly over-counts the
buy-side brokerage/stamp. Conservative, and fine for a display estimate.

Author : H&M Opportunity Trader
==========================================================
"""

from config import (
    BROKERAGE_PER_ORDER_RS, BROKERAGE_PCT, STT_SELL_PCT,
    EXCHANGE_TXN_PCT, SEBI_CHARGES_PCT, STAMP_DUTY_BUY_PCT, GST_PCT,
    STT_DELIVERY_PCT, STAMP_DUTY_DELIVERY_PCT,
    MTF_INTEREST_DAILY_PCT, MTF_LEVERAGE, MTF_PLEDGE_FEE_RS,
)


def _brokerage(turnover):
    """Rs 20 an order, flat.

    ---- WHAT DHAN ACTUALLY CHARGES. 3 September 2026. ----
    This was min(Rs 20, 0.03% of turnover), which is the published
    "whichever is lower" wording -- but on his account it is not what
    is billed. His words:

        "dhan charges us 20 rs for buying & 20rs for selling == 40rs
         only for broker irrespective of qty"

    Irrespective of qty. The min() only ever bit below Rs 66,667 of
    turnover, which is exactly the size the bot trades now that a slot
    is Rs 15,000 at 4x -- so every trade was being costed Rs 2-4 light
    on each leg, understating a day of 20 trades by up to Rs 80.

    BROKERAGE_PCT is left in config because the delivery/other plans
    still quote it; nothing reads it here any more.
    """
    return BROKERAGE_PER_ORDER_RS


def round_trip_charges(entry_price, exit_price, qty, direction="LONG",
                       nights_held=0):
    """Total estimated charges for one completed round trip.

    nights_held = 0 (the default) means the position opened and closed
    in the SAME session: intraday STT, no interest, no pledge fee.
    Anything above 0 applies the delivery/MTF costs.

    Returns 0.0 for a degenerate record rather than raising.
    """
    if not entry_price or not exit_price or not qty or qty <= 0:
        return 0.0

    entry_turnover = entry_price * qty
    exit_turnover = exit_price * qty

    if direction == "SHORT":
        sell_turnover, buy_turnover = entry_turnover, exit_turnover
    else:
        sell_turnover, buy_turnover = exit_turnover, entry_turnover

    brokerage = _brokerage(entry_turnover) + _brokerage(exit_turnover)
    exchange = EXCHANGE_TXN_PCT * (entry_turnover + exit_turnover)
    sebi = SEBI_CHARGES_PCT * (entry_turnover + exit_turnover)

    if nights_held > 0:
        # Delivery treatment. STT is 0.1% on BOTH sides, not just the
        # sell -- four times the intraday rate on one leg and a whole
        # extra leg on top.
        stt = STT_DELIVERY_PCT * (entry_turnover + exit_turnover)
        stamp = STAMP_DUTY_DELIVERY_PCT * buy_turnover
    else:
        stt = STT_SELL_PCT * sell_turnover
        stamp = STAMP_DUTY_BUY_PCT * buy_turnover

    gst = GST_PCT * (brokerage + exchange + sebi)
    total = brokerage + stt + exchange + sebi + stamp + gst

    if nights_held > 0:
        total += mtf_carry_cost(entry_turnover, nights_held)

    return total


def mtf_carry_cost(position_value, nights_held, leverage=None):
    """Interest on the FUNDED portion, plus pledge and unpledge fees.

    Only the borrowed part accrues interest. At 4x leverage the operator
    puts up 25% and Dhan funds 75%, so a Rs 2,00,000 position borrows
    Rs 1,50,000 -- not Rs 2,00,000.

    Interest runs from T+1, so nights_held is the number of nights the
    position was actually carried, not the number of days it was open.
    """
    if not position_value or nights_held <= 0:
        return 0.0
    lev = leverage or MTF_LEVERAGE
    if lev and lev > 1:
        funded = position_value * (1.0 - 1.0 / lev)
    else:
        funded = 0.0
    interest = funded * MTF_INTEREST_DAILY_PCT * nights_held
    # Pledged on buy, unpledged on sell. Flat, so it bites small
    # positions hardest -- exactly the ones the dashboard makes look
    # marginally profitable.
    pledge = MTF_PLEDGE_FEE_RS * 2 * (1 + GST_PCT)
    return interest + pledge


def nights_between(entry_time, exit_time):
    """How many nights a position was actually carried.

    Same-session round trip -> 0, so no interest and no pledge fee.
    Returns 0 rather than raising on anything unparseable: a cost
    estimate must never break a P&L display.
    """
    try:
        return max(0, (exit_time.date() - entry_time.date()).days)
    except (AttributeError, TypeError):
        return 0
