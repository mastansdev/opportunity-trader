"""+05:30 is applied, never deleted, wherever a stored stamp is read.

    "why simple timing is still not resolved. we are in IST & its
     +05:30 asian timing"          -- operator, 23 August 2026

Because the offset was written out ten separate times and
core/feed_clock.to_ist() -- built 10 August from his own instruction
"create a mechanism if bot doesn't know" -- was used by almost none of
them. Every private copy was a fresh chance to strip instead of apply.

These are behaviour tests. A test that greps the source for
`replace("+00:00", "")` would pass the day someone writes the same bug
a different way.
"""

from datetime import datetime

from core.feed_clock import to_ist

# A real data/telegram.db stamp. 15:22 UTC is 20:52 IST -- AFTER the
# 15:30 close, so the session that answers it is the NEXT one.
UTC_EVENING = "2026-08-23T15:22:30+00:00"
NAIVE_EVENING = "2026-08-23 21:46:09"


def test_the_one_converter_applies_the_offset():
    got = to_ist(UTC_EVENING)
    assert (got.hour, got.minute) == (20, 52)


def test_the_one_converter_leaves_a_naive_stamp_alone():
    got = to_ist(NAIVE_EVENING)
    assert (got.hour, got.minute) == (21, 46)


def test_reaction_puts_an_evening_post_after_the_close():
    from core.reaction import _as_datetime, CLOSE_HOUR, CLOSE_MINUTE
    when = _as_datetime(UTC_EVENING)
    assert (when.hour, when.minute) >= (CLOSE_HOUR, CLOSE_MINUTE), \
        "an evening post must not be scored against the session that " \
        "had already closed when it was published"


def test_reaction_still_reads_a_naive_stamp():
    from core.reaction import _as_datetime
    when = _as_datetime(NAIVE_EVENING)
    assert (when.hour, when.minute) == (21, 46)


def test_reaction_survives_rubbish():
    from core.reaction import _as_datetime
    assert _as_datetime("") is None
    assert _as_datetime(None) is None
    assert _as_datetime("not a date") is None


def test_a_datetime_passes_through_reaction():
    from core.reaction import _as_datetime
    stamp = datetime(2026, 8, 23, 20, 52)
    assert _as_datetime(stamp) == stamp


def test_the_feed_is_not_five_and_a_half_hours_stale():
    """core/telegram_feed._all_older_than() decides whether the feed
    has gone quiet. Reading UTC as IST made a live feed look 5h30m
    behind -- more than most staleness thresholds.

    The stamp is built RELATIVE TO NOW. The first version of this test
    hard-coded "2026-08-23T15:22:30+00:00", which was twenty minutes
    old when I wrote it and nineteen hours old the next afternoon. A
    test whose answer depends on the day it runs is not a test.
    """
    from datetime import timedelta, timezone
    from core.telegram_feed import _all_older_than

    # Ten minutes ago, written the way the store writes it: UTC.
    ten_min_ago = (datetime.now(timezone.utc)
                   - timedelta(minutes=10)).isoformat()
    assert _all_older_than([{"at": ten_min_ago}], hours=4) is not True

    # And something genuinely old still reads as old, so the assertion
    # above is not passing for want of a working comparison.
    long_ago = (datetime.now(timezone.utc)
                - timedelta(hours=30)).isoformat()
    assert _all_older_than([{"at": long_ago}], hours=4) is True


def test_why_moving_and_the_feed_agree_on_one_stamp():
    from core.why_moving import _local_naive
    assert _local_naive(UTC_EVENING) == to_ist(UTC_EVENING).replace(
        tzinfo=None)
