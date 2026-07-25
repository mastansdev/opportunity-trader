"""
==========================================================
Dashboard Access Token
==========================================================

Operator-approved 2026-07-23: the dashboard link needs to be
shareable with someone on a different network entirely (a
tunnel like ngrok, or similar), but that other person must be
able to WATCH only -- never click BUY/SELL/EXIT ALL.

Why not just check the request's IP address? It doesn't hold up
once a tunnel is involved: tools like ngrok run a local agent
that connects to this server over 127.0.0.1 itself, so EVERY
visitor -- including a stranger on the other side of the tunnel
-- would appear to originate from localhost. An IP check would
silently stop protecting anything the moment a tunnel is added,
which is exactly the moment it matters most.

Instead: a single random secret, generated once and reused
(not regenerated every restart -- the operator needs a stable
link to bookmark), read by dashboard/server.py:
  - GET / with the CORRECT ?token=... query param gets the page
    with the token embedded in it -- from then on on that page,
    the BUY/SELL/EXIT ALL buttons work.
  - GET / with no token, or the wrong one, gets the exact same
    live page, buttons just quietly do nothing -- no token was
    ever sent to that browser to prove authority with.
  - Every POST /api/... write endpoint independently re-checks
    the token header itself -- the page-level gate above is only
    what decides whether the token gets HANDED to the browser,
    it is never itself the enforcement.

This is transport-agnostic on purpose: works identically whether
the "share" link is on the same WiFi, through ngrok, through
Tailscale, or anything else -- because it never depends on
figuring out who's "really" local.

Stored in data/dashboard_token.txt (gitignored, same folder as
every other runtime file this bot writes, e.g. session_state.json).

Author : H&M Opportunity Trader
==========================================================
"""

import os
import secrets

TOKEN_PATH = os.path.join("data", "dashboard_token.txt")


def get_or_create_token(path=TOKEN_PATH):
    """
    Returns the existing token if one's already on disk, else
    generates a fresh one and saves it. Stable across restarts on
    purpose -- an operator control link that changes every time
    the bot restarts isn't a link worth bookmarking.
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing

    token = secrets.token_urlsafe(24)

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(token)

    return token
