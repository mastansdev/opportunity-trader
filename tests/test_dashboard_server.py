"""
Decision-correctness tests for dashboard/server.py's app wiring.
Uses FastAPI's TestClient (no real socket/thread) against
build_app() directly -- start_dashboard()/stop_dashboard() (the
real uvicorn-in-a-thread lifecycle) are exercised manually via
main.py, not unit tested here, since they open a real port.
"""

from fastapi.testclient import TestClient

from dashboard.server import build_app


class _FakeDashboardState:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot or {"ready": True, "advances": 1}
        self.force_refresh_called = False

    def get_snapshot(self):
        return self._snapshot

    def force_gainers_losers_refresh(self):
        self.force_refresh_called = True


class _FakeTradeController:
    def __init__(self):
        self.buys = []
        self.exits = []
        self.shorts = []
        self.exit_all_called = False
        self.pause_new_entries_called = False
        self.resume_new_entries_called = False

    def request_buy(self, symbol):
        self.buys.append(symbol)

    def request_exit(self, symbol):
        self.exits.append(symbol)

    def request_short(self, symbol):
        self.shorts.append(symbol)

    def request_exit_all(self):
        self.exit_all_called = True

    def request_pause_new_entries(self):
        self.pause_new_entries_called = True

    def resume_new_entries(self):
        self.resume_new_entries_called = True


class _FakeMasterLoader:
    def __init__(self, known_symbols):
        self.known = set(known_symbols)

    def get_by_symbol(self, symbol):
        return {"SECTOR": "IT"} if symbol in self.known else None


def _client(snapshot=None, known_symbols=("TCS", "RELIANCE"), operator_token=None):
    state = _FakeDashboardState(snapshot)
    controller = _FakeTradeController()
    loader = _FakeMasterLoader(known_symbols)
    app = build_app(state, controller, loader, operator_token=operator_token)
    return TestClient(app), controller


def _client_with_state(snapshot=None, operator_token=None):
    state = _FakeDashboardState(snapshot)
    app = build_app(state, _FakeTradeController(), _FakeMasterLoader(("TCS",)),
                    operator_token=operator_token)
    return TestClient(app), state


def test_refresh_gainers_losers_forces_a_rebuild_no_token_needed():
    client, state = _client_with_state()
    res = client.post("/api/refresh_gainers_losers")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert state.force_refresh_called is True


def test_index_serves_the_dashboard_page():
    client, _ = _client()
    res = client.get("/")
    assert res.status_code == 200
    assert "Opportunity Trader" in res.text


def test_snapshot_endpoint_returns_current_state():
    client, _ = _client(snapshot={"ready": True, "advances": 7})
    res = client.get("/api/snapshot")
    assert res.status_code == 200
    assert res.json() == {"ready": True, "advances": 7}


def test_buy_known_symbol_requests_buy_on_controller():
    client, controller = _client(known_symbols=("TCS",))
    res = client.post("/api/buy/tcs")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert controller.buys == ["TCS"]


def test_buy_unknown_symbol_is_rejected_without_touching_controller():
    client, controller = _client(known_symbols=("TCS",))
    res = client.post("/api/buy/FAKESTOCK")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
    assert "FAKESTOCK" in body["error"]
    assert controller.buys == []


def test_sell_requests_exit_on_controller():
    client, controller = _client()
    res = client.post("/api/sell/reliance")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert controller.exits == ["RELIANCE"]


def test_short_known_symbol_requests_short_on_controller():
    client, controller = _client(known_symbols=("TCS",))
    res = client.post("/api/short/tcs")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert controller.shorts == ["TCS"]


def test_short_unknown_symbol_is_rejected_without_touching_controller():
    client, controller = _client(known_symbols=("TCS",))
    res = client.post("/api/short/FAKESTOCK")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
    assert "FAKESTOCK" in body["error"]
    assert controller.shorts == []


def test_exit_all_requests_exit_all_on_controller():
    client, controller = _client()
    res = client.post("/api/exit_all")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert controller.exit_all_called is True
    # Bare POST -- "Exit All only" -- must NOT also pause entries.
    assert controller.pause_new_entries_called is False


def test_exit_all_with_pause_true_also_pauses_new_entries():
    """2026-07-24, EXIT ALL popup's "Stop New Entries + Exit All"
    option -- ?pause=true."""
    client, controller = _client()
    res = client.post("/api/exit_all?pause=true")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert controller.exit_all_called is True
    assert controller.pause_new_entries_called is True


def test_exit_all_with_pause_false_behaves_like_the_bare_endpoint():
    client, controller = _client()
    res = client.post("/api/exit_all?pause=false")
    assert res.status_code == 200
    assert controller.exit_all_called is True
    assert controller.pause_new_entries_called is False


def test_resume_entries_endpoint_turns_entries_back_on():
    """2026-07-24 (evening): the paused-banner "Resume New Entries"
    button -> /api/resume_entries. Auto-resume was removed, so this
    manual endpoint is now the only way back on."""
    client, controller = _client()
    res = client.post("/api/resume_entries")
    assert res.status_code == 200
    assert res.json() == {"success": True}
    assert controller.resume_new_entries_called is True


def test_websocket_pushes_the_current_snapshot_on_connect():
    client, _ = _client(snapshot={"ready": True, "advances": 3})
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data == {"ready": True, "advances": 3}


# -- operator-token view-only gate (dashboard/access_token.py) --

def test_no_operator_token_configured_means_every_write_succeeds():
    """Backward compat: operator_token=None (the default) disables
    the gate entirely -- existing local-only behavior, unchanged."""
    client, controller = _client(operator_token=None)
    res = client.post("/api/buy/tcs")
    assert res.status_code == 200
    assert controller.buys == ["TCS"]


def test_index_with_correct_token_embeds_it_in_the_page():
    client, _ = _client(operator_token="secret123")
    res = client.get("/?token=secret123")
    assert res.status_code == 200
    assert 'window.__OPERATOR_TOKEN__ = "secret123";' in res.text


def test_index_with_wrong_or_missing_token_does_not_embed_anything():
    client, _ = _client(operator_token="secret123")

    res_wrong = client.get("/?token=nope")
    assert 'window.__OPERATOR_TOKEN__ = "secret123"' not in res_wrong.text
    assert 'window.__OPERATOR_TOKEN__ = "";' in res_wrong.text

    res_missing = client.get("/")
    assert 'window.__OPERATOR_TOKEN__ = "secret123"' not in res_missing.text
    assert 'window.__OPERATOR_TOKEN__ = "";' in res_missing.text


def test_write_endpoints_403_without_a_matching_token_header():
    client, controller = _client(operator_token="secret123", known_symbols=("TCS",))

    res = client.post("/api/buy/TCS")  # no X-Operator-Token header at all
    assert res.status_code == 403
    assert controller.buys == []

    res = client.post("/api/sell/TCS", headers={"X-Operator-Token": "wrong"})
    assert res.status_code == 403
    assert controller.exits == []

    res = client.post("/api/exit_all")
    assert res.status_code == 403
    assert controller.exit_all_called is False

    res = client.post("/api/short/TCS", headers={"X-Operator-Token": "wrong"})
    assert res.status_code == 403
    assert controller.shorts == []


def test_write_endpoints_succeed_with_the_matching_token_header():
    client, controller = _client(operator_token="secret123", known_symbols=("TCS",))
    headers = {"X-Operator-Token": "secret123"}

    res = client.post("/api/buy/TCS", headers=headers)
    assert res.status_code == 200
    assert controller.buys == ["TCS"]

    res = client.post("/api/exit_all", headers=headers)
    assert res.status_code == 200
    assert controller.exit_all_called is True


def test_read_endpoints_never_require_a_token():
    """Reads -- GET /api/snapshot and the websocket -- stay fully
    open to a view-only visitor; only writes are gated."""
    client, _ = _client(
        operator_token="secret123",
        snapshot={"ready": True, "advances": 5},
    )

    res = client.get("/api/snapshot")
    assert res.status_code == 200
    assert res.json() == {"ready": True, "advances": 5}

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"ready": True, "advances": 5}
