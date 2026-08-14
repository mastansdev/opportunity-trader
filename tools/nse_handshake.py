"""
Find out what NSE is actually doing to us.

    py tools/nse_handshake.py

WHY THIS EXISTS
---------------
tools/index_members.py fails like this:

    [INDEX] nifty50 fetch failed (404 Client Error: Not Found for url:
    https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050)

A 404 is misleading. That endpoint exists -- it is what nseindia.com's
own Live Equity Market page calls. NSE returns 404 (not 401 or 403) to
requests it does not accept, which means the status code tells you
nothing about WHY it refused.

And there is no point guessing. There are at least five plausible
causes and they need different fixes:

  1. The cookie handshake silently failed. core/nse_quotes.py's
     requests_fetcher() calls session.get(HOME) inside a try block that
     only writes a diagnostic line and then carries on -- so a failed
     handshake looks exactly like a successful one, and the API call
     goes out with no cookies. Nothing in the logs distinguishes these.
  2. The homepage alone is no longer enough. NSE has at times required
     a hit on the referring market-data page before the API will answer.
  3. Missing sec-fetch-* / sec-ch-ua headers. A real Chrome sends them
     and NSE has used their absence as a bot signal.
  4. The index name encoding. "SECURITIES%20IN%20F%26O" carries an
     encoded ampersand; if anything in the stack decodes it, the query
     string breaks in two and the index parameter is lost.
  5. The endpoint or its parameters genuinely changed.

This script performs each step separately and prints what came back --
status, cookies, content type and the first bytes of the body. Whatever
is wrong will be visible rather than inferred, and the fix goes in
core/nse_quotes.py afterwards, chosen rather than guessed.

IT CHANGES NOTHING. Read only, no files written, no config touched.
"""

import sys

sys.path.insert(0, ".")

BASE = "https://www.nseindia.com"

# Real Chrome sends all of these. The current HEADERS in
# core/nse_quotes.py send the first four only.
FULL_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": BASE + "/market-data/live-equity-market",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Chromium";v="120", "Not:A-Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

CURRENT_HEADERS = {
    "User-Agent": FULL_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/market-data/live-equity-market",
}

# What a browser sends when it asks for an HTML PAGE, as opposed to an
# API call. Measured need, 30 July 2026: phase 1 showed the homepage
# returning 403 with no cookies while the market-data page returned 200.
# The difference was the headers -- the bot asks for the homepage while
# claiming Accept: application/json and a Referer from a page it has not
# visited yet. A browser opening nseindia.com sends neither. Akamai
# fronts this site (the _abck and bm_sz cookies are Bot Manager's) and a
# request that describes itself incoherently is exactly what it looks
# for.
PAGE_HEADERS = {
    "User-Agent": FULL_HEADERS["User-Agent"],
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": FULL_HEADERS["sec-ch-ua"],
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Connection": "keep-alive",
}

# NSE's own application cookies. Without these the /api/ calls return
# NSE's 382-byte "Resource not found" page regardless of the URL, which
# is why the 404 was so misleading.
APP_COOKIES = ("nsit", "nseappid")

# Endpoints probed to tell "we are blocked" apart from "this endpoint is
# gone". If a DIFFERENT endpoint answers with JSON on the same session,
# the session is fine and the problem is the URL. If every one returns
# the same 382-byte page, the session is the problem.
PROBES = (
    ("marketStatus   ", "/api/marketStatus"),
    ("allIndices     ", "/api/allIndices"),
    ("equity-meta    ", "/api/equity-meta-info?symbol=INFY"),
    ("stockIndices   ", "/api/equity-stockIndices?index=NIFTY%2050"),
)

# The two index_members.py wants, plus one from nse_quotes.py that has
# no ampersand -- so an encoding problem shows up as one working and
# the other not.
TARGETS = (
    ("nifty50  (no ampersand)", "NIFTY%2050"),
    ("fno      (encoded &)   ", "SECURITIES%20IN%20F%26O"),
    ("nifty500 (no ampersand)", "NIFTY%20500"),
)


def _show(label, response):
    body = (response.text or "")[:180].replace("\n", " ")
    print(f"      {label}")
    print(f"        status       {response.status_code}")
    print(f"        content-type {response.headers.get('Content-Type', '-')}")
    print(f"        length       {len(response.text or '')}")
    print(f"        body[:180]   {body!r}")


def phase_two(requests):
    """The browser-correct sequence, plus an endpoint-liveness probe.

    Phase 1 established that the homepage 403s and only Akamai's own
    cookies (_abck, bm_sz) come back -- never nsit or nseappid, which is
    what /api/ needs. Two hypotheses remain and they need different
    fixes, so both are tested rather than argued about:

      A. The handshake headers are wrong. Ask for HTML like a browser
         does and the homepage should return 200 and set nsit/nseappid.
      B. The endpoint changed. If a DIFFERENT /api/ path answers with
         JSON on the same session, the session is fine and the URL is
         the problem.
    """
    print("=" * 70)
    print("  PHASE 2 -- browser-correct sequence, then endpoint probe")
    print("=" * 70)

    session = requests.Session()

    print("  STEP 1  GET homepage with PAGE headers (Accept: text/html,")
    print("          no Referer -- what Chrome actually sends)")
    try:
        session.headers.clear()
        session.headers.update(PAGE_HEADERS)
        home = session.get(BASE + "/", timeout=20)
        cookies = list(session.cookies.keys())
        print(f"        status  {home.status_code}"
              f"{'   <-- was 403 with API headers' if home.status_code == 200 else ''}")
        print(f"        cookies {cookies or 'NONE'}")
        got_app = [c for c in APP_COOKIES if c in session.cookies]
        print(f"        NSE app cookies {got_app or 'NONE -- /api/ cannot work'}")
    except Exception as exc:                               # noqa: BLE001
        print(f"        FAILED  {type(exc).__name__}: {exc}")
        return

    print("  STEP 2  GET the live-equity-market page (same PAGE headers)")
    try:
        page = session.get(BASE + "/market-data/live-equity-market",
                           timeout=20)
        print(f"        status  {page.status_code}")
        print(f"        cookies {list(session.cookies.keys())}")
        got_app = [c for c in APP_COOKIES if c in session.cookies]
        print(f"        NSE app cookies {got_app or 'NONE'}")
    except Exception as exc:                               # noqa: BLE001
        print(f"        FAILED  {type(exc).__name__}: {exc}")

    print("  STEP 3  probe several /api/ endpoints with API headers")
    print("          (same session -- so a difference means the URL,")
    print("           and sameness means the session)")
    session.headers.clear()
    session.headers.update(FULL_HEADERS)
    for label, path in PROBES:
        url = BASE + path
        try:
            response = session.get(url, timeout=20)
            body = (response.text or "")[:100].replace("\n", " ")
            is_json = "json" in (response.headers.get("Content-Type") or "")
            verdict = "JSON -- THIS WORKS" if is_json else "not JSON"
            print(f"      {label} {response.status_code}  "
                  f"{len(response.text or ''):>6}b  {verdict}")
            print(f"                       {body!r}")
        except Exception as exc:                           # noqa: BLE001
            print(f"      {label} FAILED  {type(exc).__name__}: {exc}")
    print()
    print("  READ PHASE 2 LIKE THIS")
    print("    STEP 1 now 200 + nsit/nseappid   -> the handshake headers")
    print("                                        were the bug. Fix")
    print("                                        core/nse_quotes.py to")
    print("                                        send PAGE headers for")
    print("                                        pages and API headers")
    print("                                        only for /api/.")
    print("    STEP 1 still 403                 -> Akamai is blocking this")
    print("                                        IP or the TLS")
    print("                                        fingerprint, not the")
    print("                                        headers. requests cannot")
    print("                                        win this; use the")
    print("                                        browser or drop NSE.")
    print("    some probe returns JSON           -> the session is FINE and")
    print("                                        equity-stockIndices is")
    print("                                        the wrong URL now.")
    print("    every probe returns the 382b page -> the session is the")
    print("                                        problem, not the URL.")
    print()


ARCHIVE = "https://nsearchives.nseindia.com"

# NSE publishes index constituents as static CSVs. This is the SOURCE
# the API is a view onto, it takes no query parameter, and
# core/results_ingest.py already reaches this host successfully -- so it
# is known-good ground rather than another guess.
ARCHIVE_PROBES = (
    ("nifty50 list   ", ARCHIVE + "/content/indices/ind_nifty50list.csv"),
    ("nifty500 list  ", ARCHIVE + "/content/indices/ind_nifty500list.csv"),
    ("F&O lot sizes  ", ARCHIVE + "/content/fo/fo_mktlots.csv"),
)

# Encoding variants for the endpoint that 404s. Phase 2 showed every
# PARAMETERLESS endpoint answering and every PARAMETERISED one failing,
# so the parameter itself is the suspect.
PARAM_VARIANTS = (
    ("space as %20   ", "/api/equity-stockIndices?index=NIFTY%2050"),
    ("space as +     ", "/api/equity-stockIndices?index=NIFTY+50"),
    ("space literal  ", "/api/equity-stockIndices?index=NIFTY 50"),
    ("no space       ", "/api/equity-stockIndices?index=NIFTY"),
)


def phase_three(requests):
    """Where the membership lists should come from instead.

    Phase 2 settled two things. The session is FINE -- marketStatus and
    allIndices both returned JSON with no NSE application cookies at all,
    which also disproves the nsit/nseappid theory. And the failures are
    endpoint-specific in a very particular way: every endpoint WITHOUT a
    query parameter answered, every endpoint WITH one returned the same
    382-byte page.

    So this tests the two things that follow from that:

      1. The static archive CSVs. Index constituents are PUBLISHED files,
         not an API view. No parameter, no bot wall, and the same host
         core/results_ingest.py already uses. If these work, index
         membership should read them and the API can be abandoned.

      2. Whether the parameter encoding is the whole story, by asking
         for the same index four ways.
    """
    print("=" * 70)
    print("  PHASE 3 -- the static archive, and parameter encoding")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(PAGE_HEADERS)
    try:
        session.get(BASE + "/market-data/live-equity-market", timeout=20)
    except Exception as exc:                               # noqa: BLE001
        print(f"  handshake failed ({exc}) -- continuing anyway")

    print("  A. STATIC ARCHIVE CSVs (no query parameter, published files)")
    for label, url in ARCHIVE_PROBES:
        try:
            response = session.get(url, timeout=30)
            text = response.text or ""
            first = text.splitlines()[0][:88] if text.strip() else ""
            lines = len([ln for ln in text.splitlines() if ln.strip()])
            looks_csv = "," in first and response.status_code == 200
            print(f"      {label} {response.status_code}  "
                  f"{len(text):>7}b  {lines:>5} lines  "
                  f"{'CSV -- USABLE' if looks_csv else 'not CSV'}")
            if first:
                print(f"                       header: {first!r}")
        except Exception as exc:                           # noqa: BLE001
            print(f"      {label} FAILED  {type(exc).__name__}: {exc}")

    print()
    print("  B. THE SAME INDEX ASKED FOUR WAYS (API headers)")
    session.headers.clear()
    session.headers.update(FULL_HEADERS)
    for label, path in PARAM_VARIANTS:
        try:
            response = session.get(BASE + path, timeout=20)
            is_json = "json" in (response.headers.get("Content-Type") or "")
            print(f"      {label} {response.status_code}  "
                  f"{len(response.text or ''):>7}b  "
                  f"{'JSON -- THIS ONE WORKS' if is_json else 'not JSON'}")
        except Exception as exc:                           # noqa: BLE001
            print(f"      {label} FAILED  {type(exc).__name__}: {exc}")

    print()
    print("  READ PHASE 3 LIKE THIS")
    print("    archive CSVs return CSV   -> rewrite core/index_members.py to")
    print("                                 read them. No API, no bot wall,")
    print("                                 and it is NSE's own published")
    print("                                 file rather than a view on it.")
    print("    one variant returns JSON  -> the encoding was the bug all")
    print("                                 along; fix INDEX_URL only.")
    print("    all four still 404        -> equity-stockIndices is retired")
    print("                                 for this client. Use the")
    print("                                 archive.")
    print()


def main():
    try:
        import requests
    except ImportError:
        print("  requests is not installed. pip install requests")
        sys.exit(1)

    for header_name, headers in (("CURRENT headers (what the bot sends)",
                                  CURRENT_HEADERS),
                                 ("FULL headers (adds sec-fetch / sec-ch-ua)",
                                  FULL_HEADERS)):
        print("=" * 70)
        print(f"  {header_name}")
        print("=" * 70)

        session = requests.Session()
        session.headers.update(headers)

        # STEP 1 -- the handshake the bot does, but reported instead of
        # swallowed. This is the step whose failure is currently silent.
        print("  STEP 1  GET the homepage (for cookies)")
        try:
            home = session.get(BASE + "/", timeout=20)
            print(f"        status  {home.status_code}")
            cookies = list(session.cookies.keys())
            print(f"        cookies {cookies or 'NONE -- this is the problem'}")
        except Exception as exc:                           # noqa: BLE001
            print(f"        FAILED  {type(exc).__name__}: {exc}")
            print("        The handshake never happened. Every API call "
                  "below will fail for this reason alone.")

        # STEP 2 -- the referring page. Some NSE endpoints have needed a
        # visit here before they will answer.
        print("  STEP 2  GET the live-equity-market page")
        try:
            page = session.get(BASE + "/market-data/live-equity-market",
                               timeout=20)
            print(f"        status  {page.status_code}")
            print(f"        cookies {list(session.cookies.keys())}")
        except Exception as exc:                           # noqa: BLE001
            print(f"        FAILED  {type(exc).__name__}: {exc}")

        # STEP 3 -- the actual API calls.
        print("  STEP 3  the API calls")
        for label, index in TARGETS:
            url = f"{BASE}/api/equity-stockIndices?index={index}"
            try:
                response = session.get(url, timeout=20)
                _show(f"{label}  {url}", response)
                # What the URL became after the library normalised it.
                # If %26 was decoded, the index parameter is broken and
                # THAT is the bug, not NSE.
                if str(response.url) != url:
                    print(f"        URL WAS REWRITTEN to {response.url}")
                    print("        ^ if the ampersand was decoded, the "
                          "index parameter is being lost here.")
            except Exception as exc:                       # noqa: BLE001
                print(f"      {label}")
                print(f"        FAILED  {type(exc).__name__}: {exc}")
        print()

    phase_two(requests)
    phase_three(requests)

    print("=" * 70)
    print("  HOW TO READ THIS")
    print("=" * 70)
    print("  STEP 1 cookies NONE      -> the handshake is the problem. NSE")
    print("                              is unreachable or blocking the")
    print("                              first request; nothing else can")
    print("                              work until that is fixed.")
    print("  STEP 1 fine, STEP 3 404  -> cookies alone are not enough.")
    print("                              Compare the two header sets: if")
    print("                              FULL works and CURRENT does not,")
    print("                              the fix is HEADERS in")
    print("                              core/nse_quotes.py.")
    print("  nifty50 works, fno 404   -> an encoding problem, not a block.")
    print("                              Pass the index UNENCODED and let")
    print("                              requests encode it once.")
    print("  everything 404 in both   -> the endpoint or its parameters")
    print("                              changed. Open the Live Equity")
    print("                              Market page in Chrome, F12 ->")
    print("                              Network, and read the real call.")
    print("  200 but body is HTML     -> NSE served a challenge page, not")
    print("                              JSON. That is a bot block.")
    print()
    print("  NOTE: this is unrelated to the Dhan index/VIX feed. That is")
    print("  config.INDEX_INSTRUMENTS and the tick router in main.py.")
    print("  This script is only about NSE membership lists, which feed")
    print("  the pre-open NIFTY 50 / F&O buttons.")


if __name__ == "__main__":
    main()
