"""
==========================================================
Reading public Telegram channels with no credentials
==========================================================

    "both possible ? as both are genuine & i'm using since long.
     daytrader channel posts all images from X accounts & other
     sources which i can consider one reliable place to find all
     info"                          -- operator, 29 July 2026

WHY THIS EXISTS
---------------
The API route (core/telegram_client.py) needs an api_id from
my.telegram.org, and that page returns a bare "ERROR" with no
explanation. Meanwhile every one of the operator's channels is
PUBLIC, and Telegram publishes a plain HTML view of every public
channel:

    https://t.me/s/earnings_pulse

No key, no login, no session file, no telethon. Verified against the
real pages on 29 July 2026.

TWO KINDS OF CHANNEL, AND THEY NEED DIFFERENT TREATMENT
-------------------------------------------------------
Measured, not assumed -- both were read before this was written.

  @earnings_pulse   STRUCTURED TEXT. Every post is
                        "#UPL - Great Results - 1 minute ago"
                    plus a link to the filing PDF, 1-2 minutes after
                    it lands. A ticker, a grade in four fixed levels,
                    and a source. This is data.

  @daytradertelugu  IMAGES. 173,000 photos, and twenty consecutive
                    market-hours posts (08:08-09:21) carried NO text
                    at all. The news is inside the pictures -- they
                    are screenshots from X and news sites.

So text extraction is right for one and useless for the other. For
the image channel this module keeps the PICTURE URL and the dashboard
shows the picture. The operator already reads these images himself;
showing them replaces the second screen he watches, and needs no OCR
to be worth having. Reading the pixels can come later, if ever.

WHAT IT NEVER DOES
------------------
Nothing here reaches core/engine.py. Not the grades, not the
mentions. A channel post is not a filing, the bot cannot tell a paid
promotion from a genuine call, and the standing rule is that an entry
needs a real reason. This is a reading panel.

Author : H&M Opportunity Trader
==========================================================
"""

import html
import re
import urllib.request
from datetime import datetime

from core.logger import diagnostic, warn

BASE = "https://t.me/s/{handle}"

# Telegram serves the plain HTML view to anything that looks like a
# browser. Without a User-Agent it returns the app-download page.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_MESSAGE = re.compile(
    r'<div class="tgme_widget_message[^"]*"[^>]*data-post="([^"]+)"(.*?)'
    r'(?=<div class="tgme_widget_message[^"]*"[^>]*data-post=|\Z)',
    re.S)
_TEXT = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
# Match the PICTURE element itself, not any background image.
#
# The first version grabbed every background-image on the message and
# then dropped the first one, assuming it was the avatar. It is --
# but a post with ONLY an avatar then looked like it had a photo,
# survived the "is this message empty" check, and rendered as a blank
# row. Matching the photo wrapper by its own class has no such
# assumption to get wrong.
_PHOTO = re.compile(
    r'<a class="tgme_widget_message_(?:photo_wrap|video_thumb)[^"]*"'
    r'[^>]*background-image:url\(\'([^\']+)\'\)')
_HASHTAG = re.compile(r"#([A-Z0-9&_-]{2,})")
_HREF = re.compile(r'href="(https?://[^"]+)"')
_TAG = re.compile(r"<[^>]+>")

# The Pulse channels grade every result. Read as published -- this
# module does not decide what a result is worth.
#
# "Excellent Results" was missing until 31 July 2026, and it is the
# channel's TOP grade. Eleven posts in three days carried it and this
# table saw none of them: ACMESOLAR, LXCHEM, GHCLTEXTIL, VAML,
# OCCLLTD, ASAHISONG, YASHO twice, ESAFSFB and GAIL twice.
#
# It was survivable only by luck. core/stock_events.py has a SECOND
# grader with its own word list, that one did include "excellent", and
# it is the one feeding the score -- so the ranking was right while
# the Telegram panel on the dashboard showed those same stocks
# ungraded. Two graders with two vocabularies, disagreeing in public.
#
# Ordered longest-phrase-first: "Strong Beat" must be tested before
# "Beat", or every strong beat is read as an ordinary one.
GRADES = (
    ("Excellent Results", "EXCELLENT"),
    ("Great Results", "GREAT"),
    ("Good Results", "GOOD"),
    ("OK Results", "OK"),
    ("Bad Results", "BAD"),
    ("Weak Results", "WEAK"),
    ("Poor Results", "POOR"),
    # The FinAI card's vocabulary, mapped onto the same six words so
    # that nothing downstream has to learn a second set. See
    # core/stock_events.py BEAT_TO_GRADE, which must agree with this.
    ("Strong Beat", "EXCELLENT"),
    ("Strong Miss", "POOR"),
    ("In-Line", "OK"),
    # This is a SUBSTRING match, not a regex, so a bare "Miss" would
    # fire on "commission", "emissions", "missile" and "dismissed" --
    # and grade a story about SEBI's commission as a bad quarter. The
    # channel always writes the verdict after the ticker dash, so
    # requiring the dash costs nothing real and removes the whole
    # class of false positive.
    ("Rating : Beat", "GOOD"),
    ("Rating: Beat", "GOOD"),
    ("Verdict: BEAT", "GOOD"),
    ("- Beat", "GOOD"),
    ("- Miss", "WEAK"),
)


def _clean(fragment):
    """HTML fragment -> plain text, with the line breaks kept."""
    if not fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = _TAG.sub("", text)
    return html.unescape(text).strip()


def parse_channel_html(page, handle=""):
    """The HTML of one t.me/s/ page -> a list of messages.

    Every field is optional. A post with no text is still returned if
    it has a photo -- that is the entire content of the image
    channels, and dropping it would empty the panel that matters most
    to the operator.
    """
    out = []
    for post_id, body in _MESSAGE.findall(page or ""):
        text_match = _TEXT.search(body)
        text = _clean(text_match.group(1)) if text_match else ""
        photos = _PHOTO.findall(body)
        when = None
        time_match = _TIME.search(body)
        if time_match:
            try:
                when = datetime.fromisoformat(
                    time_match.group(1).replace("Z", "+00:00"))
            except ValueError:
                when = None
        if not text and not photos:
            continue

        message = {
            "id": post_id.split("/")[-1],
            "channel": handle or post_id.split("/")[0],
            "at": when,
            "text": text,
            "photos": photos,
            "hashtags": _HASHTAG.findall(text.upper()),
            "links": [u for u in _HREF.findall(body)
                      if "t.me" not in u and "telegram.org" not in u],
            "url": f"https://t.me/{post_id}",
        }
        message.update(_pulse_fields(text, message["links"]))
        out.append(message)
    return out


def _pulse_fields(text, links):
    """The Earnings Pulse format, read as published.

        "#UPL - Great Results - 1 minute ago"  + link to the PDF

    The grade is REPORTED, never recomputed and never trusted as a
    decision. core/quarterly_results.py grades from the actual
    numbers in the filing; this is somebody else's opinion arriving
    faster, and the two must never be confused for each other.
    """
    out = {"grade": None, "filing_url": None, "is_calendar": False}
    upper = (text or "").upper()
    for needle, grade in GRADES:
        if needle.upper() in upper:
            out["grade"] = grade
            break
    for link in links:
        if link.lower().endswith(".pdf") or "corpfiling" in link.lower() \
                or "nsearchives" in link.lower():
            out["filing_url"] = link
            break
    # "Tomorrow's Earnings Calendar - 12 May, 2026 ... #TATAPOWER #DIXON"
    if "EARNINGS CALENDAR" in upper or "REPORTING RESULTS" in upper:
        out["is_calendar"] = True
    return out


class TelegramWebReader:
    """Fetches public channels over plain HTTP. No credentials.

    Same one method TelegramFeed calls, so it drops in wherever the
    telethon client would go and nothing downstream knows which it is
    talking to.
    """

    def __init__(self, timeout=20, opener=None):
        self.timeout = timeout
        self.opener = opener

    def _get(self, url):
        if self.opener is not None:
            return self.opener(url)
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def fetch(self, channel, limit=30, before=None, ids=None):
        # `ids` exists so this stays a drop-in for the API reader. The
        # public web view serves pages and cannot answer "give me post
        # 3741", so it says so instead of returning a page that was not
        # asked for. See core/telegram_client.FallbackReader.fetch().
        if ids:
            return []
        """Recent messages from one public channel.

        `channel` is the handle without the @ -- "earnings_pulse".
        Raises on a network failure so TelegramFeed can report which
        channel failed; it catches per channel, so one being down
        never costs the others.

        ---- `before`: READING BACKWARDS, 31 July 2026 ----

            "real gap as far i concerned about after my terminal(laptop)
             close to next opening. & weekends data?"
            "we cannot loose some important in weekends"

        One page of t.me/s/ carries about TWENTY posts. Measured on the
        real channels, they publish 6-10 an hour and 34% of everything
        arrives outside market hours -- so a 65-hour weekend is 400-700
        posts, and a single fetch on Monday morning recovers twenty of
        them. The rest were simply gone.

        Telegram paginates these pages itself, and says so in the HTML
        it serves. The live page carries:

            canonical: /s/earnings_pulse?before=10095
            <a href="https://t.me/s/earnings_pulse?before=10075">

        Post ids are sequential integers, so `?before=<id>` walks
        backwards a page at a time. That is a documented part of the
        page Telegram publishes, not a trick -- the "load older
        messages" link a browser follows when you scroll up.
        """
        handle = str(channel).strip().lstrip("@")
        url = BASE.format(handle=handle)
        if before:
            url = f"{url}?before={int(before)}"
        page = self._get(url)
        messages = parse_channel_html(page, handle)
        if not messages:
            warn(f"[TELEGRAM] {handle}: page fetched but no messages parsed "
                 f"-- Telegram may have changed its HTML, or the channel is "
                 f"private (a private channel has no web view at all).")
        diagnostic(f"[TELEGRAM] {handle}: {len(messages)} messages.")
        return messages[-limit:] if limit else messages
