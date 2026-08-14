"""
==========================================================
The night does the work; the morning is short
==========================================================

    "every night we will complete the necessary works, & in morning
     only small pending can be completed by bot within 15-20 mins."

    "for news Day Trader Telugu is reliable + off the clickable youtube
     links; Insurance links; excel sheet links from this channel."
                                    -- operator, 2 August 2026

WHY THE MORNING USED TO OVERRUN
-------------------------------
Measured on the real store, the channels deliver about seven messages
a minute of OCR work, and 34% of everything they send arrives outside
market hours. A weekend backlog is 250-400 posts -- forty to sixty
minutes. Started at 08:00 that is still running at 09:15.

tools/nightly.py runs the six long jobs after the close. What is left
for the morning is the token, the route, the overnight brief and a
short catch-up.

THE DATE BUG THIS CREATED, AND THE FIX
--------------------------------------
morning_universe asks stock_memory for "symbols going ex-date TODAY".
Run at 22:00 on Sunday that means SUNDAY -- so a stock going ex-split
on MONDAY would not be blocked on the Monday list the run is building.
The one job of that check, missed by a date. next_session() rolls past
16:00 and past the weekend.

THE AFFILIATE FILTER, AND THE TRAP IN IT
----------------------------------------
Day Trader Telugu pays for itself with referral links -- term and
health policies, and a row of broker sign-ups. The obvious filter is
the word "insurance". It is also wrong: HDFCLIFE, SBILIFE, ICICIGI,
LICI and STARHEALTH are STOCKS, and a filter on that word would
silently drop their results.

Measured across all 3,135 stored messages before anything was written:

    "support our work"     2 hits, Day Trader Telugu only
    "bit.ly/_"             4 hits, Day Trader Telugu only
    "aonelink.in"          2 hits, Day Trader Telugu only
    "term|health policy"   5 hits -- ONE of them an Earnings Pro
                           expectations page naming a listed insurer

So the last one was thrown away and the filter matches the AFFILIATE
SHAPE: his own shortener prefix, his own referral host.

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import datetime

import pytest

from core.stock_events import NOISE, classify


# ---------------------------------------------------------------
# 1. THE AFFILIATE BLOCK
# ---------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Support Our Work 🤝 1Cr Best Term Policy: https://bit.ly/_Term_Policy",
    "ZERODHA: https://bit.ly/_ZERODHA_ ANGEL ONE: "
    "https://a.aonelink.in/ANGOne/j4hirbQ FYRES: https://bit.ly/_Fyers_",
])
def test_the_referral_block_is_marked_noise(text):
    assert NOISE.search(text)
    assert classify(text)[0] == "NOISE"


@pytest.mark.parametrize("text", [
    "#HDFCLIFE — Q1 FY27 Pulse Rating : Good. Sales +12% YoY",
    "ICICIGI reports strong premium growth, PAT up 18% YoY",
    "SBILIFE Q1 results: APE up 14%, VNB margin steady",
    "LICI — Earnings · Q1 FY27  BEAT Revenue, EBITDA",
    "STARHEALTH gets IRDAI nod for a new health policy product",
])
def test_a_listed_INSURER_is_never_dropped(text):
    """THE TRAP. A filter on the word "insurance" or "health policy"
    would silently swallow the results of five listed companies. The
    patterns match his shortener and his referral host, nothing else."""
    assert not NOISE.search(text), f"a real insurer was marked noise: {text}"


def test_a_genuine_policy_story_survives():
    """An insurer launching a term product is news about a stock. Only
    the affiliate shape is refused."""
    text = ("HDFCLIFE launches a new 1Cr term policy; management guides "
            "for 15% APE growth")
    assert not NOISE.search(text)


def test_the_youtube_rule_is_untouched():
    """His original instruction, from 1 August: the weekend videos are
    not worth reading."""
    for text in ("Must Watch Shorts 👇 https://youtube.com/shorts/KI-SIub",
                 "🚨 https://youtu.be/fBB-4fZfUJw"):
        assert NOISE.search(text)


def test_the_patterns_are_narrow_on_purpose():
    """bit.ly on its own would catch any shortened link anyone posts.
    His affiliate links all carry the underscore prefix."""
    assert not NOISE.search("read more at https://bit.ly/nse-circular-2026")
    assert NOISE.search("https://bit.ly/_Term_Policy")


# ---------------------------------------------------------------
# 2. THE NIGHT RUNNER
# ---------------------------------------------------------------
#: Steps that only READ. They may sit after `universe` because they
#: change nothing the other steps depend on -- and the health check in
#: particular WANTS to run after everything has finished writing.
READ_ONLY_STEPS = ("health",)


def test_the_long_jobs_run_at_night_in_the_right_order():
    """telegram first because everything after it wants the events it
    files; universe LAST OF THE WRITERS because it reads all of them.

    12 August 2026: this asserted keys[-1] == "universe" literally, and
    a read-only health report added after it failed the test without
    breaking the rule. The rule is about the order things are WRITTEN
    in; the assertion now says that.
    """
    from tools.nightly import STEPS
    keys = [s[0] for s in STEPS]
    writers = [k for k in keys if k not in READ_ONLY_STEPS]
    assert keys[0] == "telegram"
    assert writers[-1] == "universe", (
        f"the last step that writes anything is {writers[-1]}, not "
        f"universe -- universe reads every other store and must go last")
    assert keys.index("discover") < keys.index("classify") < keys.index("universe")


def test_the_health_check_runs_after_everything_has_written():
    """A silent data outage ran for a week: config.AI_ENABLED went off
    on 10 August and 1,561 news stories were stored unreasoned, while
    every row count kept growing and nothing said a word. The check
    exists to catch that shape, so it has to see the finished night."""
    from tools.nightly import STEPS
    keys = [s[0] for s in STEPS]
    assert "health" in keys, "the nightly health check is gone"
    assert keys.index("health") > keys.index("universe")


def test_the_health_check_cannot_stop_the_night():
    """It exits non-zero BY DESIGN whenever a store is stale or news is
    unreasoned. run() must treat that as a report, not a halt --
    otherwise one honest warning would look like a broken night."""
    src = open("tools/nightly.py", encoding="utf-8").read()
    block = src[src.find("def run(step"):]
    block = block[:block.find("def main(")]
    assert "MOVING ON" in block


def test_every_step_is_a_subprocess():
    """One tool crashing must not take the rest of the night with it."""
    src = open("tools/nightly.py", encoding="utf-8").read()
    assert "subprocess.run" in src
    block = src[src.find("def run(step"):]
    block = block[:block.find("def main(")]
    assert "except subprocess.TimeoutExpired" in block
    assert "MOVING ON" in block, "a failed step must not stop the run"


def test_the_three_morning_only_jobs_are_not_in_the_night_list():
    """The Dhan token lasts 24 hours -- one generated tonight dies
    mid-session. The static IP route has to be true AT the open. The
    premarket brief reads a US close that has not happened at 22:00."""
    from tools.nightly import STEPS
    joined = " ".join(" ".join(s[2]) for s in STEPS)
    for tool in ("proxy_check", "premarket_brief", "access_token"):
        assert tool not in joined, f"{tool} cannot be done the night before"


def test_it_says_what_is_still_left_for_the_morning():
    from tools.nightly import MORNING_ONLY
    assert len(MORNING_ONLY) >= 3
    joined = " ".join(w for w, _ in MORNING_ONLY).lower()
    assert "token" in joined and "proxy_check" in joined


# ---------------------------------------------------------------
# 3. THE DATE BUG RUNNING AT NIGHT WOULD HAVE CREATED
# ---------------------------------------------------------------
@pytest.mark.parametrize("when,expect", [
    ((2026, 8, 3, 9, 0), (2026, 8, 3)),    # Monday morning -> today
    ((2026, 8, 2, 22, 0), (2026, 8, 3)),   # Sunday night   -> Monday
    ((2026, 8, 7, 22, 0), (2026, 8, 10)),  # Friday night   -> Monday
    ((2026, 8, 8, 11, 0), (2026, 8, 10)),  # Saturday       -> Monday
])
def test_the_universe_is_built_for_the_right_session(when, expect):
    """price_distorting_symbols() defaults to TODAY. Run at 22:00 on a
    Sunday that means Sunday -- so a stock going ex-split on MONDAY
    would not be blocked on the Monday list this run is building."""
    from tools.morning_universe import next_session
    assert next_session(datetime(*when)) == datetime(*expect).date()


def test_the_ex_date_check_is_asked_for_that_session():
    src = open("tools/morning_universe.py", encoding="utf-8").read()
    assert "fetch_corporate_actions(known, on_date=for_day)" in src
    block = src[src.find("def fetch_corporate_actions"):]
    block = block[:block.find("def fetch_price_bands")]
    assert "price_distorting_symbols(on_date=on_date)" in block


def test_a_morning_run_behaves_exactly_as_before():
    """Before 16:00 the session is today, so nothing about the existing
    morning routine changes."""
    from tools.morning_universe import next_session
    assert next_session(datetime(2026, 8, 3, 8, 30)) == \
        datetime(2026, 8, 3).date()
