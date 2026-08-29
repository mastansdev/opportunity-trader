"""Candidates come from what has a REASON, not from a leaderboard.

    "i do not want those top 50 gainers & losers which no one gonna use
     & burden the bot system"      -- operator, 29 August 2026

build_ranked() seeded its pool with 50 gainers AND 50 LOSERS.
config.ENABLE_SHORT_TRADES is False and always has been, so every
loser was walked through the gates to be refused for being a loser --
2,045 SELL picks are on record that could never have been taken.

The gainers half is a leaderboard of moves ALREADY MADE. On a strong
day the 50th gainer is up 5-6%, so a stock that filed results at 09:41
and is up 2.5% sits around 180th and was never seen. _widen_by_reason()
existed to ADD IT BACK. Seeding from the leaderboard and then repairing
it is the wrong way round.
"""

import inspect

import config
from dashboard.state import DashboardState


def test_the_pool_is_no_longer_seeded_from_gainers_and_losers():
    src = inspect.getsource(DashboardState.build_ranked)
    # slice at the CALL, not the first mention -- the comment
    # explaining the change names the function too.
    seed = src[:src.index("movers = self._widen_by_reason(movers)")]
    assert 'for side in ("gainers", "losers")' not in seed, (
        "the leaderboard is seeding the candidate pool again")
    assert "movers = []" in seed


def test_shorts_are_still_off():
    """The whole reason the losers half was dead weight."""
    assert config.ENABLE_SHORT_TRADES is False


def test_the_market_view_is_NOT_narrowed():
    """Sector strength and breadth need every stock, candidate or not.
    gainers_losers must still reach rank() untouched."""
    src = inspect.getsource(DashboardState.build_ranked)
    assert "gainers_losers=gainers_losers" in src, (
        "rank() must still see the full leaderboard for sector and "
        "market context, even though it no longer seeds candidates")


def test_an_empty_pool_is_stated_not_silent():
    """"no news today" and "the news lookup broke" look identical from
    an empty board, and only one of them is fine."""
    src = inspect.getsource(DashboardState.build_ranked)
    assert "no event, no evaluation" in src


def test_the_widener_supplies_full_rows_not_just_symbols():
    """It becomes the seed, so it has to produce rows the ranker can
    actually score -- price, volume, sector, not bare symbols."""
    src = inspect.getsource(DashboardState._widen_by_reason)
    assert "_compute_gl_rows()" in src, (
        "the seed must pull complete rows, or every candidate is "
        "refused for missing data")
