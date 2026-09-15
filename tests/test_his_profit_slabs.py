"""---- HIS PROFIT SLABS, EXACTLY AS HE SAID THEM. 15 September 2026. ----

    "once mtm profit cross 5K then shift the Trailing stop loss to 5K
     price of that stock then increase for every 1 k upside movement"

Built on 14 Sep as a percentage instead. This is the rupee rule.
"""

import pytest

from core.trailing_stop import TrailingStopEngine


@pytest.fixture(autouse=True)
def _slabs_on(monkeypatch):
    import config
    monkeypatch.setattr(config, "PROFIT_SLAB_ENABLED", True)
    monkeypatch.setattr(config, "PROFIT_SLAB_FIRST_RS", 5000.0)
    monkeypatch.setattr(config, "PROFIT_SLAB_STEP_RS", 1000.0)
    monkeypatch.setattr(config, "PROFIT_LOCK_ENABLED", False)


def _tcs():
    """TCS today: 97 shares at 2318.06, stop 2247.40."""
    t = TrailingStopEngine()
    t.start("TCS", 2247.40, direction="LONG", entry_price=2318.06)
    return t


def _run_to(t, mtm):
    price = 2318.06 + mtm / 97.0
    t.update_on_price("TCS", price)
    return t.apply_profit_slab("TCS", 97)


def test_below_5000_nothing_changes():
    t = _tcs()
    assert _run_to(t, 4999) is None
    assert t.get_stop("TCS") < 2318.06


def test_at_5000_the_stop_locks_5000():
    t = _tcs()
    _run_to(t, 5000)
    assert t.get_stop("TCS") == pytest.approx(2318.06 + 5000 / 97, abs=0.01)
    assert t.get_stop("TCS") == pytest.approx(2369.61, abs=0.01)


def test_every_1000_raises_it_1000():
    t = _tcs()
    _run_to(t, 6400)          # best 6,400 -> locks 6,000, not 6,400
    assert t.get_stop("TCS") == pytest.approx(2318.06 + 6000 / 97, abs=0.01)
    _run_to(t, 7000)
    assert t.get_stop("TCS") == pytest.approx(2318.06 + 7000 / 97, abs=0.01)


def test_a_pullback_never_lowers_it():
    t = _tcs()
    _run_to(t, 7000)
    locked = t.get_stop("TCS")
    t.update_on_price("TCS", 2318.06 + 5500 / 97)
    t.apply_profit_slab("TCS", 97)
    assert t.get_stop("TCS") == locked
    assert t.is_hit("TCS", 2318.06 + 6900 / 97)


def test_the_slab_survives_a_restart():
    """export/load used to drop peak and entry, so nothing could lock."""
    t = _tcs()
    _run_to(t, 5200)
    saved = t.export_state()
    again = TrailingStopEngine()
    again.load_state(saved)
    again.update_on_price("TCS", 2318.06 + 6100 / 97)
    again.apply_profit_slab("TCS", 97)
    assert again.get_stop("TCS") == pytest.approx(2318.06 + 6000 / 97, abs=0.01)


def test_off_means_off(monkeypatch):
    import config
    monkeypatch.setattr(config, "PROFIT_SLAB_ENABLED", False)
    t = _tcs()
    assert _run_to(t, 9000) is None


def test_the_engine_calls_it_with_the_quantity():
    import pathlib
    src = pathlib.Path("core/engine.py").read_text(encoding="utf-8")
    assert 'apply_profit_slab(symbol, position.get("qty"))' in src
