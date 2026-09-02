"""---- THE DESK IS THE DASHBOARD NOW. 2 September 2026. ----

    "this is better than current dashboard"
    "make this my real dashboard with remaining tabs"
                                            -- the operator

/desk answers the five questions a trader actually asks, in the order
they are asked: where am I, what is moving, what would I do about it,
what am I holding, what have I done. The other seven tabs sit behind
it as reference.

WHAT THIS FILE DEFENDS

The failure this project keeps repeating is a layer that changed and a
layer that consumes it that did not -- so these tests do not check
that desk.html exists. They check that the route serves it, that the
operator token reaches it (without the token the page draws no BUY
control at all, which is how "the switch does nothing" starts), that
"/" actually lands there, and that /board is STILL REACHABLE, because
the rule since 6 August is that a new page goes beside the working one
and never in place of it. If the desk is wrong at 09:15 he types
/board and keeps trading.
"""

from fastapi.testclient import TestClient

from dashboard.server import build_app
from tests.test_dashboard_server import (_FakeDashboardState,
                                         _FakeMasterLoader,
                                         _FakeTradeController)

TOKEN = "s3cret"


def _client(operator_token=None, snapshot=None):
    app = build_app(_FakeDashboardState(snapshot), _FakeTradeController(),
                    _FakeMasterLoader(("TCS",)), operator_token=operator_token)
    return TestClient(app)


def test_the_desk_is_served():
    res = _client().get("/desk")
    assert res.status_code == 200
    assert "Opportunity Trader" in res.text


def test_the_desk_carries_all_eight_tabs():
    """He asked for the new design WITH the remaining tabs. A screen
    that dropped one would lose him a place he already reads."""
    body = _client().get("/desk").text
    for tab in ("live", "pre", "trade", "post", "watch", "brain",
                "tg", "refused"):
        assert f'data-tab="{tab}"' in body, f"the {tab} tab is missing"


def test_without_the_token_the_desk_draws_no_buy_button():
    """A read-only page must refuse at the BUTTON, not at the endpoint.
    The placeholder stays empty and IS_OPERATOR is false."""
    body = _client(operator_token=TOKEN).get("/desk").text
    assert 'window.__OPERATOR_TOKEN__ = "";' in body
    assert TOKEN not in body


def test_with_the_token_the_desk_can_trade():
    """The exact bug /board had on 11 August: served raw, placeholder
    never replaced, so the page drew "view only" on every row and the
    screen was useless to a man who trades by hand."""
    body = _client(operator_token=TOKEN).get(f"/desk?token={TOKEN}").text
    assert f'window.__OPERATOR_TOKEN__ = "{TOKEN}";' in body


def test_the_front_door_lands_on_the_desk():
    res = _client().get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/desk"


def test_the_front_door_carries_the_token_through():
    """Dropping it turns a working screen into a read-only one."""
    res = _client(operator_token=TOKEN).get(f"/?token={TOKEN}",
                                            follow_redirects=False)
    assert res.headers["location"] == f"/desk?token={TOKEN}"


def test_the_old_board_is_still_reachable():
    """BESIDE the working one, never in place of it. If the desk is
    wrong on a live morning, this is the way back."""
    assert _client().get("/board").status_code == 200


def test_the_desk_never_500s_on_a_half_built_snapshot():
    """The page polls /api/snapshot every 3 seconds, including before
    the first build finishes and after the session ends. Every section
    it reads may legitimately be absent."""
    client = _client(snapshot={"ready": False})
    assert client.get("/desk").status_code == 200
    assert client.get("/api/snapshot").status_code == 200
