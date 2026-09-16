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
# ---- FOUR SEATS WAS THE BINDING CONSTRAINT. 3 Sep 2026. ----
#
#     "okay lets try this too, change slot to 15000"
#
# MEASURED by replaying today's own board (data/decisions.db, every
# price as the bot saw it, 27-minute holds, seats the only variable):
#
#     seats  slot     capital     net      per 1 lakh
#       4    30,000   120,000   -3,053       -2,544
#       8    30,000   240,000   +8,801       +3,667
#       8    10,000    80,000   +2,662       +3,327
#      13    30,000   390,000  +21,616       +5,543
#      20    30,000   600,000  +21,014       +3,502
#
# SEATS move the result, slot size barely does: at a fixed seat count,
# dropping the slot from 30,000 to 10,000 changes the return per lakh
# by a few percent. Four seats loses at every slot size; eight makes
# money at every slot size. Past thirteen it stops helping -- only so
# many stocks qualify in a day.
#
# His book was FULL for 290 of 306 minutes today -- 95% of the
# session. Every late entry was bought within 0-2 minutes of a seat
# freeing: RAYMOND 0 min after FINCABLES closed, WHEELS 0 min after
# SOLARINDS, BAJAJCON 1 min after WHEELS. The bot was never slow. It
# had nowhere to put anything.
#
# So 15,000 buys eight seats out of the same Rs 1.23 lakh, at half the
# size each. Fewer rupees per trade, at prices that are actually
# there: entries averaged 0.95% worse than first sighting today, and
# every expensive one was a long wait.
#
# THE REPLAY DOES NOT MODEL THE EXIT RULE. It holds everything 27
# minutes. Re-run it once liveness() refuses a fading stock and the
# 15-minute exit stops cutting winners -- eight may not still be the
# right number when winners are held.
# ---- RS 50,000 A SLOT. 4 September 2026. ----
#
#     "if 5 Lakh give 25 seats, then change capital alloted from 30 K
#      to 50K"                                    -- the operator
#
# PAPER became a fixed Rs 5 lakh the same morning, and Rs 15,000 a
# slot gave 25 seats -- more concurrent positions than the selector
# has ever been shown to justify, and 25 lots of brokerage.
#
# At Rs 50,000 of margin and 4x, a position is Rs 2,00,000 of stock
# and the 3% entry stop costs Rs 6,000. He was shown that the
# Rs 12,000 daily cap therefore ends the day after TWO stop-outs,
# against 6.7 at the old slot.
#
# ---- AND IT FOLLOWS THE SWITCH, NOT THE MODE. 10 September 2026. ----
# The slot is Rs 50,000 in PAPER, where the purse is a fixed Rs 5 lakh
# and the point is to test behaviour freely -- "bot/we need to trade
# as & when opportunity triggers, so in paper mode thats safe to test
# the behaviour of bot trading".
#
# LIVE is Rs 15,000, which is where he moved it on 3 September because
# the book was full for 290 of the session's 306 minutes. His real
# balance is about Rs 1.2 lakh: at Rs 50,000 that is TWO seats and,
# against the Rs 12,000 live cap, two stop-outs to the end of the day.
#
# WHY THIS STOPPED BEING A CONSTANT. Until 10 September the slot was
# chosen HERE, at import, from config.TRADING_MODE -- which is frozen
# at "PAPER" and which the switch does not move. So clicking ON (real
# orders) left the slot at the PAPER Rs 50,000 and sized every real
# position more than three times too big. THE SWITCH IS THE WHOLE
# ANSWER (his rule, 6 Sep): the engine reads execution.live at sizing
# time and passes the matching slot to slots() below -- see
# core/engine.py's slot sizing. OWN_CASH_PER_POSITION_RS stays the
# PAPER default because the bot always comes up OFF, so slots() called
# with no per_position_rs still sizes a paper book.
# ---- ONE SLOT, BOTH SIDES OF THE SWITCH. 14 September 2026. ----
#
#     "what ever we do in this bot is same for both live & paper modes.
#      no distinction at all. even capital allocation also u can change
#      from 15K to what ever paper mode we are doing (50K) ... no dual
#      channels/settings/processes at all. unified process in complete
#      bot. only distinguish thing is switch ON = trades in dhan & real
#      money ; OFF = Paper Mode & Paper Capital"
#                                          -- the operator
#
# Until today this was Rs 50,000 in paper and Rs 15,000 live, which is
# exactly the dual setting he is refusing: a paper session that proves
# a behaviour then behaves differently the moment the switch goes ON
# proves nothing. The switch decides WHOSE MONEY and nothing else.
#
# WHAT THIS CHANGES, said plainly. A live position becomes about 3.3x
# bigger. On his real balance near Rs 1,00,000 that is TWO seats rather
# than six, and at 4x MTF a seat is about Rs 2,00,000 of stock, so the
# 2.5% stop costs about Rs 5,000. Against DAILY_MAX_LOSS_RS = 12,000
# the day ends after roughly two stop-outs. That is the trade he is
# choosing: fewer, larger positions that behave identically to the ones
# he has been watching in paper.
OWN_CASH_PER_POSITION_RS = 50_000.0


def own_cash_per_position(live=None):
    """Rupees of his own cash per seat. The SAME on both sides.

    `live` is still accepted so the caller need not change and so the
    signature still says out loud that this question was once answered
    two different ways. It is ignored: see the note above.

    ---- HE SETS IT ON THE DASHBOARD NOW. 16 September 2026. ----
    "reduce per position to 25000 so i get 3 seats on my current capital
     & why do not u gave option to select capital allocation on
     dashboard." The constant below is the fallback for when nothing has
     been set; core/position_size.py holds the live figure.
    """
    try:
        from core.position_size import per_position_rs
        return per_position_rs(default=OWN_CASH_PER_POSITION_RS)
    except Exception:                                      # noqa: BLE001
        return OWN_CASH_PER_POSITION_RS

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
# has almost no buffer.
#
# ---- CAPITAL DECIDES THE SEATS, NOTHING ELSE. 31 Aug 2026. ----
#
#     "yes bot needs to use complete capital & the seats depends on
#      available capital , no minimum & no maximum seat count"
#                                         -- the operator
#
# So the working ceiling is lifted to meet ABSOLUTE_MAX_POSITIONS,
# which stays as what it has always been: a guard against a BAD
# CAPITAL READ, not a view on the strategy. A corrupt balance of ten
# crore must not open three hundred positions.
#
# WHAT THIS CHANGES TODAY: nothing. Rs 1,46,593 divided by Rs 30,000
# is four seats, and four is what slots() already returns. It binds
# only once the account clears Rs 2,40,000.
#
# WHAT IT WILL CHANGE, said once and then left alone: the recorded
# book is 139 trades at minus Rs 99,317 net of charges. More seats
# multiply whatever the selector produces, in either direction. He
# has been told; the instruction stands.
WORKING_MAX_POSITIONS = ABSOLUTE_MAX_POSITIONS


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
    per = (own_cash_per_position() if per_position_rs is None
           else float(per_position_rs))
    held = int(held or 0)

    deployable = capital - floor
    if deployable < per:
        return {"slots": 0, "deployable": max(deployable, 0.0),
                "free_after": capital,
                "why": (f"Rs {capital:,.0f} in the account and Rs "
                        f"{floor:,.0f} must stay free -- that leaves "
                        f"less than one position")}

    # What cash alone allows, before any ceiling.
    by_cash = int(deployable // per)
    # ---- THE CEILINGS. See the note at the top. ----
    # Since 31 August the working ceiling equals ABSOLUTE_MAX_POSITIONS,
    # so cash decides and the ceiling is only a guard against a bad
    # capital read.
    #
    # capped_by_rule is computed against BY_CASH, not against the
    # already-capped figure. The old order compared total to the
    # working ceiling AFTER applying the absolute one, so once the two
    # became equal the flag could never fire again -- a dead light on
    # the panel, which is worse than no light.
    total = min(by_cash, ABSOLUTE_MAX_POSITIONS, WORKING_MAX_POSITIONS)
    capped_by_rule = by_cash > total
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
