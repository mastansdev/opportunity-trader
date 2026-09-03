"""---- GROSS IS NOT WHAT HE KEEPS. 3 September 2026. ----

On 3 September the desk read +Rs 2,015 across twenty closed trades.
Charges on those trades were about Rs 2,000. He kept fifteen rupees.

Three separate places decided money off a gross number:

    the desk headline      showed cap.realized_pnl
    the Rs 12,000 cap      summed record["pnl"]
    portfolio.realized_pnl booked (exit-entry)*qty

trading/charges.py has existed and been correct all along; only the
analytics panels ever called it. This pins the two that decide
anything: what he reads, and what stops the day.

_build_performance() already published net_pnl_after_charges. Nothing
read it.
"""

import re


def test_the_desk_reads_the_net_field():
    with open("dashboard/static/desk.html", encoding="utf-8") as fh:
        body = fh.read()
    head = body[:body.index("var cells = [")]
    assert "perf.net_pnl_after_charges" in head, (
        "the headline must come from the charged number")
    assert not re.search(r"var realized = num\(cap\.realized_pnl\);", head), (
        "gross must not be the first choice for the headline")


def test_the_charge_bite_is_shown_not_just_taken():
    """He must be able to see what the charges cost, not only feel it.
    A number that quietly shrinks is worse than one that explains."""
    with open("dashboard/static/desk.html", encoding="utf-8") as fh:
        body = fh.read()
    assert "charges" in body[body.index("var cells = ["):][:1200]


def test_the_daily_loss_cap_counts_charges():
    """The brake he set is Rs 12,000 of HIS money. At Rs 100 a round
    trip a forty-trade day pays Rs 4,000 the old sum could not see, so
    the cap would have kept opening positions at a true -Rs 16,000."""
    with open("core/engine.py", encoding="utf-8") as fh:
        body = fh.read()
    start = body.index("def _daily_realized_pnl")
    fn = body[start:start + 3000]
    assert "round_trip_charges" in fn, (
        "the daily loss guardrail still sums gross P&L")
