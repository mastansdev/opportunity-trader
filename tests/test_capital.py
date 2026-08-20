

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
    assert capital.slots(200_000)["total"] == 5
    assert capital.slots(150_000)["total"] == 5
    assert capital.slots(120_000)["total"] == 4
    assert capital.slots(20_000)["slots"] == 0, (
        "an account that cannot fund one position must still open none")


def test_the_floor_machinery_still_works_if_he_restores_it():
    """Set to 0, not deleted. Putting the reserve back is one number,
    and the arithmetic that honours it must not rot while it is off."""
    from core import capital
    got = capital.slots(150_000, floor_rs=100_000)
    assert got["total"] == 1, "the reserve no longer holds cash back"
    assert capital.slots(120_000, floor_rs=100_000)["slots"] == 0


def test_the_working_ceiling_holds_the_book_at_five():
    """Cash says 11 at Rs 4.31 lakh. Measured 3-5 August, 11 seats made
    33 trades at a 24% hit rate for -Rs 26,018, against 9 trades and
    -Rs 10,715 at 3 seats. Five is the number that rises with cash --
    which he asked for -- without multiplying an unproven edge."""
    from core import capital
    got = capital.slots(431_116)
    assert got["total"] == capital.WORKING_MAX_POSITIONS == 5
    assert got["capped_by_rule"] is True


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
