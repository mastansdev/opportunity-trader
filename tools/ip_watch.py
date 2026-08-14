"""
==========================================================
Does this connection's address actually hold still?
==========================================================
    py tools/ip_watch.py            check once, append to the log
    py tools/ip_watch.py --report   what the log says so far
    py tools/ip_watch.py --watch    check every 10 minutes until Ctrl+C

Writes data/ip_history.csv. Reads nothing else, changes nothing.

WHY
---
31 July 2026. SEBI requires API orders to come from a whitelisted
static IP. Jio refused a static IPv4. The remaining free idea:

    netsh interface ipv6 set privacy state=disabled

That stops WINDOWS rotating the right-hand half of the IPv6 address.
It cannot stop JIO changing the left-hand half:

    2409:40f0:30a7:be33 : f4d1:b9b1:21ab:f8c0
    +-- prefix, Jio -+    +-- interface id, Windows --+

So the question is not "is the command correct" -- it is correct. The
question is whether Jio's prefix holds still for days at a time, and
nobody can answer that by reasoning. It has to be watched.

WHY IT MATTERS MORE THAN IT SOUNDS
----------------------------------
Dhan locks a whitelisted IP for SEVEN DAYS:

    "Once an IP is setup, you cannot modify the same for the next
     7 days."

Whitelist an address that turns out to drift and order placement is
dead for a week, on a live account, discovered at 09:20 on a Monday.
The cost of being wrong is a week; the cost of measuring first is a
weekend of a script appending one line every ten minutes.

WHAT COUNTS AS PROOF
--------------------
Not "it looked the same twice". The prefix must survive:

    - several days of ordinary use
    - a router reboot        (the most likely moment it changes)
    - a PC reboot            (proves the netsh setting persisted)

Until all three are in the log, this tool refuses to call it stable.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import socket
import sys
import time
import urllib.request
from datetime import datetime

LOG = os.path.join("data", "ip_history.csv")

# One IPv4-only service and one IPv6-capable one. Asking a single site
# is how 31 July went wrong: api.ipify.org answers only on v4 and
# ifconfig.me answered on v6, they disagreed, and the disagreement was
# misread as a VPN when it was simply two protocols.
V4_URL = "https://api.ipify.org"
V6_URL = "https://ifconfig.me/ip"


def _fetch(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode().strip()
    except Exception:                                      # noqa: BLE001
        return None


def local_v6_to_dhan():
    """The IPv6 address this machine would actually send an order FROM.

    Not "an" IPv6 address -- Windows can hold several at once, and the
    one in `ipconfig` is not necessarily the one used to reach a given
    host. Opening a real socket to api.dhan.co and reading the local
    end is the only answer that cannot be wrong.
    """
    try:
        infos = socket.getaddrinfo("api.dhan.co", 443, socket.AF_INET6,
                                   socket.SOCK_STREAM)
    except Exception:                                      # noqa: BLE001
        return None
    for family, _, _, _, address in infos:
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(8)
            sock.connect(address)
            local = sock.getsockname()[0]
            sock.close()
            return local
        except Exception:                                  # noqa: BLE001
            continue
    return None


def prefix_of(address):
    """The /64 -- the part Jio controls.

    This is the half that decides everything. The interface id can be
    pinned by disabling privacy extensions; the prefix cannot be pinned
    by anything on this machine.
    """
    if not address or ":" not in address:
        return None
    return ":".join(address.split(":")[:4]).lower()


def is_temporary_looking(address):
    """A rough flag for 'privacy extensions may still be on'.

    An EUI-64 interface id contains ff:fe in the middle. Anything else
    is either a temporary address (RFC 4941, rotates) or a stable
    opaque one (RFC 7217, does not). The two look alike, which is
    exactly why this is a hint printed for the operator and never a
    conclusion the tool acts on.
    """
    if not address or ":" not in address:
        return False
    groups = address.split(":")[4:]
    if len(groups) != 4:
        return False
    # ff:fe sits in the MIDDLE of an EUI-64 id, straddling two groups:
    #
    #     0212:34ff:fe56:7890
    #            ^^ ^^
    #
    # My first attempt checked the first two characters of each group
    # and so reported an EUI-64 address as temporary -- the ff is the
    # END of the third group. Padding to four hex digits and joining
    # removes the group boundaries entirely, which is the only way to
    # look at a value that sits across one.
    try:
        flat = "".join(f"{int(g or '0', 16):04x}" for g in groups)
    except ValueError:
        return False
    return flat[6:10] != "fffe"


def check(quiet=False):
    row = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ipv4": _fetch(V4_URL) or "",
        "ipv6_seen": _fetch(V6_URL) or "",
        "ipv6_to_dhan": local_v6_to_dhan() or "",
    }
    row["prefix"] = prefix_of(row["ipv6_to_dhan"] or row["ipv6_seen"]) or ""

    os.makedirs("data", exist_ok=True)
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)

    if not quiet:
        print(f"  {row['at']}")
        print(f"    IPv4            {row['ipv4'] or '(none)'}")
        print(f"    IPv6 to Dhan    {row['ipv6_to_dhan'] or '(none)'}")
        print(f"    prefix (Jio's)  {row['prefix'] or '(none)'}")
        if row["ipv6_to_dhan"] and is_temporary_looking(row["ipv6_to_dhan"]):
            print("    note: the interface id is not EUI-64. That is either")
            print("          a temporary address (rotates -- privacy")
            print("          extensions still on) or a stable opaque one.")
            print("          The log will tell you which within a day.")
    return row


def report():
    if not os.path.exists(LOG):
        print("  No history yet. Run it once with no arguments first.")
        return
    with open(LOG, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("  Log is empty.")
        return

    first, last = rows[0], rows[-1]
    prefixes = [r["prefix"] for r in rows if r["prefix"]]
    v6 = [r["ipv6_to_dhan"] for r in rows if r["ipv6_to_dhan"]]
    v4 = [r["ipv4"] for r in rows if r["ipv4"]]

    span_h = 0.0
    try:
        span_h = (datetime.strptime(last["at"], "%Y-%m-%d %H:%M:%S")
                  - datetime.strptime(first["at"], "%Y-%m-%d %H:%M:%S")
                  ).total_seconds() / 3600.0
    except ValueError:
        pass

    print("=" * 68)
    print(f"  IP STABILITY -- {len(rows)} checks over {span_h:.1f} hours")
    print("=" * 68)
    print(f"    first  {first['at']}")
    print(f"    latest {last['at']}")
    print()
    print(f"    distinct IPv4 addresses     {len(set(v4))}")
    print(f"    distinct IPv6 addresses     {len(set(v6))}")
    print(f"    distinct IPv6 PREFIXES      {len(set(prefixes))}   <- Jio's half")
    print()

    for label, values in (("IPv4", v4), ("IPv6", v6), ("prefix", prefixes)):
        if len(set(values)) > 1:
            print(f"    {label} CHANGED during the window:")
            seen = []
            for r in rows:
                key = {"IPv4": "ipv4", "IPv6": "ipv6_to_dhan",
                       "prefix": "prefix"}[label]
                value = r[key]
                if value and (not seen or seen[-1][1] != value):
                    seen.append((r["at"], value))
            for at, value in seen:
                print(f"        {at}   {value}")
            print()

    # THE VERDICT IS DELIBERATELY HARD TO EARN.
    #
    # "Same twice" is not stability, it is one observation repeated.
    # Dhan locks the slot for 7 days, so the bar is a couple of days
    # AND the reboots that are the likeliest moment for a change.
    print("-" * 68)
    if len(set(prefixes)) > 1:
        print("  VERDICT: NOT STABLE. Jio's prefix moved during the window.")
        print("  Whitelisting this address would fail the first time it")
        print("  moves again, and the slot is locked for 7 days after.")
    elif span_h < 48:
        print(f"  VERDICT: TOO EARLY. Only {span_h:.1f} hours watched.")
        print("  The prefix has not moved, which means nothing yet -- it")
        print("  has not been given a chance to. Keep the log running for")
        print("  at least 48 hours, and REBOOT THE ROUTER once inside that")
        print("  window. A router restart is the likeliest moment for the")
        print("  prefix to change, so an untested one proves little.")
    else:
        print(f"  VERDICT: HOLDING. One prefix across {span_h:.1f} hours.")
        print(f"      {prefixes[-1]}::/64")
        print("  If a router reboot is inside that window, this address is")
        print("  a reasonable candidate to whitelist. If it is not, reboot")
        print("  the router and watch for one more day before committing.")
    print("-" * 68)
    print("  Nothing here has been whitelisted. That is still a decision")
    print("  with a 7-day lock behind it.")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    elif "--watch" in sys.argv:
        print("  Watching every 10 minutes. Ctrl+C to stop.")
        try:
            while True:
                check()
                time.sleep(600)
        except KeyboardInterrupt:
            print("\n  Stopped.")
            report()
    else:
        check()
        print()
        print("  Logged to data/ip_history.csv")
        print("  See the picture so far with:  py tools/ip_watch.py --report")
