"""---- 293 STOCKS MISSING, EVERY CYCLE. 15 September 2026. ----

    [CIRCUIT_MONITOR] THE BOARD IS SHORT: 900 of 1,193 stocks,
    293 missing (1 batch(es) failed)

Dhan allows one quote request a second. The second batch, its retry,
and the dashboard's index tiles all hit the endpoint back to back.
core/circuit_monitor.spaced() makes every caller wait its turn.
"""

import threading

from core.circuit_monitor import CircuitMonitor, spaced


class _Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def test_the_second_call_waits_for_the_gap():
    clock = _Clock()
    calls = []
    fn = spaced(lambda x: calls.append((x, clock.t)), min_gap=1.1,
                _sleep=clock.sleep, _clock=clock.now)
    fn("a")
    fn("b")
    assert calls[1][1] - calls[0][1] >= 1.1 - 1e-9


def test_a_call_after_a_long_pause_does_not_wait():
    clock = _Clock()
    fn = spaced(lambda: None, min_gap=1.1, _sleep=clock.sleep, _clock=clock.now)
    fn()
    clock.t += 5
    fn()
    assert clock.slept == []


def test_both_batches_now_succeed_against_a_rate_limited_endpoint():
    """A fake Dhan that refuses any call within 1s of the last one --
    the shape of this morning's failure."""
    import time
    last = [None]
    lock = threading.Lock()

    def dhan(securities):
        with lock:
            now = time.monotonic()
            too_soon = last[0] is not None and now - last[0] < 1.0
            last[0] = now
        if too_soon:
            return {"status": "failure", "remarks": {}, "data": ""}
        ids = list(securities.values())[0]
        return {"status": "success", "data": {"data": {"NSE_EQ": {
            str(i): {"last_price": 100.0} for i in ids}}}}

    asked = []
    real = dhan

    def counting(securities):
        response = real(securities)
        asked.append(response["status"])
        return response

    monitor = CircuitMonitor(spaced(counting, min_gap=1.05), "NSE_EQ")
    monitor.set_universe({str(i): f"S{i}" for i in range(1, 1194)})
    monitor.poll_once()
    assert asked == ["success", "success"], (
        "the second batch was refused -- 293 stocks off the board")
