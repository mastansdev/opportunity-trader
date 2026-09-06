

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


def test_a_paper_process_never_places_a_real_order_either_way(monkeypatch):
    """The outer bound. A session started in PAPER cannot be turned
    real by a click, however the switch is set and whoever opened it."""
    import config
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    e = _execution(switch_on=True, opened={"ABC": "live"})
    assert _routed(e, symbol="NEW") == "paper"
    assert _routed(e, selling=True, symbol="ABC") == "paper"
