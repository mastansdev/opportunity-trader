"""---- "FEED RECOVERED" WAS NOT THE WHOLE TRUTH. 31 Aug 2026 ----

core/morning_ready.LiveGuard watches the feed during the session and
disarms the bot if it dies for STRIKES_TO_DISARM polls in a row. That
part is right, and the slowness is deliberate:

    "if it's too twitchy -- say the collector pauses for 30 seconds --
     it could disarm you in the middle of a good move"

What was wrong is what happens next. `self.disarmed` is set once and
never cleared -- also on purpose, because a flapping feed would
otherwise toggle trading on and off all day. But when the feed came
back the guard said:

    [GUARD] Feed recovered -- feed alive, 2 min ago. Strike count reset.

and stopped there, while engine.alert_only was still True. The bot was
not trading, the log read like it was, and nothing mentioned it again
for the rest of the session.

That is the same silent freeze that cost ten sessions in August --
2,058 picks and 0 trades on 31 August -- arriving through a different
door. He would have had no reason to look.

Re-arming stays his decision: the dashboard switch sets alert_only
False in either position. This only makes sure he knows there is a
decision to make.
"""

import pytest

from core.morning_ready import LiveGuard


class _Feed:
    """Stands in for during_session()."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, now=None, telegram_db=None):
        return self.answers.pop(0) if self.answers else {"ok": True,
                                                         "why": "alive"}


ALIVE = {"ok": True, "why": "feed alive, 1 min ago"}
DEAD = {"ok": False, "why": "no tick for 14 minutes"}


def _guard(monkeypatch, *answers, strikes=2):
    said = []
    disarmed = []
    monkeypatch.setattr("core.morning_ready.during_session",
                        _Feed(*answers))
    guard = LiveGuard(disarm=lambda: disarmed.append(True),
                      say=said.append, strikes=strikes)
    return guard, said, disarmed


def test_it_still_disarms_on_a_dead_feed(monkeypatch):
    """The behaviour being protected. Nothing here loosens it."""
    guard, said, disarmed = _guard(monkeypatch, DEAD, DEAD, strikes=2)
    guard.poll(armed=True)
    assert disarmed == [], "it panicked on the first strike"
    guard.poll(armed=True)
    assert disarmed == [True]
    assert guard.disarmed is True


def test_recovery_after_a_disarm_says_the_bot_is_still_off(monkeypatch):
    """The finding. "Feed recovered" on its own is a true sentence that
    leaves a false impression."""
    guard, said, disarmed = _guard(monkeypatch, DEAD, DEAD, ALIVE,
                                   strikes=2)
    guard.poll(armed=True)
    guard.poll(armed=True)
    said.clear()
    got = guard.poll(armed=True)

    text = " ".join(said)
    assert "recovered" in text.lower()
    assert "STILL NOT TRADING" in text, (
        "the log says the feed recovered and does not say the bot is "
        "still off -- which is how ten sessions passed unnoticed")
    assert "switch" in text.lower(), "it does not say how to resume"
    assert got.get("still_disarmed") is True


def test_recovery_without_a_disarm_does_not_cry_wolf(monkeypatch):
    """One strike then recovery is an ordinary quiet patch. If this
    warned every time, the warning would stop meaning anything."""
    guard, said, disarmed = _guard(monkeypatch, DEAD, ALIVE, strikes=3)
    guard.poll(armed=True)
    said.clear()
    guard.poll(armed=True)

    text = " ".join(said)
    assert "recovered" in text.lower()
    assert "STILL NOT TRADING" not in text
    assert disarmed == []


def test_it_does_not_re_arm_by_itself(monkeypatch):
    """Deliberate. A flapping feed would otherwise switch trading on
    and off all day, which is worse than being off and knowing it."""
    guard, said, disarmed = _guard(monkeypatch, DEAD, DEAD, ALIVE,
                                   strikes=2)
    guard.poll(armed=True)
    guard.poll(armed=True)
    guard.poll(armed=True)
    assert guard.disarmed is True, "it re-armed itself on a recovery"


def test_the_dashboard_switch_is_what_re_arms(monkeypatch):
    """The route out. Either position of the switch clears alert_only --
    so the message telling him to click it is telling him something
    that actually works."""
    from pathlib import Path

    src = Path("dashboard/server.py").read_text(encoding="utf-8")
    # ---- ONE FUNCTION MOVES THE SWITCH NOW. 5 September 2026. ----
    #
    # These asserted on lines inside the endpoint. The endpoint no
    # longer writes the flags itself: the desk and the phone both go
    # through core.trading_gate.apply_switch(), because until then the
    # same OFF meant "still trading, on paper" on the desk and "stop
    # trading, alerts only" from Telegram -- the third state, still
    # reachable from his phone.
    #
    # So the assertion follows the behaviour to where it lives: the
    # endpoint must DELEGATE, and apply_switch must do the thing.
    import inspect

    from core.trading_gate import apply_switch
    _gate = inspect.getsource(apply_switch)
    assert "apply_switch" in src, (
        "the endpoint no longer moves the switch through the gate")
    src = _gate
    # ---- THE FLAG IT CHECKED FOR IS RETIRED. 5 September 2026. ----
    #
    # This asserted apply_switch clears engine.alert_only, so that a
    # feed-guard disarm could be undone from the dashboard. Two things
    # have since changed and both remove the need:
    #
    #   the guard no longer disarms anything -- main.py wires it as
    #   _LiveGuard(disarm=None): "Nothing may turn trading off but him"
    #
    #   alert_only is gone entirely (the collapse to two, 5 Sep). The
    #   switch writes execution.live and nothing else, so there is no
    #   second flag left for anything to get stuck on.
    #
    # What must remain true is that the switch MOVES, from one place.
    assert "execution.live = bool(on)" in src, (
        "apply_switch no longer moves the switch")


def test_a_disarmed_guard_that_is_not_armed_says_nothing(monkeypatch):
    """poll(armed=False) means he has switched trading off himself.
    Telling him it is off would be noise."""
    guard, said, disarmed = _guard(monkeypatch, ALIVE, strikes=2)
    guard.disarmed = True
    said.clear()
    guard.poll(armed=False)
    assert said == []
