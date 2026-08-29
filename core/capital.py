"""
==========================================================
How much may be deployed, and how much never moves
==========================================================

    "i do not want to keep the limit if the stocks are having an
     excellent results & we keep 2-3 positions . which will get lost
     right? market is willing to give us money but we keep the gates
     locked. keep at least 1 lakh free cash & positions can be build
     on remaining ."
                                -- operator, 7 August 2026

WHY THIS EXISTS
---------------
config.MAX_OPEN_POSITIONS was 3. With Rs 4.31 lakh in the account and
Rs 30,000 of own cash per position, that left Rs 3.4 lakh sitting
idle -- not "free cash for the next stock", just money that could
never be used no matter what the day offered.

A count is the wrong control. On a heavy results morning the right
number of positions is however many good results there are; on a dead
Tuesday it is zero. What must never change is the cash he keeps back.

So the gate is CASH, not COUNT.

    deployable = capital - FREE_CASH_FLOOR
    slots      = deployable / OWN_CASH_PER_POSITION

At Rs 4,31,116 that is 11 positions rather than 3.

WHAT THIS DOES NOT PROTECT AGAINST
----------------------------------
Correlation. Eleven positions opened on the same morning, for the
same reason -- "good results" -- in a market that then gaps down are
not eleven independent bets. They are one bet made eleven times.

With MTF at 4x, eleven positions carry roughly Rs 13 lakh of stock
against Rs 4.3 lakh of capital. A 3% fall across the book is about
Rs 39,000, which is 9% of everything he has. The per-trade stop of
Rs 1,500 does not save him there, because a gap opens THROUGH a stop
rather than at it.

That is stated here, in the module that opens the gate, because he
should not have to discover it on the morning it happens. The gate is
his decision and it is a reasonable one. The exposure it creates is a
number he is entitled to see.

Author : H&M Opportunity Trader
==========================================================
"""

# ---- RETIRED 20 AUGUST 2026, ON HIS INSTRUCTION. ----
#
#     "no 1 lakh free cash rule"
#
# It was his own, from 8 August -- "keep at least 1 lakh free cash &
# positions can be build on remaining" -- and it was wired in here
# exactly as he said it.
#
# What it does at today's balance is the reason he removed it. The
# seat count is (capital - floor) / Rs 30,000, and his free cash
# moves with his own manual trades:
#
#     Rs 1,52,081 free   ->  1 seat with the floor,  5 without
#     Rs 1,20,000 free   ->  0 seats with the floor
#
# So on an ordinary day the floor was not reserving a lakh, it was
# closing the book. Set to 0 rather than deleted: the arithmetic that
# reads it is unchanged, and restoring the reserve is one number.
#
# WHAT STILL BOUNDS THE BOOK, so this is not "no limits":
#   OWN_CASH_PER_POSITION_RS   Rs 30,000 of his own cash per position
#   WORKING_MAX_POSITIONS      5, while the selector is unproven
#   ABSOLUTE_MAX_POSITIONS     25, against a bad capital read
#   config.DAILY_MAX_LOSS_RS   Rs 12,000, the day's stop
FREE_CASH_FLOOR_RS = 0.0

# Own cash committed per position. MTF supplies the rest, and how much
# it supplies depends on the stock's own margin percentage.
OWN_CASH_PER_POSITION_RS = 30_000.0

# A sanity ceiling so a bad capital read cannot open 400 slots. Not a
# trading rule -- a guard against a broker API returning nonsense.
ABSOLUTE_MAX_POSITIONS = 25

# ==========================================================
# HOW MANY THE BOOK MAY ACTUALLY HOLD.  10 August 2026.
# ==========================================================
#
#     "Capital rule: hold while it works, never block all funds"
#
# The cash rule above says 11 at Rs 4.31 lakh. Measured on 3-5 August:
#
#     3 slots      9 trades   11% win   Rs -10,715
#    11 slots     33 trades   24% win   Rs -26,018
#
# so arming it in full multiplied a losing edge. That is why
# ENABLE_CASH_SIZED_BOOK is False.
#
# BUT MAX_OPEN_POSITIONS = 3 IS ITS OWN PROBLEM, AND HIS ORIGINAL ONE:
# one overnight hold leaves two seats, and Rs 3.4 lakh sits idle no
# matter what the morning offers. Both extremes are wrong.
#
# So the ceiling is a THIRD number, deliberately between them. It rises
# with cash, as he asked, and it cannot reach eleven while the selector
# is unproven. Raise it as the hit rate earns it -- that is a decision
# with evidence behind it, not a constant I picked.
#
# ---- RAISED TO EIGHT. 29 August 2026. ----
#
#     "i want bot to utilise the capital to max & book the profits"
#                                              -- operator
#
# His real Dhan balance read Rs 246,592.89 at startup, so the cash
# supports exactly eight positions at OWN_CASH_PER_POSITION_RS. At
# five, Rs 96,593 sat idle every session -- the same "Rs 3.4 lakh sits
# idle" complaint the note above was written for, one number down.
#
# WHAT THIS DOES NOT CHANGE IS THE DOWNSIDE, and that is why it is
# safe to do while the selector is still unproven:
#
#     seats   own cash used   left free   worst-case day
#         5         150,000      96,593         -12,000
#         6         180,000      66,593         -12,000
#         7         210,000      36,593         -12,000
#         8         240,000       6,593         -12,000
#
# config.DAILY_MAX_LOSS_RS halts the session at Rs 12,000 whatever the
# seat count, so eight seats cannot lose more in a day than five can.
# It buys more OPPORTUNITIES at the same risk, which is exactly what
# the 8 August measurement said NOT to do -- but that measurement
# multiplied a losing edge with no daily halt in front of it, and the
# halt is what makes this a different question.
#
# THE ONE COST, SAID PLAINLY: eight seats leave Rs 6,593 free. MTF
# margin is re-quoted per stock and can move intraday, so a shortfall
# has almost no buffer. Seven seats leave Rs 36,593 and still deploy
# 85% of the account. He asked for max; seven is one edit away.
WORKING_MAX_POSITIONS = 8


def slots(capital_rs, held=0, floor_rs=None, per_position_rs=None):
    """How many NEW positions may be opened right now.

    Returns {"slots", "deployable", "free_after", "why"} -- never a
    bare number, because a refusal he cannot read is a refusal he
    cannot act on.
    """
    try:
        capital = float(capital_rs or 0.0)
    except (TypeError, ValueError):
        capital = 0.0
    floor = FREE_CASH_FLOOR_RS if floor_rs is None else float(floor_rs)
    per = (OWN_CASH_PER_POSITION_RS if per_position_rs is None
           else float(per_position_rs))
    held = int(held or 0)

    deployable = capital - floor
    if deployable < per:
        return {"slots": 0, "deployable": max(deployable, 0.0),
                "free_after": capital,
                "why": (f"Rs {capital:,.0f} in the account and Rs "
                        f"{floor:,.0f} must stay free -- that leaves "
                        f"less than one position")}

    total = int(deployable // per)
    total = min(total, ABSOLUTE_MAX_POSITIONS)
    # ---- THE WORKING CEILING. See the note at the top. ----
    # Cash says how many he COULD hold; this says how many the bot may
    # hold while the selector is still unproven. Both must be satisfied.
    capped_by_rule = total > WORKING_MAX_POSITIONS
    total = min(total, WORKING_MAX_POSITIONS)
    open_now = max(total - held, 0)
    free_after = capital - (held + open_now) * per

    return {"slots": open_now, "total": total, "deployable": deployable,
            "capped_by_rule": capped_by_rule,
            "free_after": free_after,
            "why": (f"Rs {capital:,.0f} capital, Rs {floor:,.0f} held back, "
                    f"Rs {per:,.0f} per position -> {total} positions "
                    f"({held} held, {open_now} free)")}


def exposure(positions, capital_rs):
    """What the book is actually carrying, and what a gap would cost.

    `positions` is an iterable of dicts with "qty" and "entry_price".
    """
    value = 0.0
    n = 0
    for position in (positions or []):
        try:
            qty = float((position or {}).get("qty") or 0)
            price = float((position or {}).get("entry_price") or 0)
        except (TypeError, ValueError):
            continue
        if qty > 0 and price > 0:
            value += qty * price
            n += 1
    try:
        capital = float(capital_rs or 0.0)
    except (TypeError, ValueError):
        capital = 0.0

    leverage = (value / capital) if capital > 0 else 0.0
    return {
        "positions": n,
        "stock_value": value,
        "capital": capital,
        "leverage": round(leverage, 2),
        # What a market-wide gap costs, since a gap opens THROUGH the
        # stops rather than at them.
        "gap_2pct": round(value * 0.02, 0),
        "gap_3pct": round(value * 0.03, 0),
        "gap_5pct": round(value * 0.05, 0),
    }
