

# ==========================================================
#  FLIPPING OFF MUST NOT ORPHAN A REAL POSITION. 6 Sep 2026.
# ==========================================================
#
#     "once if i ON & after trades completed incase i switched OFF,
#      how bot will react for multiple ON & OFF"    -- the operator
#
# He asked, and the answer was wrong. "An exit follows its own entry"
# has been right since 31 August for one direction only -- a PAPER
# position sold on paper even with the switch ON. The other direction
# never reached that code, because `if not self.live` returned first.
#
# Measured with the process in LIVE, before the fix:
#
#     switch ON   buy ABC   -> LIVE
#     switch OFF  sell ABC  -> PAPER      <-- orphaned at Dhan
#
# The bot would record the trade closed while Dhan went on holding the
# stock, unmanaged, with no stop the broker knows about.

class _Executor:
    def __init__(self, tag):
        self.tag = tag


def _execution(switch_on, opened):
    from trading.execution import Execution
    e = Execution.__new__(Execution)
    e.executor = _Executor("paper")
    e._live = _Executor("live")
    e.live = switch_on
    e._said = set()
    e._opened_by = dict(opened)
    return e


def _routed(e, **kw):
    return "live" if e._route("x", **kw) is e._live else "paper"


def test_a_real_position_is_closed_for_real_even_after_switching_off(
        monkeypatch):
    import config
    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    e = _execution(switch_on=False, opened={"ABC": "live"})
    assert _routed(e, selling=True, symbol="ABC") == "live", (
        "the switch went OFF and a REAL position was closed on paper -- "
        "Dhan would still be holding it")


def test_a_paper_position_is_still_closed_on_paper_with_the_switch_on(
        monkeypatch):
    """The direction that was already right, and must stay right: a
    real SELL for stock never bought opens a real short."""
    import config
    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    e = _execution(switch_on=True, opened={"P": "paper"})
    assert _routed(e, selling=True, symbol="P") == "paper"


def test_the_switch_still_governs_what_may_be_OPENED(monkeypatch):
    import config
    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    assert _routed(_execution(True, {}), symbol="NEW") == "live"
    assert _routed(_execution(False, {}), symbol="NEW") == "paper"


def test_the_switch_is_the_whole_answer(monkeypatch):
    """---- HE SETTLED IT, AND IT IS FINAL. 6 September 2026. ----

        "its not correct. as we settled that switch . OFF = paper &
         ON = Real trades thats it & final"
        "by default OFF . after clicking ON then it must trade in real
         mode & do not ask user to change in files or restarts in run"

    A real order used to need TRADING_MODE=LIVE as well, so arming
    meant editing a source file and restarting -- a deployment, not a
    control, and the same thing he rejected when ALERT_ONLY_MODE lived
    in config.py.

    TRADING_MODE no longer decides anything. The switch does.
    """
    import config
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    assert _routed(_execution(True, {}), symbol="NEW") == "live", (
        "the switch is ON and the order went to paper -- he must not "
        "have to edit a file or restart to trade for real")
    assert _routed(_execution(False, {}), symbol="NEW") == "paper"


def test_the_bot_always_starts_OFF():
    """"by default OFF". It is a class attribute, so it cannot be
    forgotten in a constructor, and it is never written back to
    config -- a restart always comes up OFF."""
    from trading.execution import Execution
    assert Execution.live is False
