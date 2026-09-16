"""
==========================================================
MTF margin -- ask Dhan, never guess
==========================================================

Operator's sizing rule, 2026-07-28:

    "Buy no of shares worth equal to 1 Lakh = mtf power. ex - as of now
     if i want to buy coforge 1686 rs - qty 225 with 99657.31 rs worth."

        COFORGE 1,686 x 225 shares  = Rs 3,79,350 position
        margin Dhan actually blocks = Rs   99,657   (26.27%)

He commits a FIXED Rs 1 lakh of his own margin per position. The share
count falls out of whatever margin THAT stock requires -- and as he
pointed out himself, "some stocks may give more leverage & some none".

    qty = MTF_MARGIN_PER_POSITION_RS / (price x margin_pct)

WHY THIS ASKS DHAN INSTEAD OF USING A TABLE
-------------------------------------------
dhanhq exposes /margincalculator with product_type="MTF" (Funds.
margin_calculator, dhanhq 2.2.0). It returns the same number the order
screen shows. A hard-coded table would be wrong the day Dhan changes a
rate or drops a stock from the MTF list -- and nobody would notice,
because the bot would keep sizing confidently off a stale number. That
is the exact failure mode this project keeps finding: a value that is
silently wrong looks identical to one that is right.

WHAT IT REPLACES
----------------
The old sizing gave Rs 2 lakh to every trade regardless of the stock,
because at a 1% stop the two formulas are algebraically identical:

    2000 / (0.01 x price)  ==  200000 / price

All eighteen of 2026-07-28's trades landed at Rs 1.90-2.00 lakh.
NILKAMAL, which swings 11% in a day, was given the same size as
MANAPPURAM, which swings 2%.

FAILURE POSTURE
---------------
Every failure path leads to LESS leverage, never more:

    call fails            -> own cash only, Rs 1L buys Rs 1L
    stock has no MTF      -> own cash only
    response unparseable  -> own cash only
    margin looks absurd   -> own cash only

Under-leveraging costs opportunity. Over-leveraging on a bad number
costs money, and on MTF it can trigger Dhan's own liquidation.

Author : H&M Opportunity Trader
==========================================================
"""

import threading
import time

from config import (
    MTF_MARGIN_PER_POSITION_RS, MTF_MARGIN_CACHE_SECONDS,
    MTF_FALLBACK_MARGIN_PCT,
)
from core.logger import decision, diagnostic, warn

# A margin rate outside this band is not believable. Indian MTF runs
# roughly 15-50%; anything below 5% would mean 20x leverage, which does
# not exist here, and anything above 100% is nonsense. Either way the
# safe reading is "I do not understand this response".
MIN_SANE_MARGIN_PCT = 0.05
MAX_SANE_MARGIN_PCT = 1.0

# Fields Dhan has used for the blocked amount across API versions.
_MARGIN_FIELDS = (
    "totalMargin", "total_margin", "marginRequired", "margin_required",
    "insufficientBalance", "availableBalance",
)


# How often the running total is printed. Every call already logs its
# own elapsed time; this is the line that answers "is the rebuild slow
# because of this?" without needing to add up a hundred others.
SUMMARY_EVERY = 25


def parse_margin(response, price, quantity):
    """The margin PERCENTAGE out of a /margincalculator response.

    Returns None when the response cannot be trusted -- which the caller
    turns into "use own cash only", never into a guess.
    """
    if not isinstance(response, dict) or not price or not quantity:
        return None

    body = response.get("data") if isinstance(response.get("data"), dict) \
        else response

    amount = None
    for field in _MARGIN_FIELDS[:4]:
        value = body.get(field)
        if value is None:
            continue
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            break
        amount = None

    if not amount:
        return None

    notional = float(price) * int(quantity)
    if notional <= 0:
        return None

    pct = amount / notional
    if not (MIN_SANE_MARGIN_PCT <= pct <= MAX_SANE_MARGIN_PCT):
        return None
    return pct


def shares_for(price, margin_pct, budget=None):
    """How many shares Rs <budget> of margin buys. Always rounds DOWN --
    225.7 becomes 225, never 226, so the commitment can never exceed the
    operator's own ceiling."""
    # 16 Sep 2026: the size he set on the dashboard, with the config
    # constant as the fallback. See core/position_size.py.
    if budget is None:
        try:
            from core.position_size import per_position_rs
            budget = per_position_rs(default=MTF_MARGIN_PER_POSITION_RS)
        except Exception:                                  # noqa: BLE001
            budget = MTF_MARGIN_PER_POSITION_RS
    try:
        per_share = float(price) * float(margin_pct)
        if per_share <= 0:
            return 0
        return max(0, int(budget // per_share))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


class MtfMarginBook:
    """Per-symbol MTF margin rates, asked of Dhan and cached."""

    def __init__(self, calculator=None, cache_seconds=None):
        # calculator(security_id, price, quantity) -> raw API response.
        # Injected so tests never touch the network and so a missing
        # client degrades to own-cash sizing instead of crashing a buy.
        self._calculator = calculator
        self._cache = {}          # symbol -> (pct_or_None, fetched_at)
        self._lock = threading.Lock()
        # What this book has cost in wall-clock time. Read by
        # timing_summary(); see margin_pct().
        self._calls = 0
        self._failures = 0
        self._spent_ms = 0.0
        self._cache_seconds = (MTF_MARGIN_CACHE_SECONDS
                               if cache_seconds is None else cache_seconds)

    # ------------------------------------------------------------

    def margin_pct(self, symbol, security_id, price):
        """This stock's MTF margin as a fraction, or the fallback.

        Cached: margin rates change rarely, and a live call on every
        click would put ~300ms between BUY and the order going out --
        the exact latency being removed everywhere else.
        """
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(symbol)
            if cached and (now - cached[1]) < self._cache_seconds:
                return cached[0] if cached[0] else MTF_FALLBACK_MARGIN_PCT

        # ---- HOW LONG DOES THIS ACTUALLY TAKE? 4 September 2026 ----
        #
        #     "add that timing"                     -- the operator
        #
        # This call sits inside the board rebuild: dashboard/state.
        # _mtf_for() asks it for every ranked row, so a cold cache
        # costs one network round trip per stock. The docstring above
        # says "~300ms" and nobody has ever measured it.
        #
        # It matters right now because his static IP is not renewed
        # and Dhan refuses every call. A refusal that comes back
        # instantly costs nothing; a refusal that TIMES OUT costs the
        # full timeout per stock, and a hundred new stocks would be a
        # hundred timeouts. That is the difference between a rebuild
        # of 50 seconds and one of 344, and it is a measurement, not
        # a theory -- so it is measured.
        #
        # NO NEW LOG LINES. The elapsed time is added to the two lines
        # this already prints, plus one summary per SUMMARY_EVERY
        # calls, so the cost is visible without adding noise to a log
        # that is already too loud.
        pct = None
        started = time.monotonic()
        if self._calculator is not None:
            try:
                response = self._calculator(security_id, price, 1)
                pct = parse_margin(response, price, 1)
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[MTF] {symbol}: margin call failed ({exc}). "
                           f"Sizing on own cash only.")
        took_ms = (time.monotonic() - started) * 1000.0

        with self._lock:
            self._cache[symbol] = (pct, now)
            self._calls += 1
            self._spent_ms += took_ms
            if pct is None:
                self._failures += 1
            calls, failures, spent = self._calls, self._failures, self._spent_ms

        if calls % SUMMARY_EVERY == 0:
            warn(f"[MTF] {calls} margin calls this session, {failures} "
                 f"unanswered, {spent / 1000.0:.1f}s spent waiting "
                 f"({spent / calls:.0f}ms each). This is REBUILD time -- "
                 f"the board asks once per stock and caches for "
                 f"{self._cache_seconds / 3600:.0f}h.")

        if pct is None:
            warn(f"[MTF] {symbol}: no usable MTF margin from Dhan -- "
                 f"buying with own cash only (no leverage). "
                 f"[{took_ms:.0f}ms]")
            return MTF_FALLBACK_MARGIN_PCT

        decision(f"[MTF] {symbol}: margin {pct * 100:.2f}% "
                 f"(about {1 / pct:.1f}x leverage). [{took_ms:.0f}ms]")
        return pct

    def leverage_for(self, symbol, security_id, price):
        """Can he buy this ON MTF, and at what leverage?

        ==========================================================
            "only trade in best set of stocks in MTF"
                                -- operator, 4 August 2026
        ==========================================================

        margin_pct() answers a sizing question and deliberately never
        fails: when Dhan quotes nothing it returns 1.0, meaning "buy it
        with your own cash". That is the right answer for the engine,
        which still wants to place the order.

        It is the WRONG answer for the ranker, which is choosing what
        to put in front of him. He trades MTF. A stock Dhan will not
        margin is not a candidate -- ranking it hands him a name he
        cannot buy the way he buys, and he only finds out at the click.

        So this asks the same cached question and reports the answer
        plainly instead of papering over it:

            {"eligible": bool, "leverage": float or None,
             "margin_pct": float or None}

        eligible False means Dhan quoted no MTF margin. It does NOT
        mean the stock is bad -- he can still buy it with cash from the
        platform. It means the bot should not be recommending it, since
        the whole book runs on MTF.
        """
        pct = self.margin_pct(symbol, security_id, price)
        # margin_pct() returns the fallback -- 1.0, full cash -- both
        # when Dhan refused and when there is no client at all. Either
        # way there is no leverage on offer, and "no leverage" is the
        # thing the ranker has to act on.
        if not pct or pct >= MTF_FALLBACK_MARGIN_PCT:
            return {"eligible": False, "leverage": None, "margin_pct": None}
        return {"eligible": True,
                "leverage": round(1.0 / pct, 1),
                "margin_pct": pct}

    def quantity_for(self, symbol, security_id, price, budget=None):
        """Shares to buy for one position. THE method the engine calls.

        Returns (qty, margin_pct, position_value) so the caller can log
        all three -- the operator should be able to see the leverage he
        actually got, not just the share count.
        """
        pct = self.margin_pct(symbol, security_id, price)
        qty = shares_for(price, pct, budget)
        return qty, pct, round(qty * float(price or 0), 2)

    def timing_summary(self):
        """What asking Dhan has cost this session.

            {"calls": 41, "failures": 41, "spent_ms": 12300.0,
             "avg_ms": 300.0}

        avg_ms is None before the first call -- an average over
        nothing is not a number.
        """
        with self._lock:
            calls, failures = self._calls, self._failures
            spent = self._spent_ms
        return {"calls": calls, "failures": failures, "spent_ms": spent,
                "avg_ms": (spent / calls) if calls else None}

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._calls = 0
            self._failures = 0
            self._spent_ms = 0.0


def dhan_margin_calculator(dhan_client, exchange_segment="NSE_EQ"):
    """Wraps dhanhq's Funds.margin_calculator into the shape this module
    wants. Kept here rather than in main.py so the API surface this
    depends on is visible in one place.

    product_type="MTF" is a real dhanhq constant (dhanhq.py:42) -- the
    same product the operator's order screen uses.
    """
    def _call(security_id, price, quantity):
        return dhan_client.margin_calculator(
            security_id=str(security_id),
            exchange_segment=exchange_segment,
            transaction_type="BUY",
            quantity=int(quantity),
            product_type="MTF",
            price=float(price),
        )
    return _call
