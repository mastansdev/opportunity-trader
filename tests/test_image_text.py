"""
Reading the text inside a picture.

    "Day Trader Telugu posts all important news in live markets. NONE of
     them are being used by bot. WHY?"
    "all images are english only that too taken from X , or any other
     reliable sources only"
                                    -- operator, 30 July 2026

77 of that channel's 90 stored messages carry no text at all. The news
is inside a forwarded screenshot, and the bot could not read one.

These tests do NOT check OCR accuracy -- that depends on an engine that
may not be installed, and a test that silently skips is a test that
lies. They check the things that are this codebase's job: that a
missing engine costs the feature and never the session, that a
transcript is never mistaken for something a human typed, and that a
picture earns no more trust than any other message.
"""

import pytest

from core import image_text


def test_a_missing_reader_is_reported_not_raised(monkeypatch):
    """The operator has no ANTHROPIC_API_KEY and may not have Tesseract.
    Neither is an error -- it is a feature that is off."""
    monkeypatch.setattr(image_text, "_backend", None)
    monkeypatch.setattr(image_text, "_try_tesseract", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert image_text.available() is False
    assert image_text.read(b"anything") == ""
    why = image_text.why_unavailable()
    assert "Tesseract" in why and "ANTHROPIC_API_KEY" in why, (
        "the message must say what to actually do about it")


def test_local_and_free_is_preferred_over_paid_and_remote(monkeypatch):
    monkeypatch.setattr(image_text, "_backend", None)
    monkeypatch.setattr(image_text, "_try_tesseract", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert image_text.backend() == "tesseract", (
        "reading a screenshot of a headline must not require an API key")


def test_claude_is_the_fallback_when_tesseract_is_absent(monkeypatch):
    monkeypatch.setattr(image_text, "_backend", None)
    monkeypatch.setattr(image_text, "_try_tesseract", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert image_text.backend() == "claude"


def test_a_broken_reader_returns_empty_rather_than_raising(monkeypatch):
    """Nothing about a chat feed may be able to stop a trading session."""
    monkeypatch.setattr(image_text, "_backend", "tesseract")
    def boom(_data):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(image_text, "_read_tesseract", boom)
    assert image_text.read(b"\x89PNG") == ""


def test_a_fetch_failure_is_none_not_an_exception(monkeypatch):
    """Telegram CDN links expire. A 404 on a month-old image is normal."""
    assert image_text.fetch("") is None
    assert image_text.fetch(None) is None


def test_noise_is_not_stored_as_a_transcript():
    """A logo or an uncaptioned chart produces a handful of stray
    characters. Storing that is worse than storing nothing, because
    noise reaches the matcher."""
    assert image_text.clean("|| -- ~~") == ""
    assert image_text.clean("BEL") == "", "too short to be worth matching"
    long_enough = ("BREAKING: Bharat Electronics wins order worth "
                   "Rs 2,210 crore. #BEL")
    assert image_text.clean(long_enough) == long_enough


def test_cleaning_does_not_change_what_the_text_says():
    """Tidying whitespace is fine. Rewording is not -- the transcript is
    evidence."""
    messy = "  BREAKING:   Bharat  Electronics  wins\n\n\n  Rs 2,210 crore\n"
    out = image_text.clean(messy)
    assert out == "BREAKING: Bharat Electronics wins\nRs 2,210 crore"
    assert "2,210" in out, "numbers must survive exactly"


def test_border_art_lines_are_dropped():
    text = "=======\nBharat Electronics wins Rs 2,210 crore order\n-------"
    assert image_text.clean(text) == "Bharat Electronics wins Rs 2,210 crore order"


def test_there_is_a_size_cap():
    """A chat feed is not worth a decompression bomb."""
    assert image_text.MAX_BYTES <= 16 * 1024 * 1024
    assert image_text.FETCH_TIMEOUT <= 15, (
        "an image fetch must not hang a poll that runs during the session")


# ---------------------------------------------------------------
# THE TRANSCRIPT IS ITS OWN THING
# ---------------------------------------------------------------

def test_ocr_text_is_a_separate_column():
    """Never merged into `text`. It must stay possible to tell what a
    human typed from what a machine read off a picture."""
    src = open("core/telegram_feed.py", encoding="utf-8").read()
    assert '("ocr_text", "TEXT")' in src
    assert "ocr_text" in src.split("INSERT OR IGNORE INTO messages")[1][:300]


def test_reading_images_can_be_turned_off(tmp_path):
    """The RULE, not the line that implements it.

    This used to assert the literal source `if photos and
    self.read_images:` and broke on 1 August when the Telegram API
    reader arrived -- its photos have no URL, so the condition grew a
    second source. The behaviour it guards was never in question.
    """
    from core.telegram_feed import TelegramFeed

    read = []
    for enabled in (True, False):
        feed = TelegramFeed(client=None, master_loader=None,
                            db_path=str(tmp_path / f"tg{enabled}.db"),
                            read_images=enabled)
        feed.symbols_in = lambda t: []
        feed.names_in = lambda t: []
        feed._read_photo = lambda url=None, data=None: read.append(url) or "x"
        feed._store({"name": "Day Trader Telugu", "handle": "x",
                     "kind": "image"},
                    [{"id": "1", "at": "2026-08-01T10:00:00", "text": "",
                      "photos": ["http://example/card.png"]}])
    assert read == ["http://example/card.png"], (
        "with read_images off, no image may be read")


def test_symbols_from_a_picture_go_through_the_same_matcher():
    """A picture earns no extra trust for having been harder to read."""
    src = open("core/telegram_feed.py", encoding="utf-8").read()
    block = src[src.find("ocr = self._read_photo"):]
    assert "self.symbols_in(ocr)" in block[:400], (
        "OCR text must go through symbols_in(), not a looser path")


def test_the_backfill_tool_requires_capitals_for_a_bare_ticker():
    """OCR of a news card produces plenty of ordinary lowercase prose,
    and DOLLAR is both a currency and a textiles company."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "telegram_ocr", "tools/telegram_ocr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tagged = {"DOLLAR", "BEL", "LT"}
    plain = {"DOLLAR", "BEL"}
    assert mod.symbols_for("the dollar weakened today", tagged, plain) == []
    assert mod.symbols_for("DOLLAR posts higher margins", tagged, plain) == ["DOLLAR"]
    assert mod.symbols_for("order win #LT confirmed", tagged, plain) == ["LT"], (
        "an explicit hashtag beats the three-character floor")


# ---------------------------------------------------------------
# THE ADVICE MUST NAME THE ACTUAL MISSING PIECE
# ---------------------------------------------------------------
# 30 July 2026. The operator ran `py -m pip install pytesseract pillow`,
# it succeeded, and the bot told him:
#
#     no image reader: install Tesseract (...) and `pip install
#     pytesseract pillow`, or set ANTHROPIC_API_KEY
#
# One message for every failure, telling him to install a package he had
# installed two minutes earlier. An error that does not distinguish its
# causes is a dead end, and this is the second time in one day that a
# vague message cost a round trip -- see the search box.

def test_a_missing_engine_does_not_blame_the_python_package(monkeypatch):
    monkeypatch.setattr(image_text, "_backend", None)
    monkeypatch.setattr(image_text, "_missing", "engine")
    monkeypatch.setattr(image_text, "_try_tesseract", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    why = image_text.why_unavailable()
    assert "ENGINE" in why
    assert "pip install" not in why, (
        "the wrapper is already installed -- saying so again is a dead end")


def test_a_missing_wrapper_says_how_to_install_it(monkeypatch):
    monkeypatch.setattr(image_text, "_backend", None)
    monkeypatch.setattr(image_text, "_missing", "wrapper")
    monkeypatch.setattr(image_text, "_try_tesseract", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    why = image_text.why_unavailable()
    assert "py -m pip install" in why, (
        "plain `pip` is not on this operator's PATH -- the advice has to "
        "be a command that actually runs on his machine")


# ---------------------------------------------------------------
# FINDING THE ENGINE WINDOWS HID
# ---------------------------------------------------------------
# The UB Mannheim installer does not add itself to PATH. Without this,
# installing Tesseract correctly still leaves the bot unable to see it,
# and the operator is sent to edit environment variables.

def test_path_is_tried_first(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/tesseract")
    assert image_text._find_tesseract_binary() == "/usr/bin/tesseract"


def test_the_standard_windows_folders_are_checked(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _n: None)
    fake = tmp_path / "tesseract.exe"
    fake.write_text("x")
    monkeypatch.setattr(image_text, "_WINDOWS_GUESSES", (str(fake),))
    assert image_text._find_tesseract_binary() == str(fake)


def test_a_genuinely_absent_engine_is_still_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _n: None)
    monkeypatch.setattr(image_text, "_WINDOWS_GUESSES",
                        (r"C:\nope\tesseract.exe",))
    assert image_text._find_tesseract_binary() is None


def test_the_guesses_cover_both_program_files_and_localappdata():
    """The installer offers a per-machine and a per-user install, and
    they land in different places."""
    joined = " ".join(image_text._WINDOWS_GUESSES).lower()
    assert "program files" in joined
    assert "tesseract-ocr" in joined
    assert len(image_text._WINDOWS_GUESSES) >= 3


# ---------------------------------------------------------------
# "GONE" WAS TRUE AND USELESS
# ---------------------------------------------------------------
# 30 July 2026, the first real run: ten images, "gone 10", end of
# information. Two completely different situations produce that number:
#
#     the link expired          Telegram CDN links do not live forever
#     the machine cannot reach  proxy, firewall, DNS, VPN
#
# The first is normal and needs nothing. The second means the feature
# will never work. A counter that cannot tell them apart sends somebody
# looking in the wrong place -- and it did: the run was inside a
# sandbox behind a proxy, and it read like the operator's images were
# too old.

class _Response:
    def __init__(self, status=200, body=b"data", length=None):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Length": str(length if length is not None
                                              else len(body))}


def test_an_expired_link_says_expired(monkeypatch):
    import sys, types
    fake = types.ModuleType("requests")
    fake.get = lambda *a, **k: _Response(status=404)
    monkeypatch.setitem(sys.modules, "requests", fake)
    data, reason = image_text.fetch_with_reason("http://x/y.jpg")
    assert data is None
    assert "expired" in reason and "404" in reason


def test_a_network_failure_says_unreachable(monkeypatch):
    """The one that matters. This must never read as 'your images are
    too old'."""
    import sys, types
    fake = types.ModuleType("requests")
    def boom(*a, **k):
        raise OSError("ProxyError")
    fake.get = boom
    monkeypatch.setitem(sys.modules, "requests", fake)
    data, reason = image_text.fetch_with_reason("http://x/y.jpg")
    assert data is None
    assert "unreachable" in reason
    assert "expired" not in reason


def test_an_oversized_image_is_refused_by_size(monkeypatch):
    import sys, types
    fake = types.ModuleType("requests")
    fake.get = lambda *a, **k: _Response(length=image_text.MAX_BYTES + 1)
    monkeypatch.setitem(sys.modules, "requests", fake)
    data, reason = image_text.fetch_with_reason("http://x/y.jpg")
    assert data is None and "too big" in reason


def test_a_good_fetch_returns_bytes_and_no_reason(monkeypatch):
    import sys, types
    fake = types.ModuleType("requests")
    fake.get = lambda *a, **k: _Response(body=b"\x89PNG12345")
    monkeypatch.setitem(sys.modules, "requests", fake)
    data, reason = image_text.fetch_with_reason("http://x/y.jpg")
    assert data == b"\x89PNG12345"
    assert reason is None


def test_the_tool_warns_loudly_on_a_network_failure():
    """Because the operator will otherwise conclude the wrong thing."""
    src = open("tools/telegram_ocr.py", encoding="utf-8").read()
    assert 'if any("unreachable"' in src
    assert "cannot reach Telegram" in src


def test_the_tool_migrates_before_it_queries():
    """The first real run died on `no such column: ocr_text`. The tool
    opens sqlite directly, so it never triggered the migration that
    TelegramFeed performs on startup."""
    src = open("tools/telegram_ocr.py", encoding="utf-8").read()
    migrate = src.find("TelegramFeed(client=None, db_path=path)")
    query = src.find("select rowid, channel, at, text")
    assert -1 not in (migrate, query)
    assert migrate < query, "the migration must run before the query"
    # Checked on CODE, not on prose. The comment above the migration
    # explains why there is no second ALTER TABLE here -- and the first
    # version of this assertion matched that explanation and failed.
    # That is twice in one session (see "Top 50 Gainers" in the
    # dashboard contract), so: strip comments and strings first.
    import io, tokenize
    code = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            code.append(tok.string)
    assert "ALTER" not in " ".join(code).upper(), (
        "the schema has ONE definition, in TelegramFeed._migrate(). A "
        "second ALTER here would be a second source of truth and the "
        "two would drift.")
