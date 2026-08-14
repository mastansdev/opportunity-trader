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
        self.buy_qty_seen = []
        self.exit_qty_seen = []
        self.short_qty_seen = []
        self.exit_all_called = False
        self.pause_new_entries_called = False
        self.resume_new_entries_called = False
        # The server has called note_action on every write path since
        # the action log moved server-side (2026-07-28), but this fake
        # was never given it -- so all seven write tests were failing
        # with AttributeError, and the fake, not the server, was the
        # thing that was wrong. A stand-in that does not implement the
        # real interface tests nothing.
        self.noted = []

    def note_action(self, ok, text, at=None):
        self.noted.append({"ok": ok, "text": text, "at": at})

    def actions(self):
        return list(self.noted)

    # 2 August 2026: every request can now name a SIZE. qty=None is
    # what every caller before today meant -- the standard size on an
    # entry, the whole position on an exit -- so the lists keep holding
    # bare symbols and the sizes are recorded beside them. A fake that
    # does not implement the real interface tests nothing.
    def request_buy(self, symbol, qty=None):
        self.buys.append(symbol)
        self.buy_qty_seen.append(qty)

    def request_exit(self, symbol, qty=None):
        self.exits.append(symbol)
        self.exit_qty_seen.append(qty)

    def request_short(self, symbol, qty=None):
        self.shorts.append(symbol)
        self.short_qty_seen.append(qty)

    def request_exit_all(self):
        self.exit_all_called = True

    def request_pause_new_entries(self):
        self.pause_new_entries_called = True

    def resume_new_entries(self):
        self.resume_new_entries_called = True


class _FakeMasterLoader:
    def __init__(self, known_symbols, blocked=None):
        self.known = set(known_symbols)
        # 2 August 2026. /api/buy now refuses a stock that is NOT on
        # today's feed -- a blocked name produces no ticks, so the
        # request would sit in the controller's set forever and the
        # screen would report success. See
        # tests/test_manual_buy_needs_a_feed.py. This fake grew the
        # method the real loader has always had.
        self.blocked = dict(blocked or {})

    def get_by_symbol(self, symbol):
        return {"SECTOR": "IT"} if symbol in self.known else None

    def blocked_symbols(self):
        return dict(self.blocked)


def _client(snapshot=None, known_symbols=("TCS", "RELIANCE"),
            operator_token=None, blocked=None):
    state = _FakeDashboardState(snapshot)
    controller = _FakeTradeController()
    loader = _FakeMasterLoader(known_symbols, blocked=blocked)
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
    got = res.json()
    # The cached snapshot must arrive intact...
    assert got["ready"] is True and got["advances"] == 7
    # ...plus the two things the endpoint now adds on every request.
    # 11 August 2026: the cached snapshot FREEZES when the trading loop
    # ends at the close, so the switch state was stale forever. It is
    # recomputed live per request; served_at says how old the rest is.
    assert "bot_trading" in got
    assert "served_at" in got


def test_buy_known_symbol_requests_buy_on_controller():
    client, controller = _client(known_symbols=("TCS",))
    res = client.post("/api/buy/tcs")
    assert res.status_code == 200
    # "qty": None is the new field and it means "the standard size"
    assert res.json() == {"success": True, "qty": None}
    assert controller.buys == ["TCS"]


def test_buy_a_stock_that_is_not_on_todays_feed_is_refused():
    """2 August 2026. main.py subscribes to SUBSCRIBE=YES rows only and
    core/engine.py checks the buy queue inside the per-symbol TICK
    handler -- so a blocked stock produced no ticks, the request sat in
    the set forever, and the screen said success.

    The operator had just said "i can trade manually from dashboard"
    about the 235 names the turnover bar keeps out."""
    client, controller = _client(
        known_symbols=("TCS", "SKFINDIA"),
        blocked={"SKFINDIA": "turnover Rs 4.89cr median of 10 sessions "
                             "below Rs 5cr"})
    res = client.post("/api/buy/skfindia")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
    assert "4.89cr" in body["error"], "the real reason must reach him"
    assert controller.buys == [], "nothing may be queued"


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
    assert res.json() == {"success": True, "qty": None}
    assert controller.exits == ["RELIANCE"]


def test_short_known_symbol_requests_short_on_controller():
    client, controller = _client(known_symbols=("TCS",))
    res = client.post("/api/short/tcs")
    assert res.status_code == 200
    assert res.json() == {"success": True, "qty": None}
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


# ---- "/" IS THE REACT SCREEN NOW. 6 August 2026. ----
#
# The React page reads the token off the URL query itself, so nothing
# is embedded into its HTML. Token EMBEDDING is the old page's
# contract, and the old page lives at /screen -- so that is what these
# two must drive. Left pointed at "/" they were asserting the old
# behaviour against the new page and failing for the right reason.
def test_index_with_correct_token_embeds_it_in_the_page():
    client, _ = _client(operator_token="secret123")
    res = client.get("/screen?token=secret123")
    assert res.status_code == 200
    assert 'window.__OPERATOR_TOKEN__ = "secret123";' in res.text


def test_index_with_wrong_or_missing_token_does_not_embed_anything():
    client, _ = _client(operator_token="secret123")

    res_wrong = client.get("/screen?token=nope")
    assert 'window.__OPERATOR_TOKEN__ = "secret123"' not in res_wrong.text
    assert 'window.__OPERATOR_TOKEN__ = "";' in res_wrong.text

    res_missing = client.get("/screen")
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
    got = res.json()
    assert got["ready"] is True and got["advances"] == 5

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"ready": True, "advances": 5}


# ---------------------------------------------------------------
# One bad number must never blank the whole dashboard
# ---------------------------------------------------------------

def test_a_nan_anywhere_costs_one_field_not_the_whole_payload():
    """JSON has no NaN, and both FastAPI and websocket.send_json
    refuse the ENTIRE payload over one -- every panel blank, no error
    anywhere on screen. This bot goes live with real money on
    3 August; a stray NaN may cost a field, never the operator's whole
    view of the market."""
    from dashboard.server import _json_safe
    dirty = {"ok": 1.5, "bad": float("nan"), "worse": float("inf"),
             "rows": [{"pnl": float("-inf")}, {"pnl": 12.0}],
             "text": "fine", "none": None}
    clean = _json_safe(dirty)
    assert clean["ok"] == 1.5
    assert clean["bad"] is None
    assert clean["worse"] is None
    assert clean["rows"] == [{"pnl": None}, {"pnl": 12.0}]
    assert clean["text"] == "fine"
    import json
    json.dumps(clean, allow_nan=False)


def test_json_safe_leaves_a_clean_payload_untouched():
    from dashboard.server import _json_safe
    payload = {"a": [1, 2.5, "x", None], "b": {"c": True}}
    assert _json_safe(payload) == payload


def test_a_set_never_kills_the_websocket_again():
    """The real one: risk_filters.circuit_flagged_symbols arrived as a
    set and every push died --

        TypeError: Object of type set is not JSON serializable
        when serializing dict item 'circuit_flagged_symbols'

    -- so the browser received nothing at all and every panel sat
    blank, with the error only in the terminal."""
    from dashboard.server import _json_safe
    clean = _json_safe({"risk_filters": {
        "circuit_flagged_symbols": {"TCS", "INFY"},
        "frozen_symbols": frozenset(["HFCL"])}})
    assert clean["risk_filters"]["circuit_flagged_symbols"] == ["INFY", "TCS"]
    assert clean["risk_filters"]["frozen_symbols"] == ["HFCL"]


def test_datetimes_and_oddities_survive_as_text():
    from datetime import datetime
    from decimal import Decimal
    from dashboard.server import _json_safe
    clean = _json_safe({"at": datetime(2026, 7, 29, 15, 30), "d": Decimal("1.5")})
    assert clean["at"] == "2026-07-29T15:30:00"
    assert clean["d"] == "1.5"


def test_the_websocket_itself_survives_a_snapshot_full_of_junk():
    """The endpoint I never actually opened. /api/snapshot passed
    because FastAPI's encoder handles sets on its own -- the websocket
    does NOT, and the websocket is what the page reads."""
    import json
    from datetime import datetime
    dirty = {"ready": True,
             "risk_filters": {"circuit_flagged_symbols": {"TCS"}},
             "pnl": float("nan"),
             "updated_at": datetime(2026, 7, 29, 15, 30)}
    client, _ = _client(snapshot=dirty)
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
    assert data["risk_filters"]["circuit_flagged_symbols"] == ["TCS"]
    assert data["pnl"] is None
    json.dumps(data, allow_nan=False)


# ---------------------------------------------------------------
# /api/snapshot MUST BE SANITISED, NOT RAW
# ---------------------------------------------------------------
#     ValueError: Out of range float values are not JSON compliant:
#     nan ... when serializing dict item 'sector'
#                                     -- live session, 5 August 2026
#
# The WEBSOCKET has always sent _json_safe(...). This endpoint returned
# the payload raw, so the same snapshot the page renders happily killed
# every REST read with a 500. It went unnoticed for weeks because the
# page uses /ws and nothing else called this until a tool did.
#
# One NaN from an empty cell in master_stocks.csv refuses the ENTIRE
# payload, not the offending field. That is what _json_safe is for.
def test_the_rest_snapshot_survives_a_nan():
    """The exact payload shape that 500'd: a NaN nested inside rows."""
    bad = {"news_impact": {"rows": [{"sector": float("nan")}]},
           "watchlist": {"unknown": [{"sector": float("nan")}]}}
    client, _ = _client(snapshot=bad)
    res = client.get("/api/snapshot")
    assert res.status_code == 200, res.text
    assert res.json()["news_impact"]["rows"][0]["sector"] is None


def test_the_rest_snapshot_survives_a_set():
    """The other value that killed the websocket once already."""
    client, _ = _client(snapshot={"risk_filters": {"flagged": {"B", "A"}}})
    res = client.get("/api/snapshot")
    assert res.status_code == 200
    assert res.json()["risk_filters"]["flagged"] == ["A", "B"]


def test_the_rest_and_the_socket_use_the_same_sanitiser():
    """They diverged once. A second REST endpoint added later must not
    quietly skip it again."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    block = code[code.find('@app.get("/api/snapshot")'):
                 code.find('@app.get("/api/mode")')]
    # The REST route now builds on the snapshot rather than returning
    # it raw -- the switch state is recomputed live -- but it must
    # still go through the same sanitiser as the socket.
    assert "_json_safe(payload)" in block
    assert "dashboard_state.get_snapshot()" in block
