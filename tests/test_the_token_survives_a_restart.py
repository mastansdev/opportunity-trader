"""
==========================================================
One token a day, not one a process
==========================================================

    "TOTP mint failed (Dhan refused the request: {'message': 'Token can
     be generated once every 2 minutes.', 'status': 'error'})
     -- falling back to DHAN_ACCESS_TOKEN"
    "but i started just now on morning"     -- operator, 13 August 2026

He had started once. TWO things asked Dhan for a token inside that one
morning:

  1. tools/dhan_token_check.py called access_token(force=True), which
     skips the cache and mints unconditionally. It was added to
     tools/morning.py's `token` step on 12 August and described as "the
     CHECK, not removed" -- it was really a second login.

  2. main.py then started and minted again, because core/dhan_auth.py's
     cache is PROCESS MEMORY. Dhan issues a 24-hour token and every
     restart threw it away.

Dhan allows one mint every two minutes, so the second was refused and
the bot fell back to the static .env token -- correctly, loudly, and
for no good reason.

Restarting twice inside two minutes is not unusual. It is what anybody
does when the first start looked wrong.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import pathlib
from datetime import datetime, timedelta

import pytest

import core.dhan_auth as auth

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    """Fresh module state and a cache nowhere near the real one."""
    monkeypatch.setattr(auth, "TOKEN_CACHE", str(tmp_path / "tok.json"))
    monkeypatch.setattr(auth, "_held",
                        {"token": None, "expires": None, "source": None,
                         "why": None, "clock_note": None})
    monkeypatch.setenv("DHAN_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "env-fallback-token")
    return tmp_path


def _cache(path, token="cached-token", hours=20):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"token": token,
                   "expires": (datetime.now()
                               + timedelta(hours=hours)).isoformat(),
                   "why": "minted earlier"}, handle)


def test_a_restart_reuses_a_good_token_instead_of_minting(_clean, monkeypatch):
    """THE REGRESSION. A fresh process must not ask Dhan again."""
    minted = []
    monkeypatch.setattr(auth, "mint",
                        lambda *a, **k: minted.append(1) or {"token": None})
    _cache(auth.TOKEN_CACHE)

    assert auth.access_token() == "cached-token"
    assert not minted, (
        "a restart minted a new token while a valid one was cached -- "
        "two starts inside two minutes will be refused by Dhan")


def test_a_nearly_expired_token_is_re_minted(_clean, monkeypatch):
    """The cache must not keep a token past its usefulness. Dhan's 24
    hours run out mid-session otherwise."""
    monkeypatch.setattr(auth, "mint", lambda *a, **k: {
        "token": "fresh", "expires": datetime.now() + timedelta(hours=24),
        "why": "minted"})
    _cache(auth.TOKEN_CACHE, hours=1)      # under REMINT_WHEN_UNDER_HOURS
    assert auth.access_token() == "fresh"


def test_a_token_with_no_expiry_is_not_trusted(_clean, monkeypatch):
    """An undateable credential must read as expired. Trusting a stale
    one is the failure this whole file guards."""
    monkeypatch.setattr(auth, "mint", lambda *a, **k: {
        "token": "fresh", "expires": datetime.now() + timedelta(hours=24),
        "why": "minted"})
    with open(auth.TOKEN_CACHE, "w", encoding="utf-8") as handle:
        json.dump({"token": "undateable", "expires": None}, handle)
    assert auth.access_token() == "fresh"


def test_force_still_mints(_clean, monkeypatch):
    """Deliberately re-minting must remain possible -- a rejected
    token, a changed pin."""
    monkeypatch.setattr(auth, "mint", lambda *a, **k: {
        "token": "forced", "expires": datetime.now() + timedelta(hours=24),
        "why": "minted"})
    _cache(auth.TOKEN_CACHE)
    assert auth.access_token(force=True) == "forced"


def test_a_successful_mint_is_written_for_the_next_process(
        _clean, monkeypatch):
    monkeypatch.setattr(auth, "mint", lambda *a, **k: {
        "token": "brand-new", "expires": datetime.now() + timedelta(hours=24),
        "why": "minted"})
    auth.access_token()
    with open(auth.TOKEN_CACHE, encoding="utf-8") as handle:
        assert json.load(handle)["token"] == "brand-new"


def test_an_unreadable_cache_never_breaks_the_session(_clean, monkeypatch):
    monkeypatch.setattr(auth, "mint", lambda *a, **k: {
        "token": "fresh", "expires": datetime.now() + timedelta(hours=24),
        "why": "minted"})
    with open(auth.TOKEN_CACHE, "w", encoding="utf-8") as handle:
        handle.write("{ this is not json")
    assert auth.access_token() == "fresh"


# ---------------------------------------------------------------
# THE OTHER HALF: the morning check must not burn a mint
# ---------------------------------------------------------------

def test_the_morning_check_does_not_force_a_mint():
    src = (ROOT / "tools" / "dhan_token_check.py").read_text(
        encoding="utf-8", errors="replace")
    assert "access_token(force=force)" in src, (
        "tools/dhan_token_check.py mints unconditionally again. It runs "
        "as tools/morning.py's `token` step, so main.py starting a "
        "minute later is refused by Dhan's 2-minute rate limit.")
    assert '"--force" in sys.argv' in src, (
        "there is no way to deliberately re-mint any more")


def test_the_credential_is_not_committed():
    """The cache holds a live trading token. Anyone with it can trade
    the account until it expires."""
    import subprocess
    done = subprocess.run(
        ["git", "check-ignore", "data/dhan_token.json"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert done.returncode == 0, (
        "data/dhan_token.json is not gitignored -- a live Dhan access "
        "token would be committed to the repository")
