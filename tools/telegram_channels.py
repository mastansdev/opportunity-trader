"""
==========================================================
What can this Telegram account actually read?
==========================================================
    py tools/telegram_channels.py
    py tools/telegram_channels.py --search pulse

Lists the channels and groups this account has JOINED, with the exact
name to copy into config.EXTRA_TELEGRAM_CHANNELS.

READ ONLY. It joins nothing, leaves nothing, posts nothing, and stores
nothing.

WHY IT EXISTS
-------------
A PUBLIC channel has an @handle you can read off its page. A PRIVATE
one has neither a handle nor a share link -- which is exactly what the
operator hit:

    "those pro channels are not showing link to share"

The only name a private channel has is its TITLE, and the only place
that title exists is inside the account that joined it. So rather than
guess at names, ask.

Copy the name EXACTLY as printed here. The resolver in
core/telegram_client.py matches on it, falling back to a partial match,
and reports honestly when it cannot find one.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.telegram_client import SESSION_PATH, telethon_available  # noqa: E402
from core.telegram_feed import CHANNELS                    # noqa: E402


def _line():
    decision("-" * 72)


def main(search=None):
    decision("=" * 72)
    decision("  TELEGRAM -- what this account can read")
    decision("=" * 72)

    if not telethon_available():
        warn("  telethon is not installed.   py -m pip install telethon")
        return 1
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        warn("  TELEGRAM_API_ID / TELEGRAM_API_HASH are not in .env.")
        return 1
    if not os.path.exists(SESSION_PATH + ".session"):
        warn("  Not logged in.   py tools/telegram_setup.py")
        return 1

    from telethon.sync import TelegramClient

    already = {(c["handle"] if isinstance(c, dict) else c).lower()
               for c in CHANNELS}
    already |= {(c.get("name", "") if isinstance(c, dict) else "").lower()
                for c in CHANNELS}

    client = TelegramClient(SESSION_PATH, int(api_id), api_hash)
    client.connect()
    if not client.is_user_authorized():
        warn("  The session exists but is not authorised. Run "
             "py tools/telegram_setup.py again.")
        client.disconnect()
        return 1

    rows = []
    try:
        from core.telegram_client import _is_readable_source
        for dialog in client.iter_dialogs():
            entity = dialog.entity
            # Channels, groups and BOTS. A human chat is not a news
            # source and has no business in this list.
            if not _is_readable_source(entity):
                continue
            name = (getattr(dialog, "name", "") or "").strip()
            handle = getattr(entity, "username", None)
            private = handle is None
            if getattr(entity, "bot", False):
                name = f"{name}  [bot]"
            if search and search.lower() not in name.lower():
                continue
            rows.append((name, handle, private))
    finally:
        client.disconnect()

    if not rows:
        warn("  No channels found." if not search else
             f"  Nothing matching {search!r}.")
        return 0

    _line()
    decision(f"  {len(rows)} channel(s) this account has joined")
    _line()
    decision(f"    {'NAME':44} {'HANDLE':22} STATUS")
    for name, handle, private in sorted(rows, key=lambda r: r[0].lower()):
        known = name.lower() in already or (handle or "").lower() in already
        status = "already watched" if known else \
                 ("PRIVATE -- use the name" if private else "public")
        decision(f"    {name[:44]:44} "
                 f"{('@' + handle) if handle else '(none)':22} {status}")

    _line()
    decision("  To add one, put its NAME in config.py:")
    decision("")
    decision("      EXTRA_TELEGRAM_CHANNELS = [")
    decision('          "Exact Name As Printed Above",')
    decision("      ]")
    decision("")
    decision("  A private channel is reachable ONLY through the API, so")
    decision("  it stays empty if the session ever expires -- the public")
    decision("  four fall back to the web view, these cannot.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    term = args[args.index("--search") + 1] if "--search" in args else None
    sys.exit(main(search=term))
