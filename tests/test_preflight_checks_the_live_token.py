"""
==========================================================
The preflight must check the credential the session uses
==========================================================

    [AUTH] Dhan token minted by the bot (TOTP), 280 chars.
           minted by the bot, good until 14 Aug 08:36
    [ OK ] 1. Dhan access token is present and not expired
              alive now, expires 13 Aug 08:47 IST. Generate the morning
              token as usual before 09:15: py tools/dhan_token.py

Four lines apart, on one startup, 13 August 2026. Both cannot be true.

Stage 1 read config.DHAN_ACCESS_TOKEN -- the static token in .env --
while core/dhan_auth.py mints a fresh 24-hour one over TOTP and main.py
authenticates with THAT. So the check reported an expiry eleven minutes
away for a credential nothing was using, and told the operator to run

    py tools/dhan_token.py

which has never existed in this repository. BACKLOG.md already records
it as missing and dashboard/server.py calls naming a nonexistent tool
"the third time on this project" -- tools/dhan_login.py in
tools/morning.py was the same fault the day before.

A preflight that checks a different credential from the one the session
will authenticate with is worse than no preflight: it reports
confidently about the wrong thing.

Author : H&M Opportunity Trader
==========================================================
"""

import base64
import json
import pathlib
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _jwt(hours_left):
    """A token shaped like Dhan's -- three parts, exp in the middle."""
    body = {"exp": int(time.time() + hours_left * 3600)}
    raw = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    return f"head.{raw.rstrip('=')}.sig"


def test_it_reads_the_token_the_bot_minted_not_the_env_one(monkeypatch):
    """THE REGRESSION. Two tokens exist; the check must read the live
    one."""
    import tools.dry_run_live_path as dr
    from core import dhan_auth

    monkeypatch.setattr(dhan_auth, "access_token", lambda *a, **k: _jwt(24))
    monkeypatch.setattr(dhan_auth, "source", lambda: "totp")
    # The .env token is nearly dead. If the check reads THIS, it fails.
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", _jwt(0.2))

    ok, message = dr._token()
    assert ok is True, message
    assert "24" in message or "past the next close" in message, message


def test_it_never_names_a_tool_that_does_not_exist():
    """py tools/dhan_token.py has never been in this repository."""
    src = (ROOT / "tools" / "dry_run_live_path.py").read_text(
        encoding="utf-8", errors="replace")
    printed = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("#"))
    assert "tools/dhan_token.py" not in printed, (
        "the preflight tells him to run tools/dhan_token.py, which does "
        "not exist. BACKLOG.md already records this one as missing.")


@pytest.mark.parametrize("tool", ["dhan_token.py", "dhan_login.py"])
def test_the_named_tools_are_real(tool):
    """The general rule behind both faults: if a message tells him to
    run something, it has to be there. Twice in two days it was not."""
    src = (ROOT / "tools" / "dry_run_live_path.py").read_text(
        encoding="utf-8", errors="replace")
    printed = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("#"))
    if f"tools/{tool}" in printed:
        assert (ROOT / "tools" / tool).exists(), (
            f"the preflight names tools/{tool} and it is not there")


def test_a_totp_token_is_not_reported_as_a_morning_chore(monkeypatch):
    """With TOTP configured there IS no morning job. Telling him to
    generate one makes a working system read as broken."""
    import tools.dry_run_live_path as dr
    from core import dhan_auth

    monkeypatch.setattr(dhan_auth, "access_token", lambda *a, **k: _jwt(3))
    monkeypatch.setattr(dhan_auth, "source", lambda: "totp")
    _, message = dr._token()
    assert "re-mints this itself" in message, message
    assert "Generate" not in message, message


def test_an_env_token_still_says_what_to_do(monkeypatch):
    """The other side: without TOTP a human really does have to act,
    and the message must say so."""
    import tools.dry_run_live_path as dr
    from core import dhan_auth

    monkeypatch.setattr(dhan_auth, "access_token", lambda *a, **k: _jwt(3))
    monkeypatch.setattr(dhan_auth, "source", lambda: "env")
    _, message = dr._token()
    assert "DHAN_TOTP_SECRET" in message, message


def test_no_token_anywhere_fails_the_stage(monkeypatch):
    """config.DHAN_ACCESS_TOKEN is read at IMPORT, so setting the
    environment variable here changes nothing -- the constant is
    already bound. Patch the constant."""
    import config
    import tools.dry_run_live_path as dr
    from core import dhan_auth

    monkeypatch.setattr(dhan_auth, "access_token", lambda *a, **k: "")
    monkeypatch.setattr(dhan_auth, "source", lambda: None)
    monkeypatch.setattr(config, "DHAN_ACCESS_TOKEN", "")
    ok, message = dr._token()
    assert ok is False
    assert "cannot start" in message
