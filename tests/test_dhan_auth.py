"""
The bot mints its own Dhan token, 11 August 2026.

    "dhan provides us Access Token & API Key toggle. we are using
     Access Token manually generating tokens , why cant we use API Key?"

THE POINT OF EVERY TEST BELOW
-----------------------------
Convenience on the auth path is the most dangerous kind of convenience,
because when it fails it fails at 09:00 and the whole session is gone.
So the load-bearing tests here are not the ones proving the mint works.
They are the ones proving that every possible way the mint can fail
still leaves him with the token that was already in .env.
"""

import base64
import os

import pytest

from core import dhan_auth


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    """---- A TEST WROTE A FAKE TOKEN INTO THE LIVE CACHE. ----
           13 August 2026.

    core/dhan_auth.py gained an on-disk token cache that morning so a
    restart stops re-minting (Dhan allows one every two minutes). The
    tests here did not know about it, so the first run put a
    one-character token with a 2099 expiry into the REAL
    data/dhan_token.json -- and main.py starting afterwards would have
    read that and failed to authenticate.

    The cache is redirected into tmp_path for every test in this file.
    A unit test must not be able to reach a live credential, in either
    direction: it must not read one and it must not write one.
    """
    monkeypatch.setattr(dhan_auth, "TOKEN_CACHE",
                        str(tmp_path / "dhan_token.json"))
    dhan_auth.reset()
    yield
    dhan_auth.reset()


SECRET = base64.b32encode(b"12345678901234567890").decode()


# ---------------------------------------------------------------
# RFC 6238 -- the arithmetic, against the published vectors
# ---------------------------------------------------------------

def test_the_totp_matches_the_rfc_test_vectors():
    """RFC 6238 Appendix B, SHA-1, secret '12345678901234567890'. If
    this passes, the code the bot computes is the code the
    authenticator app on his phone is showing."""
    assert dhan_auth.totp_now(SECRET, at=59) == "287082"
    assert dhan_auth.totp_now(SECRET, at=1111111109) == "081804"
    assert dhan_auth.totp_now(SECRET, at=1234567890) == "005924"


def test_a_spaced_lowercase_secret_still_works():
    """Dhan shows the secret in spaced groups and people paste it as
    shown. Refusing that would look like a credentials fault."""
    messy = " ".join([SECRET[i:i + 4] for i in range(0, len(SECRET), 4)])
    assert dhan_auth.totp_now(messy.lower(), at=59) == "287082"


def test_an_unpadded_secret_still_works():
    assert dhan_auth.totp_now(SECRET.rstrip("="), at=59) == "287082"


def test_the_whole_otpauth_link_works_as_the_secret():
    """11 August, his first report: "code shown in not matched".

    Beside the QR, Dhan shows a secret. Behind the QR is an
    otpauth:// link. Copying the link instead of the text is the most
    natural mistake in the flow, and it used to decode to nothing --
    which reads as "wrong secret" when the secret is perfectly right.
    """
    link = f"otpauth://totp/DhanHQ:1109?secret={SECRET}&issuer=DhanHQ"
    assert dhan_auth.totp_now(link, at=59) == "287082"


def test_a_tab_or_newline_in_the_pasted_secret_is_forgiven():
    assert dhan_auth.totp_now(f"\t{SECRET}\n", at=59) == "287082"


# ---------------------------------------------------------------
# Wrong secret vs wrong clock -- the whole diagnosis
# ---------------------------------------------------------------

def test_the_neighbouring_windows_are_offered_for_comparison():
    """If his phone shows the code from -60s, the secret is RIGHT and
    the PC clock is 60s slow. Printing only 'now' cannot tell him that,
    and sends him to re-copy a secret that was never the problem."""
    rows = dhan_auth.codes_around(SECRET, windows=2, at=1234567890)
    assert [r["offset_seconds"] for r in rows] == [-60, -30, 0, 30, 60]
    assert [r for r in rows if r["is_now"]][0]["code"] == "005924"


def test_the_window_codes_are_the_ones_that_clock_would_produce():
    at = 1234567890
    rows = dhan_auth.codes_around(SECRET, windows=1, at=at)
    for row in rows:
        assert row["code"] == dhan_auth.totp_now(
            SECRET, at=at + row["offset_seconds"])


def test_a_skewed_clock_is_retried_on_dhans_time(monkeypatch):
    """The repair, not just the diagnosis. A Windows clock a minute out
    makes a perfect secret fail every time with an error that reads as
    bad credentials. One retry on the server's clock gets him traded."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setattr(dhan_auth, "clock_skew", lambda: {"skew": 75.0})

    right = dhan_auth.totp_now(SECRET, at=__import__("time").time() - 75.0)
    tried = []

    def _fussy(url):
        tried.append(url)
        return ({"accessToken": "t", "expiryTime": "2099-01-01T00:00:00"}
                if f"totp={right}" in url else {"errorType": "Invalid_TOTP"})

    monkeypatch.setattr(dhan_auth, "_post", _fussy)
    assert dhan_auth.mint()["token"] == "t"
    assert len(tried) == 2, "it must retry exactly once, not loop"


def test_a_small_skew_is_not_retried(monkeypatch):
    """Inside half a window the code is identical, so a retry would be
    the same request twice and a wasted attempt against Dhan's count."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setattr(dhan_auth, "clock_skew", lambda: {"skew": 3.0})
    tried = []
    monkeypatch.setattr(dhan_auth, "_post",
                        lambda url: tried.append(url) or {"e": "no"})
    assert dhan_auth.mint()["token"] is None
    assert len(tried) == 1


def test_the_retry_never_becomes_an_infinite_loop(monkeypatch):
    """Dhan counts attempts. A retry that retries locks the account."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setattr(dhan_auth, "clock_skew", lambda: {"skew": 900.0})
    tried = []
    monkeypatch.setattr(dhan_auth, "_post",
                        lambda url: tried.append(url) or {"e": "no"})
    dhan_auth.mint()
    assert len(tried) <= 2


def test_an_unreachable_clock_check_does_not_break_the_mint(monkeypatch):
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "the-one-he-pasted")
    monkeypatch.setattr(dhan_auth, "clock_skew",
                        lambda: {"skew": None, "why": "offline"})
    monkeypatch.setattr(dhan_auth, "_post", lambda url: {"e": "no"})
    assert dhan_auth.access_token() == "the-one-he-pasted"


def test_clock_skew_never_raises_when_the_network_is_down(monkeypatch):
    monkeypatch.setattr(
        dhan_auth.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))
    assert dhan_auth.clock_skew()["skew"] is None


def test_rubbish_returns_none_rather_than_raising():
    for bad in ("", None, "not base32!!", "1"):
        assert dhan_auth.totp_now(bad) is None


def test_the_code_is_six_digits_including_leading_zeros():
    """005924 must not become 5924. A stripped leading zero is a five
    digit code and a rejected login."""
    got = dhan_auth.totp_now(SECRET, at=1234567890)
    assert len(got) == 6 and got.startswith("00")


# ---------------------------------------------------------------
# The fallback -- the reason this module is allowed to exist
# ---------------------------------------------------------------

def test_no_totp_configured_means_the_env_token_unchanged(monkeypatch):
    """His morning today. Nothing about it may change."""
    monkeypatch.delenv("DHAN_TOTP_SECRET", raising=False)
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "the-one-he-pasted")
    assert dhan_auth.access_token() == "the-one-he-pasted"
    assert dhan_auth.source() == "env"


def test_a_dead_auth_server_falls_back_and_says_so(monkeypatch):
    """auth.dhan.co being unreachable at 08:55 must cost him nothing."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "the-one-he-pasted")
    monkeypatch.setattr(dhan_auth, "_post",
                        lambda url: (_ for _ in ()).throw(OSError("no route")))
    assert dhan_auth.access_token() == "the-one-he-pasted"
    assert dhan_auth.source() == "env"
    assert "fall" in dhan_auth.describe().lower()


def test_a_refusal_from_dhan_falls_back_too(monkeypatch):
    """Wrong pin, expired TOTP setup, rate limit -- all one outcome."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "the-one-he-pasted")
    monkeypatch.setattr(dhan_auth, "_post",
                        lambda url: {"errorType": "Invalid_Authentication"})
    assert dhan_auth.access_token() == "the-one-he-pasted"


def test_a_missing_pin_never_reaches_the_network(monkeypatch):
    """Half-configured is the likeliest state on day one, and it must
    not spend a request or a consent to find that out."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.delenv("DHAN_PIN", raising=False)
    calls = []
    monkeypatch.setattr(dhan_auth, "_post", lambda url: calls.append(url))
    got = dhan_auth.mint()
    assert got["token"] is None
    assert "DHAN_PIN" in got["why"]
    assert calls == []


def test_access_token_is_always_a_string(monkeypatch):
    """main.py builds DhanContext with whatever this returns. None
    there is an AttributeError three frames deep in the SDK."""
    monkeypatch.delenv("DHAN_TOTP_SECRET", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    assert dhan_auth.access_token() == ""


# ---------------------------------------------------------------
# The mint, when it works
# ---------------------------------------------------------------

def test_a_good_mint_returns_the_token_and_the_expiry(monkeypatch):
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setattr(dhan_auth, "_post", lambda url: {
        "dhanClientId": "1000000001", "accessToken": "eyJ.fresh.token",
        "expiryTime": "2026-08-12T09:00:00.000"})
    assert dhan_auth.access_token() == "eyJ.fresh.token"
    assert dhan_auth.source() == "totp"


def test_the_request_carries_client_pin_and_code(monkeypatch):
    """All three, or Dhan rejects it. Checked because a silently
    dropped parameter reads as a credentials problem."""
    seen = {}
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "424242")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")

    def _capture(url):
        seen["url"] = url
        return {"accessToken": "t"}

    monkeypatch.setattr(dhan_auth, "_post", _capture)
    dhan_auth.mint()
    assert "dhanClientId=1000000001" in seen["url"]
    assert "pin=424242" in seen["url"]
    assert "totp=" in seen["url"]


def test_it_posts_to_dhans_documented_endpoint():
    assert dhan_auth.MINT_URL == (
        "https://auth.dhan.co/app/generateAccessToken")


def test_a_held_token_is_not_reminted_every_call(monkeypatch):
    """Dhan counts these. One per session, not one per import."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    mints = []

    def _once(url):
        mints.append(url)
        return {"accessToken": "t", "expiryTime": "2099-01-01T00:00:00"}

    monkeypatch.setattr(dhan_auth, "_post", _once)
    for _ in range(5):
        dhan_auth.access_token()
    assert len(mints) == 1


# ---------------------------------------------------------------
# No secret ever reaches a log
# ---------------------------------------------------------------

def test_describe_prints_no_secret_and_no_token(monkeypatch):
    """This line goes on the startup banner, which he screenshots."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setattr(dhan_auth, "_post", lambda url: {
        "accessToken": "eyJ.secret.value", "expiryTime": "2099-01-01T00:00:00"})
    dhan_auth.access_token()
    said = dhan_auth.describe()
    assert "eyJ.secret.value" not in said
    assert SECRET not in said
    assert "111111" not in said


def test_the_module_never_writes_the_secret_anywhere():
    """The SECRET has one home: the environment.

    ---- NARROWED, DELIBERATELY. 13 August 2026. ----

    This used to forbid the module from writing ANYTHING -- no
    json.dump, no open(), no sqlite. That blanket ban was written to
    protect DHAN_TOTP_SECRET, which is permanent: anyone holding it can
    mint tokens for this account forever.

    It also blocked caching the minted TOKEN, and that turned out to
    cost something real. The token lasts 24 hours and the cache was
    process memory, so every `py main.py` asked Dhan for a new one --
    and Dhan allows one every two minutes:

        "TOTP mint failed (Dhan refused the request: 'Token can be
         generated once every 2 minutes.')"
        "but i started just now on morning"

    A 24-hour credential re-minted once per process is the fault. So
    the token is now cached to data/dhan_token.json.

    THE PROTECTION THAT MATTERED IS KEPT AND MADE EXPLICIT: the secret
    itself must never be written, and the cache must contain only the
    token, its expiry and a note. A 24-hour token in a gitignored file
    under data/ is the same trust level as the Telegram session that
    already lives there, and as DHAN_ACCESS_TOKEN in .env.
    """
    import inspect
    src = inspect.getsource(dhan_auth)
    for forbidden in ("sqlite3", "shelve", "pickle"):
        assert forbidden not in src, f"{forbidden} on the auth path"

    # The one write this module performs, read back field by field.
    written = inspect.getsource(dhan_auth._write_cache)
    for leak in ("DHAN_TOTP_SECRET", "secret", "DHAN_PIN", "pin"):
        assert leak not in written, (
            f"_write_cache mentions {leak!r} -- the cache must hold the "
            f"token and its expiry, nothing that could mint another")


def test_the_cache_holds_only_the_token_and_its_expiry(tmp_path,
                                                       monkeypatch):
    """Checked against the FILE, not the source. A field added later
    that happens to carry a secret would pass a source scan."""
    import json
    from datetime import datetime, timedelta

    monkeypatch.setattr(dhan_auth, "TOKEN_CACHE", str(tmp_path / "t.json"))
    dhan_auth._write_cache("a-token", datetime.now() + timedelta(hours=24),
                           "minted")
    with open(dhan_auth.TOKEN_CACHE, encoding="utf-8") as handle:
        held = json.load(handle)
    assert set(held) <= {"token", "expires", "why", "written_at"}, (
        f"unexpected fields in the token cache: {sorted(held)}")
    blob = json.dumps(held)
    for leak in ("JBSWY", "DHAN_TOTP_SECRET", "DHAN_PIN"):
        assert leak not in blob


def test_a_refusal_body_is_truncated_in_the_reason(monkeypatch):
    """Dhan's error bodies can echo the request. Cap what we quote."""
    monkeypatch.setenv("DHAN_TOTP_SECRET", SECRET)
    monkeypatch.setenv("DHAN_PIN", "111111")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1000000001")
    monkeypatch.setattr(dhan_auth, "_post", lambda url: {"e": "x" * 5000})
    assert len(dhan_auth.mint()["why"]) < 300


# ---------------------------------------------------------------
# main.py must actually use it
# ---------------------------------------------------------------

def test_main_builds_every_dhan_client_from_the_minted_token():
    """Three places build a DhanContext -- REST, orders, and the
    WebSocket feed via dhan_context. If one still reads the raw env
    token, that connection dies at midnight while the others live."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(
        encoding="utf-8", errors="replace")
    assert "dhan_auth.access_token()" in src
    assert "DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)" not in src


def test_the_banner_says_which_door_the_token_came_through():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(
        encoding="utf-8", errors="replace")
    assert "dhan_auth.describe()" in src


def test_env_example_documents_both_new_keys():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath(
        ".env.example").read_text(encoding="utf-8", errors="replace")
    assert "DHAN_TOTP_SECRET" in src and "DHAN_PIN" in src
