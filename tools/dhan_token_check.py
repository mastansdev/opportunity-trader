"""
==========================================================
Does the bot's own token work? Ask before 09:00, not at it
==========================================================

    py tools/dhan_token_check.py

Prints which door the token came through, whether it is accepted by
Dhan, and how long it lasts -- without starting the bot and without
printing a single secret.

Run it once after setting up TOTP. Run it again any morning you want
to be sure before the open.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DHAN_CLIENT_ID                          # noqa: E402
from core import dhan_auth                                 # noqa: E402

PROFILE_URL = "https://api.dhan.co/v2/profile"


def _line(label, value):
    print(f"  {label:<26}{value}")


def _profile(token):
    """The document's own suggested first call. Confirms the token is
    live rather than merely well-formed."""
    request = urllib.request.Request(PROFILE_URL)
    request.add_header("access-token", token)
    request.add_header("Accept", "application/json")
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _diagnose(secret):
    """The code does not match the phone. There are exactly two reasons
    and they look the same from the outside, so separate them here.

    A wrong SECRET can never match, at any moment in history.
    A wrong CLOCK matches perfectly -- just at the wrong minute.

    So print the neighbouring windows. If the phone's code appears in
    this table at all, the secret is correct and the machine clock is
    wrong by exactly the offset shown. That is a Windows setting, not a
    re-copy.
    """
    print("  IS IT THE SECRET, OR IS IT THE CLOCK?")
    print("  " + "-" * 58)

    key_ok = dhan_auth._b32(secret) is not None
    if not key_ok:
        print("  The secret is not readable as base32 at all, so no code")
        print("  it produces could ever match.")
        print()
        print("  On Dhan Web, beside the QR there is a line of letters and")
        print("  numbers -- that is what goes in DHAN_TOTP_SECRET. Not the")
        print("  6-digit code, and not a screenshot of the QR.")
        print("  (If you copied the whole otpauth://... link, that is fine")
        print("   too -- paste it as is, this now reads it.)")
        print()
        return

    print(f"  secret decodes                {len(dhan_auth._b32(secret))} bytes -- readable")
    print()
    print("  Look at your authenticator app RIGHT NOW and find its")
    print("  6 digits in this table:")
    print()
    print(f"    {'WHEN':<22}{'CODE':<10}")
    for row in dhan_auth.codes_around(secret, windows=4):
        when = ("NOW" if row["is_now"]
                else f"{row['offset_seconds']:+d} seconds")
        mark = "   <-- what the bot sends" if row["is_now"] else ""
        print(f"    {when:<22}{row['code']:<10}{mark}")
    print()
    print(f"  this code rolls in {dhan_auth.seconds_left_on_code():.0f}s")
    print()

    skew = dhan_auth.clock_skew()
    if skew.get("skew") is None:
        print(f"  clock vs Dhan: could not check ({skew.get('why')})")
    else:
        drift = skew["skew"]
        _line("this PC vs Dhan's clock", f"{drift:+.1f} seconds")
        if abs(drift) < 5:
            print("     the clock is fine. If the code still does not match,")
            print("     the secret belongs to a different account entry --")
            print("     check WHICH entry in your authenticator you are")
            print("     reading, or set up TOTP again and re-copy.")
        else:
            print(f"     THIS IS THE FAULT. The clock is {abs(drift):.0f} seconds")
            print("     out, so every code it computes is for the wrong")
            print("     moment. Fix it on Windows:")
            print("       Settings > Time & language > Date & time")
            print("       -> Sync now, and turn ON 'Set time automatically'")
            print("     The bot will work around it in the meantime, but")
            print("     a wrong clock also skews every candle timestamp.")
    print()


def main():
    print()
    print("  DHAN TOKEN -- where it comes from and whether it works")
    print("  " + "=" * 58)
    print()

    have_secret = bool(str(os.getenv("DHAN_TOTP_SECRET", "")).strip())
    have_pin = bool(str(os.getenv("DHAN_PIN", "")).strip())
    have_env_token = bool(str(os.getenv("DHAN_ACCESS_TOKEN", "")).strip())

    _line("client id", (str(DHAN_CLIENT_ID)[:4] + "..." if DHAN_CLIENT_ID
                        else "MISSING"))
    _line("DHAN_TOTP_SECRET", "set" if have_secret else "not set")
    _line("DHAN_PIN", "set" if have_pin else "not set")
    _line("DHAN_ACCESS_TOKEN", "set" if have_env_token else "not set")
    print()

    if have_secret:
        _diagnose(os.getenv("DHAN_TOTP_SECRET"))

    # ---- A CHECK MUST NOT BURN A MINT. 13 August 2026. ----
    #
    #     "TOTP mint failed (Dhan refused the request: 'Token can be
    #      generated once every 2 minutes.')"
    #     "but i started just now on morning"     -- operator
    #
    # He had. Once. This tool was added to tools/morning.py's `token`
    # step on 12 August, described as "the CHECK, not removed" -- and
    # it called access_token(force=True), which SKIPS the cache and
    # asks Dhan for a brand new token every time.
    #
    # So the morning ran: morning.py minted at 08:30, main.py started a
    # minute later and minted again, and Dhan refused the second. The
    # bot fell back to the .env token and said so. One start, two
    # mints, because the "check" was really a second login.
    #
    # force=True is still available behind --force, because deliberately
    # re-minting IS sometimes what you want (a rejected token, a changed
    # pin). It is no longer what happens by default.
    force = "--force" in sys.argv
    token = dhan_auth.access_token(force=force)
    print("  " + dhan_auth.describe())
    if not force:
        print("  (checked the held token -- pass --force to mint a new "
              "one; Dhan allows one every 2 minutes)")
    print()

    if not token:
        print("  No token at all. The bot would refuse to start.")
        return 1

    try:
        body = _profile(token)
    except Exception as problem:                           # noqa: BLE001
        print(f"  Dhan would not accept it: {problem}")
        if dhan_auth.source() == "totp":
            print("  The minted token was rejected -- check the pin.")
        return 1

    _line("accepted by Dhan", "YES")
    _line("token valid until", body.get("tokenValidity", "-"))
    _line("segments", body.get("activeSegment", "-"))
    _line("MTF", body.get("mtf", "-"))
    _line("data plan", body.get("dataPlan", "-"))
    _line("data valid until", body.get("dataValidity", "-"))
    print()

    if dhan_auth.source() == "totp":
        print("  The bot minted this itself. Nothing for you to do in the")
        print("  morning.")
    else:
        print("  This came from .env, so it still expires 24 hours after")
        print("  you generated it. Set DHAN_PIN and DHAN_TOTP_SECRET to")
        print("  hand that job to the bot -- see .env.example.")
    print()
    print(f"  checked {datetime.now().strftime('%d %b %Y %H:%M:%S')}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
