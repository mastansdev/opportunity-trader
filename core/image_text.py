"""
==========================================================
Reading the text inside a picture
==========================================================

Day Trader Telugu forwards 90 messages a day and 77 of them are images
with no text at all. The bot polled them, stored them, and could not
read a word.

    "hey ... Day Trader Telugu posts all important news in live markets.
     NONE of them are being used by bot. WHY?"
                                    -- operator, 30 July 2026

    "all images are english only that too taken from X , or any other
     reliable sources only"

That second line is what makes this worth building. Screenshots of
tweets and news cards are the easy case for OCR: black text, white
background, large type, no handwriting, no camera angle. Measured on a
mock tweet card of exactly that shape, Tesseract recovered every fact
that mattered -- the company, the order value, the buyer, the move, and
the #TICKER:

    BREAKING: Bharat Electronics wins order worth Rs 2,210 crore from
    Ministry of Defence for supply of radar systems. Stock up 4.2% in
    early trade. #BEL

WHAT THIS IS NOT
----------------
It is not a claim that the picture was understood. It is a transcript.
The words come out; what they MEAN is decided downstream by exactly the
same matcher every other message goes through, with the same rules --
capitals for tickers, the master file for names. An image gets no
special trust for having been harder to read.

WHY TESSERACT FIRST
-------------------
It is free, local, needs no API key, and sends nothing anywhere. The
operator has no ANTHROPIC_API_KEY set and should not need one to read a
screenshot of a headline. Claude vision is available as a fallback when
the key exists and Tesseract is not installed -- better on messy cards,
but it costs money per image and adds a network round trip to a path
that runs during market hours.

FAILURE IS ALWAYS SILENT AND ALWAYS SAFE
----------------------------------------
Every entry point returns "" rather than raising. A picture the bot
cannot read is a picture it could not read before either. Nothing about
a chat feed may be able to stop a trading session.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import os

from core.logger import diagnostic, warn

# How long to wait for one image, and how big a file to accept. A chat
# feed is not worth a hung request or a decompression bomb.
FETCH_TIMEOUT = 8
MAX_BYTES = 8 * 1024 * 1024

# Below this many characters the "transcript" is noise -- a logo, a
# chart with no caption, a blurred crop. Storing noise is worse than
# storing nothing, because noise reaches the matcher.
MIN_USEFUL_CHARS = 25

_backend = None          # cached: "tesseract", "claude", or None


# The Windows installer does not add itself to PATH, and the operator hit
# exactly that on 30 July 2026: pytesseract imported fine, the engine was
# invisible, and the error message told him to install a Python package he
# had already installed. These are the standard install locations -- if
# the engine is on disk, the wrapper gets pointed at it rather than the
# operator being sent to edit environment variables.
_WINDOWS_GUESSES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%USERPROFILE%\AppData\Local\Tesseract-OCR\tesseract.exe"),
)

# Set when the engine is missing, so the advice can name the ACTUAL
# problem. "Install this Python package" is unhelpful to somebody who
# just installed it.
_missing = ""


def _find_tesseract_binary():
    """The engine's path, wherever Windows put it."""
    import shutil
    found = shutil.which("tesseract")
    if found:
        return found
    for guess in _WINDOWS_GUESSES:
        if guess and os.path.exists(guess):
            return guess
    return None


def _try_tesseract():
    global _missing
    try:
        import pytesseract
        from PIL import Image                               # noqa: F401
    except Exception:                                       # noqa: BLE001
        _missing = "wrapper"
        return False

    binary = _find_tesseract_binary()
    if binary:
        # Point the wrapper at it explicitly. shutil.which() already
        # covers a PATH install; this is for the ones that are not.
        pytesseract.pytesseract.tesseract_cmd = binary
    try:
        version = pytesseract.get_tesseract_version()
        diagnostic(f"[OCR] Tesseract {version} at {binary or 'PATH'}")
        return True
    except Exception as exc:                                # noqa: BLE001
        _missing = "engine"
        diagnostic(f"[OCR] pytesseract is installed but the Tesseract "
                   f"engine is not reachable ({exc}).")
        return False


def backend():
    """Which reader is available, decided once.

    Order is deliberate: local and free before paid and remote.
    """
    global _backend
    if _backend is not None:
        return _backend
    if _try_tesseract():
        _backend = "tesseract"
    elif os.getenv("ANTHROPIC_API_KEY"):
        _backend = "claude"
    else:
        _backend = None
    return _backend


def available():
    return backend() is not None


def why_unavailable():
    """A sentence the operator can act on.

    It has to name the ACTUAL missing piece. The first version said
    "install Tesseract and pip install pytesseract pillow" for every
    failure, and told the operator to install a Python package he had
    installed two minutes earlier.
    """
    if available():
        return ""
    if _missing == "wrapper":
        return ("no image reader: run  py -m pip install pytesseract pillow  "
                "(the Tesseract engine is needed too -- "
                "https://github.com/UB-Mannheim/tesseract/wiki)")
    if _missing == "engine":
        return ("pytesseract is installed but the Tesseract ENGINE is not. "
                "That is a separate download: "
                "https://github.com/UB-Mannheim/tesseract/wiki -- run the "
                ".exe installer and accept the defaults. No PATH change "
                "needed; the bot checks the standard install folders.")
    return ("no image reader: install Tesseract "
            "(https://github.com/UB-Mannheim/tesseract/wiki), or set "
            "ANTHROPIC_API_KEY to use Claude vision instead")


def fetch_with_reason(url):
    """(bytes, reason). One of them is always None.

    WHY THE REASON MATTERS -- 30 July 2026. The first real run reported
    "gone 10" for ten images and that was the end of the information.
    Two completely different situations produce it:

        the link expired          Telegram CDN links do not live forever
        the machine cannot reach  no route, DNS, proxy, firewall

    The first is normal and needs no action. The second means the
    feature will never work and the operator should be told so, not left
    to conclude his images are too old. A counter that cannot tell them
    apart sends somebody looking in the wrong place.
    """
    if not url:
        return None, "no url"
    try:
        import requests
    except Exception:                                       # noqa: BLE001
        return None, "requests is not installed"
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT, stream=True)
    except Exception as exc:                                # noqa: BLE001
        # Connection, DNS, timeout, proxy. Nothing to do with the image.
        return None, f"unreachable ({type(exc).__name__})"
    if response.status_code in (403, 404, 410):
        return None, f"expired ({response.status_code})"
    if response.status_code >= 400:
        return None, f"http {response.status_code}"
    size = int(response.headers.get("Content-Length") or 0)
    if size and size > MAX_BYTES:
        return None, f"too big ({size} bytes)"
    try:
        data = response.content
    except Exception as exc:                                # noqa: BLE001
        return None, f"read failed ({type(exc).__name__})"
    if len(data) > MAX_BYTES:
        return None, f"too big ({len(data)} bytes)"
    return data, None


def fetch(url):
    """The bytes of one image, or None. See fetch_with_reason()."""
    data, reason = fetch_with_reason(url)
    if data is None and reason not in (None, "no url"):
        diagnostic(f"[OCR] {reason}: {url[:60]}")
    return data


def _read_tesseract(data):
    from PIL import Image
    import pytesseract
    # backend() has already resolved and set tesseract_cmd if the engine
    # was found somewhere other than PATH.
    image = Image.open(io.BytesIO(data))
    # Greyscale and a generous upscale. Forwarded screenshots are often
    # re-compressed down to phone width, and Tesseract's accuracy falls
    # off a cliff under roughly 20px of text height.
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    if image.width < 1000:
        scale = min(2.0, 1000 / max(image.width, 1))
        image = image.resize((int(image.width * scale),
                              int(image.height * scale)))
    return pytesseract.image_to_string(image) or ""


def words_with_positions(data):
    """[{text, left, top, width, height}] for every word Tesseract sees.

    ---- WHY POSITION AND NOT READING ORDER. 2 August 2026. ----

        "what if i didn't asked you to tell me what our bot will do
         this image? we never know right"

    He is right, and the case that proved it is the 03 August calendar
    card. It is a GRID OF LOGOS with the ticker printed under each one.
    Tesseract walks that column by column, so the flat transcript comes
    out as:

        DURING MARKET HOURS
        UPL GLAXO
        DHANUKA CRIZAC          <- only 4 of the 19 DURING names
        AFTER MARKET HOURS
        DLF SBIFUNDS
        ...
        During/After forecast is based on past behavior...   <- FOOTER
        BLUEJET
        ETHOSLTD                <- these are DURING, dumped at the end
        AVADHSUGAR
        VELJAN

    Splitting that on the two headings put NINE stocks that report
    while the market is open into the "after the close" bucket, and
    six more were never read at all. Four of nineteen were right.

    A stock reporting DURING the session is one to have on screen at
    09:15. Filed as AFTER it is ignored until the next morning -- and
    nothing anywhere said so.

    The y-coordinate does not care what order Tesseract walked in.
    Returns [] on any problem, so every existing caller that wants a
    flat transcript is untouched.
    """
    if not data:
        return []
    try:
        from PIL import Image
        import pytesseract
        if backend() != "tesseract":
            return []
        image = Image.open(io.BytesIO(data))
        if image.mode not in ("L", "RGB"):
            image = image.convert("RGB")
        if image.width < 1000:
            scale = min(2.0, 1000 / max(image.width, 1))
            image = image.resize((int(image.width * scale),
                                  int(image.height * scale)))
        raw = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT)
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[OCR] Word positions unavailable: {exc}")
        return []

    out = []
    for i, word in enumerate(raw.get("text") or []):
        word = (word or "").strip()
        if not word:
            continue
        try:
            conf = float(raw["conf"][i])
        except (KeyError, ValueError, TypeError):
            conf = 0.0
        # -1 means Tesseract is reporting a layout block, not a word.
        if conf < 0:
            continue
        out.append({
            "text": word,
            "left": int(raw["left"][i]),
            "top": int(raw["top"][i]),
            "width": int(raw["width"][i]),
            "height": int(raw["height"][i]),
            "conf": conf,
        })
    return out


def _read_claude(data, budget=None):
    # ---- THE MOST EXPENSIVE CALL IN THE BOT, AND THE ONLY ONE THAT
    #      NEITHER RECORDED NOR ASKED. 16 August 2026. ----
    #
    #     "5$ completed within 5 days"      -- operator
    #
    # data/ai_spend.db recorded $1.4321 across 1,892 calls for that
    # window and the arithmetic is exact against Haiku 4.5's published
    # rates -- so the ledger was not wrong, it was INCOMPLETE. It knew
    # two purposes, news_direction and ai_check. Five modules reach
    # messages.create().
    #
    # This is the vision path: a base64 JPEG in the prompt. An image is
    # billed by its pixels, not its characters, so one call here costs
    # multiples of the 469-token text calls that made up the whole
    # ledger -- and it was charged to him with no row written and no
    # cap consulted.
    #
    # Note it is tried SECOND: _read_tesseract() runs locally and free,
    # and this only runs when that fails or is not installed. That
    # limits the volume; it never limited the spend.
    import base64
    from core.morning_brief import anthropic_client
    client = anthropic_client()
    if client is None:
        return ""
    if budget is None:
        from core.ai_budget import AiBudget
        budget = AiBudget()
    allowed, why = budget.may_call()
    if not allowed:
        warn(f"[IMAGE] Not reading with the model: {why}")
        return ""
    encoded = base64.standard_b64encode(data).decode("ascii")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/jpeg",
                                         "data": encoded}},
            # TRANSCRIBE, do not summarise. A summary is the model's
            # opinion, and an opinion stored as if it were the source is
            # the thing this codebase keeps having to undo.
            {"type": "text", "text":
                "Transcribe every word of text visible in this image, "
                "exactly as written. Keep tickers, numbers and currency "
                "amounts exact. Do not summarise, explain or add "
                "anything. If there is no text, reply with nothing."},
        ]}],
    )
    usage = getattr(message, "usage", None)
    if usage is not None:
        # An image's cost arrives in input_tokens like any other input,
        # so nothing special is needed here beyond actually WRITING the
        # row -- which is the whole of what was missing.
        budget.record(
            "claude-haiku-4-5-20251001", purpose="image_text",
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(
                usage, "cache_creation_input_tokens", 0) or 0)
    parts = [b.text for b in message.content if getattr(b, "text", None)]
    return "\n".join(parts)


def claude_available():
    """Is the paid reader usable? Only if a key is set.

    Separate from backend(), which answers "which reader do we START
    with". This answers "is there a second opinion available", and the
    two are different questions -- see read().
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic                                   # noqa: F401
    except Exception:                                      # noqa: BLE001
        return False
    return True


def read(data):
    """Transcribe image bytes. Never raises.

    ==============================================================
    A SECOND LOOK, NOT A SECOND READER.  5 September 2026.
    ==============================================================

        "for me all info must be tagged properly & never mis ,
         duplicate , thats it"                  -- the operator

    Claude vision used to run only when Tesseract was ABSENT. That is
    backwards: an installed reader that returns nothing is exactly the
    case where a second opinion is worth paying for, and it was the one
    case that never got one.

    Measured on data/telegram.db, 30 July to 5 September: of 1,321
    pictures, 138 came back blank. Most had a caption carrying the news
    -- but SIX had nothing at all, no caption and no transcript, and
    those six are gone for good.

    So: the free reader always goes first, on every image, exactly as
    before. The paid one is asked ONLY when the free one produced
    nothing usable -- fewer than MIN_USEFUL_CHARS of real writing. On
    the measured history that is about one image in ten, and on most
    days none at all.

    WHY NOT ON EVERY IMAGE. It costs money per picture and adds a
    network round trip to a path that runs during market hours. The
    free reader is already correct on the thing that matters most:
    2,489 crore figures were read out of pictures and not one of them
    is impossible. Paying to re-read what is already right is spending
    for no gain.

    A blank result stays "" and stays safe. Nothing about a chat feed
    may stop a trading session.
    """
    if not data:
        return ""
    which = backend()
    if which is None:
        return ""
    try:
        text = (_read_tesseract(data) if which == "tesseract"
                else _read_claude(data))
    except Exception as exc:                                # noqa: BLE001
        warn(f"[OCR] Read failed: {exc}")
        text = ""
    out = clean(text)
    if out or which != "tesseract" or not claude_available():
        return out
    # The free reader saw nothing worth keeping. Ask the paid one.
    try:
        second = clean(_read_claude(data))
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[OCR] Second look failed: {exc}")
        return ""
    if second:
        diagnostic(f"[OCR] Tesseract read nothing; Claude read "
                   f"{len(second)} characters.")
    return second


def read_url(url):
    return read(fetch(url))


def clean(text):
    """Tidy a transcript without changing what it says.

    Collapses the ragged blank lines OCR leaves between columns, drops
    lines that are pure punctuation noise, and returns "" when what is
    left is too short to be worth matching against.
    """
    if not text:
        return ""
    lines = []
    for raw in str(text).splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        # A line with no letters at all is border art, not writing.
        if not any(c.isalnum() for c in line):
            continue
        lines.append(line)
    out = "\n".join(lines).strip()
    return out if len(out) >= MIN_USEFUL_CHARS else ""
