"""
One-time Telegram login.

    py tools/telegram_setup.py

BEFORE RUNNING, five minutes of your own:

  1. Go to  https://my.telegram.org  and log in with your phone number.
  2. Click "API development tools", fill the short form (any app name,
     e.g. "opportunity-trader"). It gives you an api_id and api_hash.
  3. Put both in your .env file:

         TELEGRAM_API_ID=1234567
         TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789

  4. pip install telethon
  5. Run this script. It asks for your phone number and the code
     Telegram sends you, once. After that the bot reads the channels
     on its own.

WHY YOUR OWN ACCOUNT AND NOT A BOT: a Telegram bot can only read
channels it has been made an admin of. Day Trader Telugu, MoneyPurse,
EARNINGS PULSE and ORDERBOOK PULSE belong to other people -- you can
read them because you have joined them, so the client has to act as
you.

THE SESSION FILE IT WRITES (data/telegram_session.session) IS A
CREDENTIAL. Anyone who has it can read your Telegram. Do not commit
it, do not share it. It is in .gitignore.

This only ever READS. It never posts, joins, leaves or reacts.
"""

import os
import sys

sys.path.insert(0, ".")

from core.logger import decision, warn
from core.telegram_client import SESSION_PATH, telethon_available
from core.telegram_feed import CHANNELS


def main():
    if not telethon_available():
        warn("telethon is not installed. Run:  pip install telethon")
        sys.exit(1)

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        warn("TELEGRAM_API_ID / TELEGRAM_API_HASH are not in your .env.\n"
             "  Get them free at https://my.telegram.org -> "
             "API development tools,\n"
             "  then add both lines to .env and run this again.")
        sys.exit(1)

    from telethon.sync import TelegramClient

    decision("Logging in to Telegram -- once only.")
    decision("")
    # THE COUNTRY CODE IS NOT OPTIONAL, 1 August 2026.
    #
    # The operator typed a plain ten-digit Indian number and got
    # PhoneNumberInvalidError, followed by eighty lines of asyncio
    # teardown noise that buried it. Telethon's own prompt just says
    # "Please enter your phone (or bot token)" and gives no hint about
    # the format, so the failure looks like a broken tool rather than a
    # missing "+91".
    decision("  Enter your number in INTERNATIONAL format, with the")
    decision("  country code and a leading +.  For India that is")
    decision("      +91XXXXXXXXXX")
    decision("  A plain 10-digit number is rejected by Telegram.")
    decision("")

    client = TelegramClient(SESSION_PATH, int(api_id), api_hash)
    try:
        client.start()
    except Exception as exc:                               # noqa: BLE001
        name = type(exc).__name__
        warn("")
        if "PhoneNumberInvalid" in name:
            warn("Telegram rejected that number.")
            warn("Almost always the missing country code -- type it as")
            warn("    +91XXXXXXXXXX")
            warn("not as a bare 10-digit number.")
        elif "PhoneCodeInvalid" in name:
            warn("That login code was wrong. Run this again for a new one.")
        elif "PhoneCodeExpired" in name:
            warn("That code expired. Run this again -- they are short-lived.")
        elif "SessionPassword" in name:
            warn("This account has two-step verification on. Telethon will "
                 "ask for that password too; run this again and enter it "
                 "when prompted.")
        elif "FloodWait" in name:
            warn(f"Telegram is rate-limiting this account: {exc}")
            warn("Wait for the time it states and try once more. Repeated "
                 "attempts make it longer, not shorter.")
        else:
            warn(f"Login failed: {name}: {str(exc)[:160]}")
        warn("")
        warn("Nothing was saved. Your .env and the bot are untouched.")
        try:
            client.disconnect()
        except Exception:                                  # noqa: BLE001
            pass
        sys.exit(1)

    me = client.get_me()
    decision(f"Logged in as {getattr(me, 'username', None) or me.first_name}.")

    decision("")
    decision("Checking the four channels:")
    reachable = 0
    for channel in CHANNELS:
        # CHANNELS became a list of RECORDS when the feed learned that a
        # channel has a kind and a trust setting; this loop still passed
        # the whole record to Telegram and would raise on the first one.
        # 1 August 2026 -- found before the operator ran it, not after.
        handle = channel["handle"] if isinstance(channel, dict) else channel
        try:
            messages = list(client.iter_messages(handle, limit=1))
            newest = messages[0].date.strftime("%d %b %H:%M") \
                if messages else "no messages"
            decision(f"  OK       {handle:<20} newest: {newest}")
            reachable += 1
        except Exception as exc:                           # noqa: BLE001
            warn(f"  CANNOT   {handle:<20} {exc}")

    client.disconnect()
    decision("")
    if reachable == len(CHANNELS):
        decision("All four reachable. The dashboard panel will fill on the "
                 "next run of main.py.")
    else:
        warn(f"{reachable} of {len(CHANNELS)} reachable. A channel that "
             f"fails here is usually one this account has not JOINED, or "
             f"whose name differs from what we have. Join it in the "
             f"Telegram app, or send me its exact @handle and I will fix "
             f"the name in core/telegram_feed.py.")
    decision(f"Session saved to {SESSION_PATH}.session -- treat it like a "
             f"password.")


if __name__ == "__main__":
    main()
