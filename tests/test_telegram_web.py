"""
Tests for core/telegram_web.py -- reading public channels with no
credentials at all.

    "both possible ? as both are genuine & i'm using since long.
     daytrader channel posts all images from X accounts & other
     sources which i can consider one reliable place to find all info"
                                    -- operator, 29 July 2026

Two channels, two shapes, both measured off the live pages on
29 July before a line of this was written:

    @earnings_pulse    "#UPL - Great Results - 1 minute ago" plus a
                       link to the filing PDF, 1-2 minutes after it
                       lands. A ticker, a grade, a source.

    @daytradertelugu   Twenty consecutive market-hours posts with NO
                       text at all. 173,000 photos. The news is
                       inside the pictures.

An image-only post MUST survive parsing. Dropping it -- the obvious
thing for a text parser to do -- would empty the one panel the
operator most wants, and it is the bug this file exists to prevent.
"""

from core.telegram_web import (TelegramWebReader, parse_channel_html,
                               _pulse_fields)


def _post(post_id, text="", photo=None, links=(), when="2026-05-11T09:17:00+00:00"):
    """One message in Telegram's own HTML shape. The channel avatar
    appears on EVERY message and must never be mistaken for content."""
    avatar = ('<a class="tgme_widget_message_user_photo" '
              "style=\"background-image:url('https://cdn5.telesco.pe/file/AV.jpg')\"></a>")
    picture = ("<a class=\"tgme_widget_message_photo_wrap\" "
               f"style=\"background-image:url('{photo}')\"></a>") if photo else ""
    body = (f'<div class="tgme_widget_message js-widget_message" '
            f'data-post="{post_id}">{avatar}{picture}')
    if text:
        body += ('<div class="tgme_widget_message_text js-message_text">'
                 f"{text}</div>")
    for link in links:
        body += f'<a href="{link}">Result</a>'
    body += f'<time class="time" datetime="{when}">09:17</time></div>'
    return body


PULSE = _post("earnings_pulse/10084",
              text='<a href="?q=%23MOLDTKPAC">#MOLDTKPAC</a> - '
                   "&#127775; Great Results - 1 minute ago",
              links=["https://www.bseindia.com/xml-data/corpfiling/"
                     "AttachLive/abc.pdf"])
IMAGE_ONLY = _post("daytradertelugu/198788",
                   photo="https://cdn5.telesco.pe/file/NEWSPIC.jpg")
CALENDAR = _post("earnings_pulse/10086",
                 text="&#128197; Tomorrow's Earnings Calendar - 12 May, 2026"
                      "<br>Key companies reporting results: "
                      "<a>#TATAPOWER</a> <a>#DRREDDY</a> <a>#DIXON</a>")


# ---------------------------------------------------------------
# the structured channel
# ---------------------------------------------------------------

def test_the_ticker_comes_from_the_hashtag():
    """Far more reliable than reading prose -- the channel names its
    stock exactly."""
    row = parse_channel_html(PULSE)[0]
    assert row["hashtags"] == ["MOLDTKPAC"]


def test_the_grade_is_read_as_published():
    row = parse_channel_html(PULSE)[0]
    assert row["grade"] == "GREAT"


def test_every_grade_level_is_recognised():
    for text, expected in (("Great Results", "GREAT"), ("Good Results", "GOOD"),
                           ("OK Results", "OK"), ("Bad Results", "BAD"),
                           ("Weak Results", "WEAK")):
        assert _pulse_fields(f"#X - {text} - 1 minute ago", [])["grade"] \
            == expected


def test_an_ungraded_post_is_None_not_guessed():
    assert _pulse_fields("just some chatter", [])["grade"] is None


def test_the_filing_link_is_kept():
    """The whole reason this channel is worth reading -- it carries
    the source document, not just an opinion about it."""
    row = parse_channel_html(PULSE)[0]
    assert row["filing_url"].endswith(".pdf")
    assert "bseindia" in row["filing_url"]


def test_the_nse_archive_link_is_recognised_too():
    fields = _pulse_fields("#UPL", [
        "https://nsearchives.nseindia.com/corporate/UPL_x.pdf"])
    assert fields["filing_url"].startswith("https://nsearchives")


def test_the_earnings_calendar_post_is_flagged():
    """"i dont know which stock is getting results" -- this post is
    exactly that list, a day ahead."""
    row = parse_channel_html(CALENDAR)[0]
    assert row["is_calendar"] is True
    assert row["hashtags"] == ["TATAPOWER", "DRREDDY", "DIXON"]


def test_html_entities_become_real_characters():
    row = parse_channel_html(CALENDAR)[0]
    assert "&#128197;" not in row["text"]
    assert "Tomorrow's Earnings Calendar" in row["text"]


def test_the_timestamp_is_parsed():
    row = parse_channel_html(PULSE)[0]
    assert row["at"].hour == 9 and row["at"].minute == 17


# ---------------------------------------------------------------
# the image channel -- the bug this file exists to prevent
# ---------------------------------------------------------------

def test_a_post_with_no_text_at_all_still_comes_through():
    """Twenty consecutive market-hours posts on @daytradertelugu had
    no text. A text parser that skips them empties the panel."""
    rows = parse_channel_html(IMAGE_ONLY)
    assert len(rows) == 1
    assert rows[0]["text"] == ""
    assert rows[0]["photos"] == ["https://cdn5.telesco.pe/file/NEWSPIC.jpg"]


def test_the_channel_avatar_is_not_mistaken_for_content():
    """It appears on every single message. Showing it would put the
    same logo under every post."""
    rows = parse_channel_html(IMAGE_ONLY)
    assert all("AV.jpg" not in p for p in rows[0]["photos"])


def test_a_text_post_with_no_picture_has_no_photos():
    assert parse_channel_html(PULSE)[0]["photos"] == []


def test_a_link_back_to_the_post_itself_is_kept():
    """So the operator can open the original and read the picture
    full size."""
    assert parse_channel_html(IMAGE_ONLY)[0]["url"] \
        == "https://t.me/daytradertelugu/198788"


# ---------------------------------------------------------------
# several messages, and junk
# ---------------------------------------------------------------

def test_a_whole_page_of_mixed_messages_parses():
    rows = parse_channel_html(PULSE + IMAGE_ONLY + CALENDAR)
    assert [r["id"] for r in rows] == ["10084", "198788", "10086"]


def test_a_completely_empty_post_is_dropped():
    assert parse_channel_html(_post("x/1")) == []


def test_junk_html_is_survivable():
    assert parse_channel_html("") == []
    assert parse_channel_html(None) == []
    assert parse_channel_html("<html>nothing here</html>") == []


def test_a_broken_timestamp_does_not_lose_the_message():
    rows = parse_channel_html(_post("x/1", text="hello", when="not a date"))
    assert len(rows) == 1
    assert rows[0]["at"] is None


# ---------------------------------------------------------------
# the reader
# ---------------------------------------------------------------

def test_the_handle_is_cleaned_before_it_is_fetched():
    seen = []

    def opener(url):
        seen.append(url)
        return PULSE

    TelegramWebReader(opener=opener).fetch("@earnings_pulse")
    assert seen == ["https://t.me/s/earnings_pulse"]


def test_a_private_channel_returns_nothing_rather_than_pretending():
    """A private channel has no web view at all. Empty is the honest
    answer; the warning tells the operator why."""
    reader = TelegramWebReader(opener=lambda url: "<html>no messages</html>")
    assert reader.fetch("secret") == []
