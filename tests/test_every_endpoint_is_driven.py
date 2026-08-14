"""
==========================================================
Press every button on the server. All nineteen.
==========================================================

    "see without asking you are not finding the bugs you created
     without knowing ... & do u expect me to blindly follow like you
     r doing with your code?"
                                -- operator, 5 August 2026

He is right, and the bug class is specific enough to hunt.

I write tests that READ SOURCE TEXT -- assert "x" in open(f).read() --
instead of DRIVING THE THING. Those pass while the feature is broken.
It is how core/ranker.py reached no order path through 3,541 green
tests, and how the operator token gate was wrong in one direction and
the page wrong in the other for a week.

An audit of dashboard/server.py found NINE of nineteen endpoints that
no test had ever called. Among them:

    POST /api/watchlist/...   the one that returned "Internal Server
                              Error" to his face, and whose fix has
                              never been proven
    WEBSOCKET /ws             every number on his screen
    WEBSOCKET /ws/prices      every price on his screen

This file drives all of them. Not their source -- them.

Author : H&M Opportunity Trader
==========================================================
"""

import json

import pytest
from fastapi.testclient import TestClient

from dashboard.server import build_app

TOKEN = "operator-token"


class _State:
    def __init__(self):
        self.engine = None
        self.added = []

    def get_snapshot(self):
        return {"ok": True, "prices": {"TCS": 100.0}}

    def refresh(self):
        return None

    def watchlist_store(self):
        return self

    # WatchlistStore's real surface -- checked against the class below.
    def add(self, symbol, note=None):
        self.added.append(symbol)
        return True

    def remove(self, symbol):
        return symbol in self.added

    def symbols(self):
        return list(self.added)

    # The REAL method names, read off DashboardState -- card_for() and
    # price_check_rows(). My first stub invented stock_card() and three
    # tests failed on my own fake rather than on the server.
    def card_for(self, symbol):
        return {"symbol": symbol}

    def price_check_rows(self):
        return []


class _Controller:
    def note_action(self, ok, text):
        return None


class _Loader:
    def get_by_symbol(self, symbol):
        return {"SECTOR": "IT"} if symbol in ("TCS", "STYRENIX") else None

    def blocked_symbols(self):
        return {}

    def all_symbols(self, include_blocked=False):
        return ["TCS", "STYRENIX", "RELIANCE"]


@pytest.fixture
def client():
    return TestClient(build_app(_State(), _Controller(), _Loader(),
                                operator_token=TOKEN))


def q(path):
    return f"{path}?token={TOKEN}"


# ---------------------------------------------------------------
# 1. THE PAGES RENDER AT ALL
# ---------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/screen", "/full"])
def test_the_page_loads(client, path):
    """A 500 here is a blank screen at 09:15."""
    response = client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    assert len(response.text) > 500, f"{path} came back nearly empty"


def test_the_two_links_serve_the_same_screen():
    """     "only one universal screen required for now"

    The React screen answers on BOTH "/" and "/app" as of 6 August
    2026, so those are the two that must match. /screen and /old are
    the deliberate fallback to the pre-React page for the case where
    the CDN that serves React cannot be reached at 09:15 -- they are
    not expected to be identical, and asserting that they were is what
    made this test fail when the default page changed.
    """
    got = TestClient(build_app(_State(), _Controller(), _Loader()))
    assert got.get("/").text == got.get("/app").text


def test_the_fallback_page_still_answers():
    """If React cannot load, there must still be a screen."""
    got = TestClient(build_app(_State(), _Controller(), _Loader()))
    for path in ("/screen", "/old"):
        assert got.get(path).status_code == 200, path
        assert len(got.get(path).text) > 500, path


# ---------------------------------------------------------------
# 2. THE READ ENDPOINTS ANSWER
# ---------------------------------------------------------------
@pytest.mark.parametrize("path", ["/api/mode", "/api/symbols",
                                  "/api/price_check", "/api/snapshot"])
def test_the_read_endpoints_return_json(client, path):
    response = client.get(q(path))
    assert response.status_code == 200, f"{path} -> {response.text[:120]}"
    json.loads(response.text)               # raises if it is not JSON


def test_the_symbol_list_is_not_empty(client):
    """The watchlist search box reads this. Empty means he can type a
    name and get nothing, with no error to explain it."""
    got = client.get(q("/api/symbols")).json()
    rows = got.get("symbols", got) if isinstance(got, dict) else got
    assert rows, "the search box has nothing to offer"


def test_the_stock_card_answers_for_a_known_symbol(client):
    response = client.get(q("/api/stock/TCS"))
    assert response.status_code == 200, response.text[:150]


def test_the_stock_card_does_not_500_on_an_unknown_symbol(client):
    """He will mistype. A traceback on the screen is not an answer."""
    response = client.get(q("/api/stock/NOTAREALSTOCK"))
    assert response.status_code < 500, response.text[:150]


# ---------------------------------------------------------------
# 3. THE WATCHLIST -- THE ONE THAT FAILED IN HIS FACE
# ---------------------------------------------------------------
#     "could not send: SyntaxError: Unexpected token 'I',
#      "Internal S"... is not valid JSON"
#
# That was a 500 from master_loader.known_symbols(), a method I
# invented. The fix -- all_symbols(include_blocked=True) -- has never
# been driven by a test until now.
def test_adding_a_stock_to_the_watchlist_works(client):
    response = client.post(q("/api/watchlist/add/STYRENIX"))
    assert response.status_code == 200, response.text[:200]
    assert response.json().get("success") is True, response.text[:200]


def test_removing_one_works(client):
    client.post(q("/api/watchlist/add/STYRENIX"))
    response = client.post(q("/api/watchlist/remove/STYRENIX"))
    assert response.status_code == 200, response.text[:200]


def test_an_unknown_symbol_is_refused_in_json_not_in_a_traceback(client):
    """The 500 is the bug. A refusal is fine; HTML in a JSON parser is
    not."""
    response = client.post(q("/api/watchlist/add/NOTAREALSTOCK"))
    assert response.status_code < 500, response.text[:200]
    json.loads(response.text)


def test_the_watchlist_needs_the_operator_token(client):
    """It answers 200 with success=False rather than a bare 403, so the
    page can SHOW him why the click did nothing. Refusing is the
    contract; the status code is not."""
    response = client.post("/api/watchlist/add/TCS")
    assert response.json()["success"] is False
    assert "read-only" in response.json()["error"]


def test_the_loader_method_the_endpoint_calls_is_real():
    """known_symbols() did not exist. The test passed anyway because I
    wrote the fake loader and gave it the name I had invented."""
    import inspect

    from core.master_loader import MasterLoader
    real = {n for n, _ in inspect.getmembers(MasterLoader)}
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):]
    block = block[:block.find("@app.")]
    for call in set(__import__("re").findall(r"master_loader\.(\w+)", block)):
        assert call in real, f"master_loader.{call}() does not exist"


# ---------------------------------------------------------------
# 4. THE TWO WEBSOCKETS -- EVERY NUMBER ON HIS SCREEN
# ---------------------------------------------------------------
def test_the_snapshot_socket_pushes(client):
    with client.websocket_connect("/ws") as ws:
        got = ws.receive_json()
    assert isinstance(got, dict) and got, "the screen would stay blank"


def test_the_price_socket_pushes(client):
    """250ms channel. "ABSOLUTELY - LATENCY FIRST"."""
    with client.websocket_connect("/ws/prices") as ws:
        got = ws.receive_json()
    assert isinstance(got, dict), "prices would never move"


def test_what_the_socket_sends_survives_json(client):
    """A NaN sector crashed /api/snapshot on 5 August. The socket used
    _json_safe and the REST route did not."""
    with client.websocket_connect("/ws") as ws:
        json.dumps(ws.receive_json())


def test_the_rest_snapshot_is_sanitised_the_same_way(client):
    """Both paths serve the same object. Only one used to be safe."""
    json.dumps(client.get(q("/api/snapshot")).json())
