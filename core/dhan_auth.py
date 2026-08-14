"""
==========================================================
The bot mints its own Dhan token
==========================================================

    "dhan provides us Access Token & API Key toggle. we are using
     Access Token manually generating tokens , why cant we use API Key?"
                                -- operator, 11 August 2026

WHY NOT THE API KEY
-------------------
It looks like the automatic one and it is not. DhanHQ's own
documentation, step 2 of the API-key flow:

    "This endpoint needs to be opened directly on a browser. On this
     step, the user needs to enter their Dhan credentials, validate
     with 2FA like OTP/pin/password."

The KEY lasts 12 months. The TOKEN it produces still lasts 24 hours
and still needs him in front of a browser to get it. That is the same
manual morning he has now, wearing a different hat, plus a redirect
URL to host. Not a trade worth making.

WHAT THIS DOES INSTEAD
----------------------
The third door in the same document, and the only one with no browser
in it:

    POST https://auth.dhan.co/app/generateAccessToken
         ?dhanClientId=...&pin=...&totp=......

TOTP is set up once on Dhan Web (Profile -> DhanHQ Trading APIs ->
Setup TOTP). After that the six-digit code is not something he reads
off a phone -- it is computed from a shared secret and the clock, by
RFC 6238, which the bot can do as well as the phone can. So the bot
asks Dhan for a fresh 24-hour token at startup and he is out of the
loop entirely.

WHAT IT WILL NOT DO
-------------------
Stop the morning. If the secret is absent, wrong, expired, or if
auth.dhan.co is unreachable, this returns the DHAN_ACCESS_TOKEN
already in .env and says why in one line. A broken convenience must
never become a broken session -- that is the whole reason the fallback
is here rather than an exception.

It also holds no secrets of its own. DHAN_PIN and DHAN_TOTP_SECRET are
read from the environment at the moment of use, never written to disk,
never logged, and never printed -- `describe()` prints lengths, not
values.

WHY NO pyotp
------------
TOTP is HMAC-SHA1 over a counter, truncated. Twenty lines of stdlib.
A dependency on the auth path is a dependency that can fail to install
on the morning it matters.

Author : H&M Opportunity Trader
==========================================================
"""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Dhan's own endpoint, from the v2 authentication document.
MINT_URL = "https://auth.dhan.co/app/generateAccessToken"

# RFC 6238 defaults, and what Dhan's authenticator QR issues.
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6

# Give up rather than hang the startup. A token we do not have in ten
# seconds is a token we fall back from.
TIMEOUT_SECONDS = 10.0

# Re-mint only when the held token is nearly out. Dhan issues 24 hours.
REMINT_WHEN_UNDER_HOURS = 2.0

_held = {"token": None, "expires": None, "source": None, "why": None,
         "clock_note": None}

# ==========================================================
# THE CACHE HAS TO SURVIVE A RESTART.  13 August 2026.
# ==========================================================
#
#     "TOTP mint failed (Dhan refused the request: 'Token can be
#      generated once every 2 minutes.')"
#
# _held above is process memory. Dhan issues a token that lasts 24
# HOURS, and every `py main.py` threw it away and asked for another --
# so restarting twice inside two minutes broke authentication, and the
# bot fell back to whatever static token was in .env.
#
# Restarting twice in two minutes is not an unusual thing to do. It is
# what anybody does when the first start looked wrong.
#
# So the minted token is written here with its expiry and read back on
# the next start. A 24-hour token is minted about once a day instead of
# once a process.
#
# NOT IN .env, and never printed. The file holds a live credential:
# anyone with it can trade the account until it expires. data/ is
# already gitignored for the same reason the Telegram session lives
# there.
TOKEN_CACHE = os.path.join("data", "dhan_token.json")


def _read_cache():
    """The last minted token, if it is still good. None otherwise.

    Never raises: an unreadable cache means "mint one", which is the
    behaviour this whole file had before the cache existed.
    """
    try:
        with open(TOKEN_CACHE, encoding="utf-8") as handle:
            held = json.load(handle)
    except Exception:                                       # noqa: BLE001
        return None
    token = str(held.get("token") or "")
    if not token:
        return None
    expires = None
    stamp = held.get("expires")
    if stamp:
        try:
            expires = datetime.fromisoformat(str(stamp))
        except ValueError:
            expires = None
    # No expiry recorded is treated as EXPIRED rather than eternal. A
    # token we cannot date is one we must not keep using -- the whole
    # failure this fixes came from trusting a stale credential.
    if expires is None:
        return None
    if expires - datetime.now() <= timedelta(hours=REMINT_WHEN_UNDER_HOURS):
        return None
    return {"token": token, "expires": expires,
            "why": held.get("why") or
            f"minted earlier, good until {expires.strftime('%d %b %H:%M')}"}


def _write_cache(token, expires, why=None):
    """Best effort. A cache that cannot be written costs a re-mint on
    the next start, never a session."""
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE) or ".", exist_ok=True)
        with open(TOKEN_CACHE, "w", encoding="utf-8") as handle:
            json.dump({"token": token,
                       "expires": expires.isoformat() if expires else None,
                       "why": why,
                       "written_at": datetime.now().isoformat()}, handle)
    except Exception:                                       # noqa: BLE001
        pass


# ----------------------------------------------------------
# RFC 6238
# ----------------------------------------------------------

def _b32(secret):
    """Authenticator secrets arrive spaced, lower-cased and unpadded --
    and sometimes as the whole otpauth:// URI behind the QR code, which
    is what you get if you copy the QR rather than the text beside it.

    All four shapes decode to the same key here, because "I pasted what
    was on the screen" must not be the reason a login fails.
    """
    raw = str(secret or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("otpauth://"):
        try:
            query = urllib.parse.urlparse(raw).query
            raw = urllib.parse.parse_qs(query).get("secret", [""])[0]
        except Exception:                                      # noqa: BLE001
            return None
    raw = raw.replace(" ", "").replace("-", "").replace("\t", "").upper()
    if not raw:
        return None
    raw += "=" * (-len(raw) % 8)
    try:
        return base64.b32decode(raw, casefold=True)
    except Exception:                                          # noqa: BLE001
        return None


def totp_now(secret, at=None):
    """The six digits the authenticator app would be showing.

    Returns None rather than raising -- a malformed secret is a reason
    to fall back, not a reason to stop.
    """
    key = _b32(secret)
    if not key:
        return None
    counter = int((at if at is not None else time.time()) // TOTP_STEP_SECONDS)
    try:
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        chunk = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(chunk % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)
    except Exception:                                          # noqa: BLE001
        return None


def codes_around(secret, windows=4, at=None):
    """The codes for the windows either side of now.

    THE POINT. When the bot's code does not match the phone, there are
    only two possible faults and they look identical from the outside:

        wrong secret  -- no window will ever match
        wrong clock   -- the phone's code is sitting in one of these

    So print them. If his authenticator is showing the -2 row, the
    secret is perfect and the machine clock is 60 seconds slow, and
    that is a completely different repair from re-copying the secret.
    """
    now = at if at is not None else time.time()
    out = []
    for step in range(-windows, windows + 1):
        moment = now + step * TOTP_STEP_SECONDS
        out.append({
            "step": step,
            "offset_seconds": step * TOTP_STEP_SECONDS,
            "code": totp_now(secret, at=moment),
            "is_now": step == 0,
        })
    return out


def clock_skew():
    """How far this machine's clock is from Dhan's own server, in
    seconds. Positive means this PC is AHEAD.

    Read off the Date header of an ordinary HTTPS response, which every
    server sends and which needs no authentication. Dhan's clock is the
    one that matters here -- not the phone's, not NTP's -- because
    Dhan's clock is what validates the code.
    """
    try:
        request = urllib.request.Request(
            "https://api.dhan.co/v2/profile", method="GET")
        try:
            with urllib.request.urlopen(request,
                                        timeout=TIMEOUT_SECONDS) as response:
                served = response.headers.get("Date")
        except urllib.error.HTTPError as refused:
            # 401 is expected and perfectly useful -- it still carries
            # the header we came for.
            served = refused.headers.get("Date")
        if not served:
            return {"skew": None, "why": "no Date header came back"}
        theirs = parsedate_to_datetime(served)
        mine = datetime.now(timezone.utc)
        skew = (mine - theirs).total_seconds()
        return {"skew": round(skew, 1), "server_utc": theirs, "why": None}
    except Exception as problem:                               # noqa: BLE001
        return {"skew": None, "why": f"could not reach api.dhan.co ({problem})"}


def seconds_left_on_code(at=None):
    """How long the current code lives. Used to avoid minting on the
    knife-edge of a rollover, which is the classic intermittent
    'invalid TOTP' that looks like a credentials fault and is not."""
    now = at if at is not None else time.time()
    return TOTP_STEP_SECONDS - (now % TOTP_STEP_SECONDS)


# ----------------------------------------------------------
# The call
# ----------------------------------------------------------

def _post(url):
    request = urllib.request.Request(url, data=b"", method="POST")
    request.add_header("Accept", "application/json")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def mint(client_id=None, pin=None, secret=None):
    """Ask Dhan for a fresh 24-hour access token.

    Returns {"token", "expires", "why"} on success, or {"token": None,
    "why": <plain sentence>} on any failure. Never raises.
    """
    client_id = client_id or os.getenv("DHAN_CLIENT_ID", "")
    pin = pin if pin is not None else os.getenv("DHAN_PIN", "")
    secret = secret if secret is not None else os.getenv("DHAN_TOTP_SECRET", "")

    if not str(client_id).strip():
        return {"token": None, "why": "DHAN_CLIENT_ID is not set"}
    if not str(pin).strip():
        return {"token": None, "why": "DHAN_PIN is not set in .env"}
    if not str(secret).strip():
        return {"token": None, "why": "DHAN_TOTP_SECRET is not set in .env"}

    # Do not mint against a code that is about to roll over.
    if seconds_left_on_code() < 2.0:
        time.sleep(2.5)

    code = totp_now(secret)
    if not code:
        return {"token": None,
                "why": ("DHAN_TOTP_SECRET is not a valid base32 secret -- "
                        "copy the code shown beside the QR on Dhan Web")}

    def _try(with_code):
        url = MINT_URL + "?" + urllib.parse.urlencode({
            "dhanClientId": str(client_id).strip(),
            "pin": str(pin).strip(),
            "totp": with_code,
        })
        try:
            return _post(url), None
        except Exception as problem:                           # noqa: BLE001
            return None, f"could not reach auth.dhan.co ({problem})"

    body, unreachable = _try(code)
    if unreachable:
        return {"token": None, "why": unreachable}

    token = (body or {}).get("accessToken")

    # ---- ONE RETRY, ON DHAN'S CLOCK RATHER THAN THIS PC'S ----
    # A Windows clock drifting a minute is enough to make a perfectly
    # good secret produce a rejected code, every single time, with an
    # error that reads like bad credentials. If the first attempt was
    # refused and this machine disagrees with Dhan's own clock by more
    # than half a window, try again on THEIR time before giving up.
    if not token:
        drift = clock_skew().get("skew")
        if drift is not None and abs(drift) >= TOTP_STEP_SECONDS / 2:
            theirs = totp_now(secret, at=time.time() - drift)
            if theirs and theirs != code:
                body, unreachable = _try(theirs)
                if not unreachable:
                    token = (body or {}).get("accessToken")
                if token:
                    _held["clock_note"] = (
                        f"this PC's clock is {drift:+.0f}s off Dhan's -- "
                        f"the token was minted on their time. Fix the "
                        f"Windows clock so this is not needed.")

    if not token:
        return {"token": None,
                "why": f"Dhan refused the request: {str(body)[:200]}"}

    expires = None
    stamp = (body or {}).get("expiryTime")
    if stamp:
        for shape in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                expires = datetime.strptime(str(stamp), shape)
                break
            except ValueError:
                continue
    if expires is None:
        expires = datetime.now() + timedelta(hours=24)

    return {"token": token, "expires": expires,
            "why": (f"minted by the bot, good until "
                    f"{expires.strftime('%d %b %H:%M')}")}


# ----------------------------------------------------------
# What the rest of the bot calls
# ----------------------------------------------------------

def access_token(force=False):
    """The token to authenticate with. TOTP-minted if it can be, the
    one from .env if it cannot. Always a string, possibly empty."""
    fallback = os.getenv("DHAN_ACCESS_TOKEN", "") or ""

    if not force and _held["token"]:
        expires = _held["expires"]
        if expires is None or expires - datetime.now() > timedelta(
                hours=REMINT_WHEN_UNDER_HOURS):
            return _held["token"]

    # The token this or an earlier PROCESS minted, if it is still good.
    # See TOKEN_CACHE -- Dhan issues 24 hours and rate-limits minting to
    # one every two minutes, so a restart must reuse rather than re-ask.
    if not force:
        cached = _read_cache()
        if cached:
            _held.update({"token": cached["token"],
                          "expires": cached["expires"],
                          "source": "totp", "why": cached["why"]})
            return cached["token"]

    if not str(os.getenv("DHAN_TOTP_SECRET", "")).strip():
        _held.update({"token": fallback, "expires": None, "source": "env",
                      "why": "TOTP is not set up -- using DHAN_ACCESS_TOKEN"})
        return fallback

    got = mint()
    if got.get("token"):
        _held.update({"token": got["token"], "expires": got.get("expires"),
                      "source": "totp", "why": got.get("why")})
        # So the next process does not have to ask Dhan again.
        _write_cache(got["token"], got.get("expires"), got.get("why"))
        return got["token"]

    _held.update({"token": fallback, "expires": None, "source": "env",
                  "why": (f"TOTP mint failed ({got.get('why')}) -- "
                          f"falling back to DHAN_ACCESS_TOKEN")})
    return fallback


def source():
    """"totp" or "env" -- which door the current token came through."""
    return _held.get("source")


def describe():
    """One line for the startup banner. Prints no secret, ever."""
    token = _held.get("token") or ""
    if not token:
        return "[AUTH] no Dhan token at all -- neither TOTP nor .env"
    where = "minted by the bot (TOTP)" if _held.get(
        "source") == "totp" else "from .env"
    return (f"[AUTH] Dhan token {where}, {len(token)} chars. "
            f"{_held.get('why') or ''}".rstrip())


def reset():
    _held.update({"token": None, "expires": None, "source": None,
                  "why": None})
