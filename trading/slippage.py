"""
==========================================================
Slippage -- what a paper fill actually costs
==========================================================

WHY THIS EXISTS
---------------
trading/paper_execution.py, in full, was: write a log line, print it,
return {"success": True}. It filled at the EXACT intent price, instantly,
every single time. No spread, no partial fill, no rejection.

Six months of paper results were built on that, and paper results are
the yardstick every rule on this bot is measured against. The exit
study, the 61-session replay, today's book -- all of them assume you got
the price you asked for.

You never do. A buy lifts the offer, a sell hits the bid, and BOTH legs
cost you. That is not a fee, it is the market's actual price for
immediacy, and it does not appear on any contract note.

WHAT DRIVES IT
--------------
Three things, all of which this bot already knows:

  THIN      a wide spread costs more to cross. Day turnover is the
            cheapest available proxy and circuit_monitor already polls
            it for the whole universe.

  FAST      at the open the quote moves between the decision and the
            arrival. Measured on this project, 2026-07-28: the operator
            clicked SUPREMEIND at ~3,385 and filled at 3,472.70, +2.59%.
            That was an extreme case (a dead click, item 26) but the
            direction is the point.

  BIG       a large order eats past the top of book. Not modelled here.
            Position sizes are capped at Rs 2L, which in a liquid name
            is one or two ticks deep. Deliberately left out rather than
            guessed -- see the honesty note below.

HONESTY NOTE
------------
These numbers are ESTIMATES, not measurements. Nobody here has placed a
real order yet. 0.05% on a liquid name and 0.20% on a thin one at the
open are conventional retail figures, not this bot's own data.

From 30 July the operator places real orders. Every real fill should be
compared against the price the bot wanted, and THAT difference should
replace these constants. Until then, an estimate that is roughly right
beats a zero that is certainly wrong.

Direction is always AGAINST you. A buy fills higher, a sell fills lower,
both directions, longs and shorts. Slippage never helps.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import time as _time

from config import (
    ENABLE_PAPER_SLIPPAGE, SLIPPAGE_BASE_PCT, SLIPPAGE_THIN_PCT,
    SLIPPAGE_THIN_TURNOVER_CR, SLIPPAGE_OPENING_MULTIPLE,
    SLIPPAGE_CALM_AFTER,
)

BUY = "BUY"
SELL = "SELL"


def _parse_hhmm(value):
    hh, mm = str(value).split(":")
    return _time(int(hh), int(mm))


CALM_AFTER_T = _parse_hhmm(SLIPPAGE_CALM_AFTER)


def slippage_pct(turnover_cr=None, at_time=None):
    """How far the fill misses, as a fraction of price.

    turnover_cr : the symbol's day turnover in crores, or None if
                  unknown. UNKNOWN IS TREATED AS THIN -- absence of data
                  about liquidity is not evidence of liquidity, and the
                  expensive assumption is the safe one here.
    at_time     : the fill time. Before SLIPPAGE_CALM_AFTER costs more.
    """
    if not ENABLE_PAPER_SLIPPAGE:
        return 0.0

    if turnover_cr is None or turnover_cr < SLIPPAGE_THIN_TURNOVER_CR:
        pct = SLIPPAGE_THIN_PCT
    else:
        pct = SLIPPAGE_BASE_PCT

    if at_time is not None:
        try:
            moment = at_time.time() if hasattr(at_time, "time") else at_time
            if moment < CALM_AFTER_T:
                pct *= SLIPPAGE_OPENING_MULTIPLE
        except (AttributeError, TypeError):
            pass

    return pct


def fill_price(intent_price, side, turnover_cr=None, at_time=None):
    """The price a paper order ACTUALLY fills at.

    Always worse than intent. A BUY fills higher, a SELL fills lower.
    Never raises and never returns a non-positive price -- a cost model
    must not be able to break an order.
    """
    try:
        if not intent_price or intent_price <= 0:
            return intent_price
        pct = slippage_pct(turnover_cr, at_time)
        if pct <= 0:
            return intent_price
        if side == BUY:
            return round(intent_price * (1 + pct), 2)
        return max(0.01, round(intent_price * (1 - pct), 2))
    except Exception:                                      # noqa: BLE001
        return intent_price


def slippage_cost(intent_price, filled_price, qty, side):
    """What the miss cost in rupees. Always >= 0."""
    try:
        if side == BUY:
            return max(0.0, (filled_price - intent_price) * qty)
        return max(0.0, (intent_price - filled_price) * qty)
    except (TypeError, ValueError):
        return 0.0
