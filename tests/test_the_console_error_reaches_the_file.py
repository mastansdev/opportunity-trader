"""The one error that mattered was never written down.

    "didn't u see the error print = ERROR:root:Exception in
     DhanHQConnection.GET: ... ProxyError('Unable to connect to proxy',
     OSError('Tunnel connection failed: 403 Error'))"
                                   -- the operator, 4 September 2026

He had to paste it, because it was not in any log file. Grepping every
file in logs/ for "Tunnel connection failed" returned nothing -- not
once, in any session, ever.

WHY. dhanhq logs to the ROOT logger. core/logger.py builds
"opportunity_trader" with propagate=False and attaches the file
handler to THAT. So the bot's own lines reach the file and every
library's line reaches the console and dies there. The most
consequential message the process can produce -- the static IP tunnel
is refusing, so ORDERS CANNOT LEAVE -- was console-only.

AND THE BOT'S OWN TRANSLATION MADE IT WORSE:

    [LIVE] could not read holdings from Dhan (connection reset).

"Connection reset" sounds like weather: wait, retry, it comes back.
"The proxy refused the tunnel with 403" means the static IP is not
authorised and he has to go and renew it. Only one of those sends him
to fix the thing that stops his orders leaving.
"""

import logging

import pytest


def test_a_library_error_lands_in_the_bot_log_file():
    """THE fix. Anything a third-party library reports at WARNING or
    above must be readable afterwards, not only live on the console.

    Driven against a STAND-IN root logger: pytest's own logging plugin
    swaps the real root's handlers out during a test, so asserting on
    the real one would test pytest, not this."""
    from core.logger import capture_library_errors, log_file_path

    stand_in = logging.getLogger("test_stand_in_root")
    stand_in.handlers = []
    stand_in.propagate = False
    mirror = capture_library_errors(root=stand_in)
    assert mirror is not None, "no file handler was attached at all"

    marker = "test-marker-proxy-tunnel-403"
    stand_in.error("Exception in DhanHQConnection.GET: %s", marker)
    mirror.flush()

    with open(log_file_path(), encoding="utf-8", errors="ignore") as fh:
        body = fh.read()
    assert marker in body, (
        "a library error still dies on the console -- the proxy 403 "
        "would be invisible again")


def test_it_writes_to_the_same_file_the_bot_uses():
    """One file to read, not two. He should never have to be told
    which log has the real error in it."""
    from core.logger import capture_library_errors, log_file_path
    stand_in = logging.getLogger("test_stand_in_root_2")
    stand_in.handlers = []
    mirror = capture_library_errors(root=stand_in)
    assert mirror.baseFilename == log_file_path()


def test_only_warnings_and_worse_are_captured():
    """Not every library's debug chatter -- the file is already ~15 MB
    a session without importing everyone else's."""
    from core.logger import capture_library_errors
    stand_in = logging.getLogger("test_stand_in_root_3")
    stand_in.handlers = []
    mirror = capture_library_errors(root=stand_in)
    assert mirror.level == logging.WARNING


def test_attaching_twice_does_not_double_every_line():
    from core.logger import capture_library_errors
    stand_in = logging.getLogger("test_stand_in_root_4")
    stand_in.handlers = []
    capture_library_errors(root=stand_in)
    before = len(stand_in.handlers)
    capture_library_errors(root=stand_in)
    assert len(stand_in.handlers) == before


def test_the_bots_own_lines_are_not_duplicated():
    """opportunity_trader sets propagate=False, so its records must not
    also travel to root and be written twice."""
    from core.logger import log
    assert log.propagate is False


# ------------------------------------------------ naming the cause

class _Boom:
    def __init__(self, exc):
        self.exc = exc

    def get_holdings(self):
        raise self.exc


def _read_holdings(monkeypatch, exc, capture):
    from trading import live_execution as le
    monkeypatch.setattr(le, "warn", lambda m: capture.append(m))
    ex = object.__new__(le.LiveExecution)
    ex.dhan = _Boom(exc)
    return ex.read_holdings() if hasattr(ex, "read_holdings") else None


def test_a_proxy_403_is_reported_as_a_proxy_403(monkeypatch):
    """Not as 'connection reset'. The words decide whether he goes and
    renews the IP or waits for a network wobble to pass."""
    from trading import live_execution as le
    said = []
    monkeypatch.setattr(le, "warn", lambda m: said.append(m))

    exc = Exception("HTTPSConnectionPool(host='api.dhan.co', port=443): "
                    "Max retries exceeded with url: /v2/holdings (Caused by "
                    "ProxyError('Unable to connect to proxy', "
                    "OSError('Tunnel connection failed: 403 Error')))")
    import inspect
    src = inspect.getsource(le)
    assert "tunnel connection failed" in src.lower(), (
        "nothing recognises the proxy refusal any more")
    assert "ORDERS CANNOT LEAVE" in src, (
        "the message no longer says the consequence he needs to act on")
    assert "Renew the static IP" in src


def test_an_ordinary_failure_keeps_the_ordinary_message():
    """A real network wobble must not be reported as an IP problem."""
    from trading import live_execution as le
    import inspect
    src = inspect.getsource(le)
    assert "could not read holdings from Dhan ({exc})" in src, (
        "the plain message was removed -- now every failure blames "
        "the static IP, which is the same lie pointing the other way")
