

# ---------------------------------------------------------------
# THE WORKING CEILING, AND THE GATE ORDER IT EXPOSED
# 10 August 2026
# ---------------------------------------------------------------

def test_cash_still_decides_below_the_working_ceiling():
    """---- HIS RULE CHANGED ON 20 AUGUST 2026. ----

    It read: "keep at least 1 lakh free cash & positions can be build
    on remaining" (8 August), and this test held him to it.

        "no 1 lakh free cash rule"          -- 20 August

    Why he removed it: the seat count is (capital - floor) / 30,000
    and his free cash moves with his OWN manual trades in the same
    account. At Rs 1,52,081 free the floor gave 1 seat; at Rs 1,20,000
    it gave none. On an ordinary day it was not reserving a lakh, it
    was closing the book.

    Cash still decides -- that part is unchanged and is what this test
    exists for. Only the reserve is gone.
    """
    from core import capital

    per = capital.OWN_CASH_PER_POSITION_RS
    cap = capital.WORKING_MAX_POSITIONS
    # Below the ceiling the CASH decides, and it decides by division.
    # Derived, not written out, so raising the ceiling (5 -> 8 on
    # 29 August) does not require editing an arithmetic test.
    for rupees in (120_000, 150_000, 200_000, 246_593):
        assert capital.slots(rupees)["total"] == min(
            int(rupees // per), cap), rupees
    assert capital.slots(20_000)["slots"] == 0, (
        "an account that cannot fund one position must still open none")


def test_the_floor_machinery_still_works_if_he_restores_it():
    """Set to 0, not deleted. Putting the reserve back is one number,
    and the arithmetic that honours it must not rot while it is off."""
    from core import capital
    got = capital.slots(150_000, floor_rs=100_000)
    assert got["total"] == 1, "the reserve no longer holds cash back"
    assert capital.slots(120_000, floor_rs=100_000)["slots"] == 0


def test_the_working_ceiling_still_caps_a_big_account():
    """Cash says 11 at Rs 4.31 lakh; the ceiling holds it lower.

    ---- RAISED FROM FIVE TO EIGHT. 29 August 2026. ----
    "i want bot to utilise the capital to max & book the profits."
    His real Dhan balance is Rs 246,592.89, which funds exactly eight
    positions -- at five, Rs 96,593 sat idle every session.

    The 3-5 August measurement behind the old number stands (11 seats:
    33 trades, 24% hit rate, -Rs 26,018), but it ran with no daily
    halt in front of it. config.DAILY_MAX_LOSS_RS stops the session at
    Rs 12,000 whatever the seat count, so eight seats cannot lose more
    in a day than five -- they take more opportunities at the same
    bounded downside.

    Asserted against the constant, not a literal, so the guarantee is
    "the ceiling binds" rather than "the ceiling is five".

    ---- AND LIFTED ALTOGETHER. 31 August 2026. ----

    "yes bot needs to use complete capital & the seats depends on
     available capital , no minimum & no maximum seat count"

    So the guarantee this test defends changed. It is no longer "the
    ceiling holds the book below what cash allows" -- that is the
    opposite of the instruction. It is now:

        capital alone decides the seats, and the only ceiling left is
        the guard against a BAD CAPITAL READ

    which is ABSOLUTE_MAX_POSITIONS, unchanged at 25. A corrupt
    balance of ten crore must still not open three hundred positions.
    """
    from core import capital

    # Cash decides, all the way up.
    assert capital.slots(431_116)["total"] == int(431_116 // 30_000)
    assert capital.slots(146_593)["total"] == 4

    # ...until the bad-read guard, which is the only thing left.
    absurd = capital.slots(100_000_000)
    assert absurd["total"] == capital.ABSOLUTE_MAX_POSITIONS
    assert absurd["capped_by_rule"] is True
    assert capital.WORKING_MAX_POSITIONS == capital.ABSOLUTE_MAX_POSITIONS, (
        "a working ceiling below the bad-read guard is a seat limit, "
        "and he asked for none")


def test_the_book_is_bounded_by_the_daily_halt_not_the_seat_count():
    """Why raising the ceiling did not widen the risk.

    Eight seats at RISK_PER_TRADE_RS is Rs 20,000 of theoretical loss,
    but the session halts at DAILY_MAX_LOSS_RS long before that. If
    that halt is ever removed, the seat count becomes the bound and
    this decision has to be revisited.
    """
    import config
    from core import capital
    from core.rules import RISK_PER_TRADE_RS

    worst = capital.WORKING_MAX_POSITIONS * RISK_PER_TRADE_RS
    assert config.DAILY_MAX_LOSS_RS < worst, (
        "the daily halt no longer binds before the seats do -- the "
        "seat count is now the real risk limit")


def test_a_below_floor_account_gets_no_slots_at_all():
    """THE INTERACTION THAT BROKE TWO ENGINE TESTS.

    core/engine._staged_position_cap() runs BEFORE the margin gate, so
    an account under the free-cash floor is refused here and never
    reaches the margin check. That is correct under his rule -- there
    is no 'remaining' to build on -- but it means the two gates answer
    different questions and must be tested apart.
    """
    from core import capital
    got = capital.slots(11_200)
    assert got["slots"] == 0
    assert "less than one position" in got["why"]


def test_the_floor_is_never_spent():
    from core import capital
    for money in (431_116, 300_000, 200_000, 150_000):
        got = capital.slots(money)
        assert got["free_after"] >= capital.FREE_CASH_FLOOR_RS
