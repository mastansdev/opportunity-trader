"""
==========================================================
Why is Dhan saying "Invalid IP"?
==========================================================
    py tools/dhan_ip_check.py

READ ONLY by default. Places nothing, changes nothing.

WHY THIS EXISTS
---------------
31 July 2026, first live session. Three orders, three rejections:

    BUY AARTIIND  REJECTED  DH-905  Invalid IP
    BUY SATIN     REJECTED  DH-905  Invalid IP
    BUY SPORTKING REJECTED  DH-905  Invalid IP

Everything else worked all morning -- funds, positions, quotes, the
tick feed. That asymmetry IS the diagnosis, and it is in Dhan's own
documentation:

    "Static IP is only required while using Order Placement APIs
     including Orders, Super Order, Forever Order. While fetching
     order details or trade details, no such IP whitelisting is
     required."

SEBI made static-IP whitelisting mandatory for order placement. Reads
are exempt. So a working funds call proves the token is fine and
proves nothing at all about whether an order can be sent.

Diagnosing this by clicking BUY costs a wasted order attempt each
time and tells you nothing new. This asks the question directly:

    - what IP does the internet see this machine as?
    - what IP has Dhan actually got on file?
    - do they match?

THE 7-DAY TRAP -- READ BEFORE SETTING ANYTHING
----------------------------------------------
From Dhan's docs:

    "Once an IP is setup, you cannot modify the same for the next
     7 days."

And, in the same section:

    "A static IP is a fixed, permanent internet address... Unlike the
     default IP you get on home Wi-Fi (which your ISP changes
     automatically from time to time), a static IP never changes. To
     use one, you need to request and purchase it separately from
     your Internet Service Provider."

Setting a DYNAMIC home or mobile IP here is a trap with a one-week
sentence. It works this afternoon, the ISP rotates you overnight, and
order placement is dead until the modify window reopens. This tool
therefore refuses to set anything unless asked twice, in writing.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import sys
import urllib.request

sys.path.insert(0, ".")

from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN     # noqa: E402
from core.logger import decision, warn                   # noqa: E402

GET_IP = "https://api.dhan.co/v2/ip/getIP"
SET_IP = "https://api.dhan.co/v2/ip/setIP"
PROFILE = "https://api.dhan.co/v2/profile"

# Several, because one being down must not read as "no IP".
WHOAMI = ("https://api.ipify.org",
          "https://ifconfig.me/ip",
          "https://icanhazip.com")


def _line():
    decision("-" * 68)


def _call(url, method="GET", body=None):
    request = urllib.request.Request(url, method=method)
    request.add_header("access-token", DHAN_ACCESS_TOKEN)
    request.add_header("Accept", "application/json")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request.add_header("Content-Type", "application/json")
        request.data = data
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode() or "{}")


def my_ip():
    """This machine's OUTBOUND IPv4 -- the one Dhan sees.

    Asked of more than one service on purpose. If two disagree, the
    connection is going out through something that rewrites it (a VPN,
    a proxy, or carrier NAT), and that is worth knowing BEFORE burning
    the 7-day whitelist slot on a number that is not really yours.
    """
    seen = {}
    for url in WHOAMI:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                seen[url] = response.read().decode().strip()
        except Exception as exc:                          # noqa: BLE001
            seen[url] = f"(unreachable: {exc})"
    return seen


def _warn_if_token_dies_today(validity):
    """Will this token survive the whole session?

    Dhan's format is "01/08/2026 09:24" (DD/MM/YYYY HH:MM). Anything
    expiring before 15:30 today means the bot goes deaf to the broker
    part-way through -- so say it now, loudly, with the hour it will
    happen.
    """
    from datetime import datetime

    if not validity:
        warn("    Token validity unknown -- regenerate before the open "
             "rather than find out mid-session.")
        return
    try:
        dies = datetime.strptime(str(validity).strip(), "%d/%m/%Y %H:%M")
    except ValueError:
        warn(f"    Could not read the expiry ({validity}).")
        return

    now = datetime.now()
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if dies <= now:
        warn("    THE TOKEN HAS ALREADY EXPIRED. Regenerate it now.")
    elif dies < close:
        warn(f"    THIS TOKEN DIES AT {dies:%H:%M} TODAY -- before the "
             f"15:30 close. Every broker call fails from that minute on, "
             f"and it will look like an outage, not an expiry. "
             f"Regenerate BEFORE starting the session.")
    else:
        hours = (dies - now).total_seconds() / 3600.0
        decision(f"    survives today  yes -- {hours:.1f}h left "
                 f"(dies {dies:%d %b %H:%M})")


def route_to_dhan():
    """WHICH address actually carries an order to Dhan.

    This is the question. "What is my IP" sites answer whichever
    protocol THEY happen to support, and on 31 July 2026 they
    disagreed:

        api.ipify.org     157.50.96.168                    (IPv4)
        ifconfig.me       2409:40f0:30a7:be33:...:f8c0     (IPv6)

    Both were true. The machine has both, and Jio is IPv6-first.
    Python's urllib, like every other client, takes whatever
    getaddrinfo hands back first -- so if api.dhan.co answers on IPv6,
    the order leaves over IPv6 and Dhan sees the v6 address, no matter
    which v4 address was whitelisted.

    Whitelisting the wrong family looks identical to not whitelisting
    at all: DH-905, every time, with a correctly configured account.

    So open a real socket to the real host and read the addresses off
    it. No guessing.
    """
    import socket

    try:
        infos = socket.getaddrinfo("api.dhan.co", 443,
                                   proto=socket.IPPROTO_TCP)
    except Exception as exc:                              # noqa: BLE001
        return {"error": str(exc)}

    families = []
    for family, _, _, _, address in infos:
        families.append(("IPv6" if family == socket.AF_INET6 else "IPv4",
                         address[0]))

    chosen = local = None
    for family, _, _, _, address in infos:
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(8)
            sock.connect(address[:2] if family == socket.AF_INET else address)
            local = sock.getsockname()[0]
            chosen = ("IPv6" if family == socket.AF_INET6 else "IPv4",
                      address[0])
            sock.close()
            break
        except Exception:                                 # noqa: BLE001
            continue
    return {"resolves_to": families, "used": chosen, "local": local}


def main(set_primary=False, confirmed=False):
    if not DHAN_ACCESS_TOKEN:
        warn("DHAN_ACCESS_TOKEN missing from .env.")
        return

    decision("=" * 68)
    decision("  DHAN IP CHECK -- why order placement is being refused")
    decision("=" * 68)

    # ---- 1. is the token even alive? ---------------------------------
    # /profile is a read, so it works with or without a whitelisted IP.
    # That is exactly why it is a clean way to separate the two
    # failures: token dead vs IP not whitelisted.
    _line()
    decision("  TOKEN  (a read -- works even when orders are blocked)")
    try:
        profile = _call(PROFILE)
        decision(f"    client id      {profile.get('dhanClientId')}")
        decision(f"    token valid to {profile.get('tokenValidity')}")
        decision(f"    MTF            {profile.get('mtf')}")
        decision(f"    DDPI           {profile.get('ddpi')}")
        decision(f"    data plan      {profile.get('dataPlan')} "
                 f"(to {profile.get('dataValidity')})")
        decision(f"    segments       {profile.get('activeSegment')}")

        # THE TRAP THAT HAS NOT SPRUNG YET.
        #
        # Dhan tokens last 24 HOURS from generation. On 31 July 2026 the
        # operator regenerated at 09:24, so the token dies at 09:24 the
        # NEXT day -- nine minutes into a session started at 09:15.
        #
        # A token that expires mid-session does not announce itself. The
        # feed keeps running on its own socket while every REST call
        # starts failing, so it reads as a broker outage rather than as
        # an expiry. Finding out at 08:45 costs two minutes.
        _warn_if_token_dies_today(profile.get("tokenValidity"))
    except Exception as exc:                              # noqa: BLE001
        warn(f"    /profile failed: {exc}")
        warn("    The TOKEN is the problem, not the IP. Regenerate it.")
        return

    # ---- 2. what does the world see us as? ---------------------------
    _line()
    decision("  THIS MACHINE'S OUTBOUND IP")
    seen = my_ip()
    values = set()
    for url, value in seen.items():
        decision(f"    {url:34} {value}")
        if not value.startswith("("):
            values.add(value)
    if len(values) > 1:
        # MY OWN WRONG MESSAGE, 31 July 2026. This used to say
        # "Something is rewriting the outbound address -- a VPN, a
        # proxy, or carrier NAT", which sent the operator looking for
        # a VPN he did not have.
        #
        # Nothing is rewriting anything. The machine simply has BOTH an
        # IPv4 and an IPv6 address, and those sites answer on whichever
        # protocol they support. Both numbers are true. The only
        # question that matters is which one carries a connection to
        # api.dhan.co, and that is the section directly below -- which
        # is why this is now a note and not an alarm.
        decision("    Two different numbers, both correct: this machine "
                 "has an IPv4 AND an IPv6 address, and each site "
                 "answered on the protocol it supports. Not a VPN. What "
                 "matters is which one reaches Dhan -- see below.")
    mine = next(iter(values)) if len(values) == 1 else None

    # ---- 2b. which family actually carries the order -----------------
    _line()
    decision("  HOW THIS MACHINE ACTUALLY REACHES api.dhan.co")
    route = route_to_dhan()
    if route.get("error"):
        warn(f"    could not resolve api.dhan.co: {route['error']}")
    else:
        for family, address in route.get("resolves_to") or []:
            decision(f"    resolves       {family:5} {address}")
        used = route.get("used")
        if used:
            decision(f"    CONNECTED OVER {used[0]}  -> {used[1]}")
            decision(f"    local address  {route.get('local')}")
            decision("")
            decision("    THIS is the address family Dhan sees your orders")
            decision("    arrive on. Whitelisting the other family has no")
            decision("    effect whatsoever and looks exactly like not")
            decision("    whitelisting anything.")
            if used[0] == "IPv6":
                mine = route.get("local") or mine
                warn("    Your orders leave over IPv6. If you whitelisted "
                     "an IPv4 address, that is the entire problem.")

    # ---- 3. what has Dhan actually got? ------------------------------
    _line()
    decision("  WHAT DHAN HAS ON FILE")
    try:
        book = _call(GET_IP)
    except Exception as exc:                              # noqa: BLE001
        warn(f"    /ip/getIP failed: {exc}")
        return

    # THE DOCS SHOW A DICT. THE LIVE API RETURNED A LIST.
    #
    # 31 July 2026: this crashed with
    #     AttributeError: 'list' object has no attribute 'get'
    # against an account with no IP set. Documented shapes and shipped
    # shapes drift, and a diagnostic tool that dies on the empty case
    # is useless precisely when it is needed -- "no IP set" is the
    # single most likely thing it will ever have to report.
    #
    # So: accept either, and print the raw payload regardless. When a
    # tool disagrees with the documentation, the raw bytes are the only
    # thing worth trusting.
    decision(f"    raw reply      {str(book)[:200]}")
    if isinstance(book, list):
        book = book[0] if (book and isinstance(book[0], dict)) else {}
    if not isinstance(book, dict):
        book = {}

    primary = book.get("primaryIP")
    secondary = book.get("secondaryIP")
    decision(f"    primary        {primary or 'NONE SET'}"
             + (f"   (editable from {book['modifyDatePrimary']})"
                if book.get("modifyDatePrimary") else ""))
    decision(f"    secondary      {secondary or 'NONE SET'}"
             + (f"   (editable from {book['modifyDateSecondary']})"
                if book.get("modifyDateSecondary") else ""))

    # ---- 4. the verdict ----------------------------------------------
    _line()
    on_file = {ip for ip in (primary, secondary) if ip}
    if not on_file:
        decision("  VERDICT: NO IP IS WHITELISTED AT ALL.")
        decision("")
        decision("  Dhan has nothing to match your orders against, so every")
        decision("  order placement is refused with DH-905. Reads are")
        decision("  unaffected, which is why the whole rest of the bot has")
        decision("  worked perfectly all morning.")
    elif mine and mine in on_file:
        decision("  VERDICT: YOUR IP MATCHES WHAT DHAN HAS.")
        decision("")
        decision("  If orders are still refused, the token was generated")
        decision("  BEFORE the IP was whitelisted -- regenerate it once.")
    elif mine:
        decision(f"  VERDICT: MISMATCH. You are on {mine}, Dhan expects "
                 f"{' or '.join(sorted(on_file))}.")
        decision("")
        decision("  This is what a dynamic IP looks like the morning after.")
    else:
        decision("  VERDICT: could not establish this machine's own IP, so")
        decision("  no comparison is possible. Fix that first.")

    # ---- 5. the warning that matters more than the fix ---------------
    _line()
    decision("  BEFORE YOU SET ANYTHING")
    decision("    Dhan: \"Once an IP is setup, you cannot modify the same")
    decision("    for the next 7 days.\"")
    decision("")
    decision("    A home broadband or mobile-data address is NOT static.")
    decision("    Whitelist one and it works until your ISP rotates you --")
    decision("    then order placement is dead until the window reopens.")
    decision("    Dhan's own documentation says a static IP has to be")
    decision("    bought from the ISP.")
    decision("")
    decision("    Two slots exist, primary and secondary. Spending one on")
    decision("    a rotating address costs a week if it moves.")

    if not set_primary:
        decision("")
        decision("  Nothing was changed. To set the primary IP:")
        decision("    py tools/dhan_ip_check.py --set-primary --i-understand"
                 "-this-locks-for-7-days")
        return

    if not confirmed:
        warn("  --set-primary given without the confirmation flag. "
             "Refusing. This is a 7-day decision.")
        return
    if not mine:
        warn("  Refusing to set an IP that could not be established.")
        return

    decision("")
    decision(f"  SETTING PRIMARY IP -> {mine}")
    try:
        result = _call(SET_IP, method="POST",
                       body={"dhanClientId": str(DHAN_CLIENT_ID),
                             "ip": mine, "ipFlag": "PRIMARY"})
        decision(f"    {result}")
        decision("    Now regenerate the access token -- Dhan's support "
                 "note says a token issued BEFORE the IP was added does "
                 "not carry the permission.")
    except Exception as exc:                              # noqa: BLE001
        warn(f"    setIP failed: {exc}")


if __name__ == "__main__":
    main(set_primary="--set-primary" in sys.argv,
         confirmed="--i-understand-this-locks-for-7-days" in sys.argv)
