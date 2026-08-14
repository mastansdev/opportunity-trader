"""
Check the Telegram channels are reachable and say what they carry.

    py tools/telegram_check.py                 the configured channels
    py tools/telegram_check.py moneypurse      test one handle

No credentials. These are public channels and Telegram serves them as
plain HTML at t.me/s/<handle>.

Use this when a channel goes quiet on the dashboard, or to test a new
handle before adding it. It says which of the two kinds a channel is:

    TEXT    posts name their stock in the message -- readable
    IMAGE   posts are pictures with no text -- shown, not read
"""

import sys

sys.path.insert(0, ".")

from core.logger import decision, warn
from core.telegram_feed import CHANNELS
from core.telegram_web import TelegramWebReader


def main():
    handles = sys.argv[1:] or [c["handle"] for c in CHANNELS]
    names = {c["handle"]: c.get("name", c["handle"]) for c in CHANNELS}
    reader = TelegramWebReader()
    ok = 0

    for handle in handles:
        handle = handle.strip().lstrip("@").replace("https://t.me/", "")
        try:
            messages = reader.fetch(handle, limit=25)
        except Exception as exc:                           # noqa: BLE001
            warn(f"  UNREACHABLE  {handle:<20} {exc}")
            continue

        if not messages:
            warn(f"  NO MESSAGES  {handle:<20} private channel, or the "
                 f"handle is wrong")
            continue

        ok += 1
        with_text = sum(1 for m in messages if m["text"])
        with_photo = sum(1 for m in messages if m["photos"])
        graded = sum(1 for m in messages if m["grade"])
        tagged = sum(1 for m in messages if m["hashtags"])
        kind = "TEXT" if with_text > len(messages) / 2 else "IMAGE"
        newest = max((m["at"] for m in messages if m["at"]), default=None)

        decision(f"  OK  {handle:<20} {names.get(handle, ''):<18} {kind}")
        decision(f"      {len(messages)} messages · {with_text} with text · "
                 f"{with_photo} with a picture · {tagged} with a #ticker · "
                 f"{graded} graded")
        if newest:
            decision(f"      newest {newest.strftime('%d %b %H:%M')} UTC")
        for message in messages[-3:]:
            body = (message["text"] or "").replace("\n", " ")[:70]
            decision(f"      {message['id']:<9} "
                     f"{body or '(picture, no text)'}")
        decision("")

    if ok != len(handles):
        warn(f"{ok} of {len(handles)} reachable. A channel with no web view "
             f"is private -- only the API path (core/telegram_client.py) "
             f"can read those, and that needs my.telegram.org.")
        sys.exit(1)
    decision(f"All {ok} channels reachable, no credentials needed.")


if __name__ == "__main__":
    main()
