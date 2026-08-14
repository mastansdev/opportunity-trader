"""
==========================================================
Press the buttons. Both of them. For real.
==========================================================

    "have you checked that toggle ? is it working both today created
     & the one u mentiond? broker-stop toggle."
                                -- operator, 5 August 2026

WHY THIS EXISTS
---------------
tests/test_bot_trading_switch.py checks that the endpoint exists, that
it says the right words, and that it does not contain the wrong ones.
Every one of those assertions reads SOURCE TEXT. Not one of them
presses the button.

That is the same shape as the failure that started today: 3,541 tests
passed while core/ranker.py reached no order path, because every test
checked a part and none checked the join. A toggle that is spelled
correctly and does nothing would sail through the other file.

So this drives real HTTP through the real app, with a real engine
object on the other side, and asserts THE ENGINE CHANGED.

BOTH toggles, because he asked about both -- and because the
broker-stop switch has never had a test that pressed it either.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest
from fastapi.testclient import TestClient

from dashboard.server import build_app

TOKEN = "operator-token-for-the-test"


class _Engine:
    """Enough Engine for the two switches to act on."""

    def __init__(self, alert_only=True):
        self.alert_only = alert_only
        self.open_positions = {"CGPOWER": {"entry_price": 871.7,
                                           "direction": "LONG", "qty": 100}}
        self.broker_stop = _BrokerStop()


class _BrokerStop:
    def __init__(self):
        self.enabled = False
        self.cancelled = False

    def enable(self, open_positions=None, hard_stop_for=None):
        self.enabled = True
        # Exercise the callback the endpoint hands in -- if it is
        # wrong, this is where it blows up rather than at 09:20.
        priced = {}
        for symbol, position in (open_positions or {}).items():
            priced[symbol] = hard_stop_for(symbol, position)
        return {"placed": len(priced), "prices": priced}

    def disable(self, cancel_resting=False):
        self.enabled = False
        self.cancelled = bool(cancel_resting)
        return {"cancelled": self.cancelled}


class _State:
    def __init__(self, engine):
        self.engine = engine

    def get_snapshot(self):
        return {"bot_trading": {"on": not self.engine.alert_only,
                                "known": True}}

    def refresh(self):
        return None


class _Controller:
    def __init__(self):
        self.notes = []

    def note_action(self, ok, text):
        self.notes.append((ok, text))


class _Loader:
    def get_by_symbol(self, symbol):
        return {"SECTOR": "IT"}

    def blocked_symbols(self):
        return {}


@pytest.fixture
def rig():
    engine = _Engine()
    controller = _Controller()
    app = build_app(_State(engine), controller, _Loader(),
                    operator_token=TOKEN)
    return TestClient(app), engine, controller


def press(client, path):
    # ---- force=1 BECAUSE THIS FILE TESTS THE SWITCH, NOT THE MORNING ----
    #      6 August 2026.
    #
    # /api/bot_trading/on now refuses to arm while a morning input is
    # missing -- the collector stopped, the catch-up still running, or
    # today's pre-open gapper card not yet in the store. That guard
    # exists because on 6 August the card arrived 30 minutes after the
    # open and nothing said so.
    #
    # These tests drive the SWITCH against a fixture store that has no
    # fresh telegram data, so the guard fires every time and the
    # toggle never flips. Forcing keeps this file testing what it is
    # named for. The guard itself is proven separately by
    # test_it_refuses_to_arm_when_the_morning_is_not_ready below.
    joiner = "&" if "?" in path else "?"
    return client.post(f"{path}{joiner}token={TOKEN}&force=1"
                       if "?" in path else f"{path}?token={TOKEN}&force=1")


# ---------------------------------------------------------------
# 1. BOT TRADING -- the switch built today
# ---------------------------------------------------------------
def test_pressing_ON_actually_arms_the_engine(rig):
    client, engine, _ = rig
    assert engine.alert_only is True                 # watching

    response = press(client, "/api/bot_trading/on")

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert response.json()["trading"] is True
    assert engine.alert_only is False, (
        "the endpoint returned success and the engine did not change")


def test_pressing_OFF_actually_disarms_it(rig):
    client, engine, _ = rig
    engine.alert_only = False                        # trading
    response = press(client, "/api/bot_trading/off")
    assert response.json()["trading"] is False
    assert engine.alert_only is True


def test_it_survives_being_pressed_repeatedly(rig):
    """He will press it twice when nothing seems to happen."""
    client, engine, _ = rig
    for _ in range(3):
        press(client, "/api/bot_trading/on")
    assert engine.alert_only is False
    for _ in range(3):
        press(client, "/api/bot_trading/off")
    assert engine.alert_only is True


def test_open_positions_are_untouched_by_the_switch(rig):
    """OFF stops NEW entries. It must never close what he is holding."""
    client, engine, _ = rig
    press(client, "/api/bot_trading/on")
    press(client, "/api/bot_trading/off")
    assert list(engine.open_positions) == ["CGPOWER"]
    assert engine.open_positions["CGPOWER"]["qty"] == 100


def test_the_count_of_open_positions_comes_back(rig):
    client, _engine, _ = rig
    assert press(client, "/api/bot_trading/off").json()["open_positions"] == 1


def test_a_visitor_without_the_token_cannot_arm_it(rig):
    """A view-only visitor must never be able to start real orders."""
    client, engine, _ = rig
    response = client.post("/api/bot_trading/on")
    assert response.status_code in (401, 403), response.status_code
    assert engine.alert_only is True, "it armed without the token"


def test_a_wrong_token_cannot_arm_it(rig):
    client, engine, _ = rig
    client.post("/api/bot_trading/on?token=not-the-token")
    assert engine.alert_only is True


def test_the_snapshot_reports_the_new_state_immediately(rig):
    """The page must not keep saying OFF after he pressed ON."""
    client, _engine, _ = rig
    press(client, "/api/bot_trading/on")
    got = client.get(f"/api/snapshot?token={TOKEN}").json()
    assert got["bot_trading"]["on"] is True


def test_the_switch_is_recorded_in_the_action_log(rig):
    client, _engine, controller = rig
    press(client, "/api/bot_trading/on")
    assert any("Bot trading ON" in text for _ok, text in controller.notes)


def test_a_session_with_no_engine_refuses_instead_of_crashing():
    class NoEngine:
        engine = None

        def get_snapshot(self):
            return {}

        def refresh(self):
            return None

    app = build_app(NoEngine(), _Controller(), _Loader(),
                    operator_token=TOKEN)
    response = TestClient(app).post(f"/api/bot_trading/on?token={TOKEN}")
    assert response.status_code == 200
    assert response.json()["success"] is False


# ---------------------------------------------------------------
# 2. BROKER STOP -- the one he asked me to check too
# ---------------------------------------------------------------
def test_pressing_broker_stop_ON_really_enables_it(rig):
    client, engine, _ = rig
    response = press(client, "/api/broker_stop/on")
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert engine.broker_stop.enabled is True


def test_it_prices_a_hard_stop_for_every_open_position(rig):
    """The endpoint hands in a hard_stop_for callback. If that
    callback is wrong the switch reports success and protects
    nothing."""
    client, engine, _ = rig
    got = press(client, "/api/broker_stop/on").json()
    assert got["placed"] == 1
    stop = got["prices"]["CGPOWER"]
    assert stop is not None
    assert 0 < stop < 871.7, f"a LONG's stop must sit below entry, got {stop}"


def test_pressing_it_OFF_cancels_the_resting_orders(rig):
    """A stop left resting against a position that has closed SELLS
    STOCK NOT HELD."""
    client, engine, _ = rig
    press(client, "/api/broker_stop/on")
    press(client, "/api/broker_stop/off")
    assert engine.broker_stop.enabled is False
    assert engine.broker_stop.cancelled is True


def test_broker_stop_needs_the_token_too(rig):
    client, engine, _ = rig
    response = client.post("/api/broker_stop/on")
    assert response.status_code in (401, 403)
    assert engine.broker_stop.enabled is False


def test_a_broker_that_refuses_is_reported_not_swallowed(rig):
    """"Nothing happened" and "the broker said no" must never look the
    same on his screen."""
    client, engine, _ = rig

    def explode(**_kwargs):
        raise RuntimeError("Dhan rejected the stop")
    engine.broker_stop.enable = explode

    got = press(client, "/api/broker_stop/on").json()
    assert got["success"] is False
    assert "rejected" in got["error"]


def test_a_session_without_a_broker_stop_says_so(rig):
    client, engine, _ = rig
    engine.broker_stop = None
    got = press(client, "/api/broker_stop/on").json()
    assert got["success"] is False
    assert "not wired" in got["error"]


# ---------------------------------------------------------------
# 3. THE TWO SWITCHES ARE INDEPENDENT
# ---------------------------------------------------------------
def test_stopping_the_bot_does_not_remove_the_broker_stops(rig):
    """He stops new entries in a panic. The protection on what he is
    already holding must survive that click."""
    client, engine, _ = rig
    press(client, "/api/broker_stop/on")
    press(client, "/api/bot_trading/off")
    assert engine.broker_stop.enabled is True


def test_arming_the_bot_does_not_silently_change_the_broker_stop(rig):
    client, engine, _ = rig
    press(client, "/api/bot_trading/on")
    assert engine.broker_stop.enabled is False


# ---------------------------------------------------------------
# THE MORNING GUARD -- proven on its own, not forced
# ---------------------------------------------------------------
#     "i'll start that by 7:30 daily is that good enough to catchup &
#      build watchlist by bot?"        -- operator, 6 August 2026
#
# Measured that morning: the pre-open gapper card posted 09:08 and
# reached the store 09:45 -- thirty minutes after the open. Row 1 of
# his watchlist was empty and looked exactly like a morning with no
# good results.
def test_it_refuses_to_arm_when_the_morning_is_not_ready(rig, monkeypatch):
    """No force flag. The guard must actually stop it.

    ---- THE TEST MUST OWN THE CONDITION. 7 August 2026. ----
    The first version relied on the real data/telegram.db being stale.
    On a healthy morning the store IS current, the guard correctly does
    not fire, and the test failed for the one reason that is not a
    fault. A test whose result depends on the weather cannot tell you
    anything. So it states the condition itself."""
    import core.morning_ready as morning_ready
    monkeypatch.setattr(morning_ready, "check", lambda *a, **k: {
        "ready": False,
        "checks": [{"name": "feed alive", "ok": False, "blocks": True,
                    "detail": "nothing stored for 300 min"}],
        "blocking": ["feed alive"],
        "why_not": ["nothing stored for 300 min"]})
    client, engine, _ = rig
    response = client.post(f"/api/bot_trading/on?token={TOKEN}")
    got = response.json()
    assert got["success"] is False, (
        "it armed on inputs that had not arrived")
    assert got.get("not_ready"), "it refused without saying what is missing"
    assert "not ready to trade" in str(got.get("error", ""))
    assert engine.alert_only is True, "it armed anyway"


def test_the_refusal_names_what_is_missing(rig, monkeypatch):
    """A refusal he cannot act on is just a different silence."""
    import core.morning_ready as morning_ready
    monkeypatch.setattr(morning_ready, "check", lambda *a, **k: {
        "ready": False,
        "checks": [{"name": "feed alive", "ok": False, "blocks": True,
                    "detail": "nothing stored for 300 min"}],
        "blocking": ["feed alive"],
        "why_not": ["nothing stored for 300 min"]})
    client, _engine, _ = rig
    got = client.post(f"/api/bot_trading/on?token={TOKEN}").json()
    for check in got.get("checks") or []:
        assert check.get("name"), "a check with no name"
        assert check.get("detail"), f"{check['name']} refused with no reason"


def test_he_can_still_override_it(rig):
    """It is his money. The guard makes it deliberate, not impossible."""
    client, engine, _ = rig
    got = client.post(f"/api/bot_trading/on?token={TOKEN}&force=1").json()
    assert got["success"] is True, "force=1 did not arm it"
    assert engine.alert_only is False, "it said success and did nothing"
