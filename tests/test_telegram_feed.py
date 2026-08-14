"""
Tests for core/telegram_feed.py.

    "separate screens for NSE; Trading; Telegram for continous
     updates. Now we will replace everything by our Dashboard."
    "Telegram channels - Day Trader Telugu , MoneyPurse,
     EARNINGS PULSE , ORDERBOOK PULSE"
                                    -- operator, 29 July 2026

TWO RULES, and the second one is the important one:

  1. Symbol matching is STRICT. A mentions panel that is wrong is
     worse than no panel -- he would stop believing the ones that are
     right.

  2. NOTHING here reaches the trading engine. These are anonymous
     third-party channels; the bot cannot tell a paid promotion from a
     genuine call, and the standing rule is that an entry needs a real
     reason. This is a reading panel and the tests hold it to that.
"""

from datetime import datetime, timedelta

import pytest

from core.telegram_feed import TelegramFeed


class _Master:
    def all_symbols(self):
        return ["KAYNES", "INFY", "PCBL", "TCS", "ITC", "IT", "ALL",
                "MANAPPURAM", "M&MFIN"]


class _Client:
    """Stands in for Telegram. The one method the feed calls."""

    def __init__(self, messages=None, fail=()):
        self.messages = messages or {}
        self.fail = set(fail)
        self.calls = []

    def fetch(self, channel, limit=30):
        self.calls.append(channel)
        if channel in self.fail:
            raise RuntimeError("channel unreachable")
        return self.messages.get(channel, [])


def _msg(id_, text, minutes_ago=5):
    return {"id": id_, "text": text,
            "at": datetime.now() - timedelta(minutes=minutes_ago)}


@pytest.fixture
def feed(tmp_path):
    return TelegramFeed(master_loader=_Master(),
                        db_path=str(tmp_path / "tg.db"),
                        channels=["MoneyPurse", "EARNINGS PULSE"])


# ---------------------------------------------------------------
# strict matching
# ---------------------------------------------------------------

def test_it_finds_the_stock_a_message_names(feed):
    assert feed.symbols_in("KAYNES looking strong above 3400") == ["KAYNES"]


def test_it_finds_several(feed):
    got = feed.symbols_in("Watch KAYNES and PCBL today, avoid INFY")
    assert got == ["KAYNES", "PCBL", "INFY"]


def test_english_words_that_happen_to_be_tickers_are_not_mentions(feed):
    """IT, ALL and ITC are real NSE symbols. Matching them would tag
    almost every message ever sent and make the panel useless."""
    assert feed.symbols_in("IT sector is strong, buy ALL dips in ITC") == []


def test_it_matches_whole_words_only(feed):
    assert feed.symbols_in("KAYNESX is not KAYNES") == ["KAYNES"]
    assert feed.symbols_in("XKAYNES") == []


def test_a_bare_ticker_must_be_written_in_capitals(feed):
    """CHANGED 30 July 2026, and this test used to assert the opposite.

    Matching was case-insensitive, and it produced three false links in
    one day on real data:

        "dollar"  -> DOLLAR    a textiles company, on a story about an
                               AI security breach
        "oil"     -> OIL       Oil India, on a US GDP story
        "Agi"     -> AGI       from garbled OCR of "& Agri"

    THE COST IS REAL: a human typing "kaynes breaking out" in lowercase
    is no longer matched by this path. It was accepted because on the
    four channels actually polled, tickers arrive as #TAGS or in
    capitals -- Earnings Pulse, OrderBook Pulse and News Pulse all write
    them that way, and Day Trader Telugu posts images. Not one true
    lowercase-only match was found in the 368 stored messages, against
    three false ones.

    The lowercase case is not lost either: names_in() matches a full
    company name whatever its capitalisation, which is what a human
    typing casually actually writes.
    """
    assert feed.symbols_in("KAYNES breaking out") == ["KAYNES"]
    assert feed.symbols_in("kaynes breaking out") == []


def test_a_hashtag_is_matched_whatever_its_case(feed):
    """Somebody typed the # on purpose. That is intent, not spelling."""
    assert feed.symbols_in("#KAYNES - Great Results") == ["KAYNES"]


def test_a_symbol_with_punctuation_in_it_still_matches(feed):
    assert "M&MFIN" in feed.symbols_in("M&MFIN results were good")


def test_a_message_naming_nothing_returns_nothing(feed):
    assert feed.symbols_in("market looks weak today") == []
    assert feed.symbols_in("") == []
    assert feed.symbols_in(None) == []


def test_with_no_master_it_claims_no_mentions_rather_than_guessing(tmp_path):
    feed = TelegramFeed(db_path=str(tmp_path / "tg.db"))
    assert feed.symbols_in("KAYNES up 5%") == []


# ---------------------------------------------------------------
# reading and storing
# ---------------------------------------------------------------

def test_messages_are_polled_and_come_back(feed):
    feed.client = _Client({"MoneyPurse": [_msg(1, "KAYNES up 5% today")]})
    assert feed.poll() == 1
    rows = feed.recent()
    assert rows[0]["channel"] == "MoneyPurse"
    assert rows[0]["symbols"] == ["KAYNES"]


def test_the_same_message_is_not_stored_twice(feed):
    feed.client = _Client({"MoneyPurse": [_msg(1, "KAYNES up")]})
    assert feed.poll() == 1
    assert feed.poll() == 0, "polling again duplicated a message"


def test_one_dead_channel_does_not_cost_the_others(feed):
    feed.client = _Client(
        {"MoneyPurse": [_msg(1, "KAYNES up")],
         "EARNINGS PULSE": [_msg(2, "PCBL results")]},
        fail=["MoneyPurse"])
    feed.poll()
    assert [r["symbols"] for r in feed.recent()] == [["PCBL"]]


def test_no_client_is_reported_not_crashed(feed):
    assert feed.poll() == 0
    assert "telegram_setup" in feed.snapshot()["note"] or \
           "telegram_setup" in (feed.snapshot()["error"] or "")


def test_empty_messages_are_skipped(feed):
    feed.client = _Client({"MoneyPurse": [
        {"id": 1, "text": "", "at": datetime.now()},
        {"id": 2, "text": "   ", "at": datetime.now()},
    ]})
    assert feed.poll() == 0


# ---------------------------------------------------------------
# what the card and the panel ask
# ---------------------------------------------------------------

def test_it_answers_what_was_said_about_one_stock(feed):
    feed.client = _Client({"MoneyPurse": [
        _msg(1, "KAYNES up 5%"), _msg(2, "PCBL is quiet")]})
    feed.poll()
    said = feed.for_symbol("KAYNES")
    assert len(said) == 1
    assert "KAYNES" in said[0]["text"]


def test_one_symbol_never_matches_inside_another(feed):
    """The stored form is comma-joined; a naive LIKE would match
    KAYNES inside a longer symbol's row."""
    feed.client = _Client({"MoneyPurse": [_msg(1, "MANAPPURAM and PCBL")]})
    feed.poll()
    assert feed.for_symbol("MAN") == []
    assert len(feed.for_symbol("MANAPPURAM")) == 1


def test_most_mentioned_counts_and_does_not_recommend(feed):
    feed.client = _Client({"MoneyPurse": [
        _msg(1, "KAYNES strong"), _msg(2, "KAYNES again"),
        _msg(3, "PCBL ok")]})
    feed.poll()
    loud = feed.most_mentioned()
    assert loud[0] == {"symbol": "KAYNES", "mentions": 2}
    # A count only -- no score, no rating, no verdict.
    assert set(loud[0]) == {"symbol", "mentions"}


def test_not_connected_and_quiet_are_different_states(feed):
    """"the channels said nothing" and "we cannot see Telegram" must
    never look the same on screen."""
    assert feed.snapshot()["connected"] is False
    feed.client = _Client({})
    snap = feed.snapshot()
    assert snap["connected"] is True
    assert snap["rows"] == []


def test_the_snapshot_says_out_loud_that_it_is_read_only(feed):
    assert "trading engine" in feed.snapshot()["note"]


# ---------------------------------------------------------------
# the line that must never be crossed
# ---------------------------------------------------------------

def test_nothing_in_this_module_can_reach_the_engine():
    """These are anonymous third-party channels. The bot cannot tell a
    paid promotion from a genuine call, and an entry needs a real
    reason -- a filing, results, a measured breakout. "A Telegram
    channel mentioned it" is not one."""
    import ast
    source = open("core/telegram_feed.py", encoding="utf-8").read()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    for banned in ("core.engine", "trading.execution", "trading.portfolio"):
        assert banned not in imported

    # The name check is a crude proxy for a real rule: NOTHING IN THIS
    # FILE MAY FORM AN OPINION. It collects messages and hands them on.
    #
    # 31 July 2026 it caught a method called _grade_new_events(), added
    # when the AI reader was wired in. That method did not grade
    # anything -- it asked core/ai_news.py and stored the answer -- but
    # the name said otherwise, and a name that says otherwise is how
    # the next person learns the wrong boundary. It was renamed to
    # _request_directions().
    #
    # If a word here ever needs deleting to make a test pass, that is
    # the signal to look at what the function does, not at the list.
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    for banned in ("score", "grade", "rank", "signal", "recommend", "buy"):
        assert not any(banned in name.lower() for name in defined), banned


# ---------------------------------------------------------------
# IT HAS TO KEEP READING
# ---------------------------------------------------------------
# Found live on 30 July 2026, hours into a session. main.py called
# telegram.poll() exactly ONCE during setup and never again:
# data/telegram.db was last written at 09:02:59 and the panel showed
# 08:59's messages for the rest of the day.
#
# That discarded the whole point of these channels. Earnings Pulse posts
# "#HEXT - OK Results - 13 seconds ago"; their value IS the freshness.
# Reading them once, before the open, is reading yesterday's news.
#
# The bug hid behind a success line: startup logged "14 new message(s)
# across 4 channels" and nothing ever said "that was the only time I
# looked."

def test_the_poller_runs_more_than_once(tmp_path):
    """The actual failure: one poll and then silence."""
    import time
    calls = []

    class _Counting:
        def fetch(self, channel, limit=30):
            calls.append(channel)
            return []

    feed = TelegramFeed(client=_Counting(), master_loader=_Master(),
                        db_path=str(tmp_path / "tg.db"),
                        channels=["A", "B"])
    feed.poll()
    first = len(calls)
    feed.start(every_seconds=0.05)
    try:
        deadline = time.time() + 2.0
        while len(calls) <= first and time.time() < deadline:
            time.sleep(0.02)
    finally:
        feed.stop()
    assert len(calls) > first, \
        "the feed polled once and stopped -- the 30 July bug"


def test_poller_alive_reports_honestly(tmp_path):
    """A reading panel that has silently stopped reading is worse than an
    empty one, so the dashboard must be able to say which it is."""
    feed = TelegramFeed(client=_Client(), master_loader=_Master(),
                        db_path=str(tmp_path / "tg.db"), channels=["A"])
    assert feed.poller_alive() is False
    feed.start(every_seconds=5)
    try:
        assert feed.poller_alive() is True
    finally:
        feed.stop()
    assert feed.poller_alive() is False


def test_start_is_idempotent(tmp_path):
    """Called twice must not leave two threads hammering t.me."""
    feed = TelegramFeed(client=_Client(), master_loader=_Master(),
                        db_path=str(tmp_path / "tg.db"), channels=["A"])
    feed.start(every_seconds=5)
    first = feed._thread
    feed.start(every_seconds=5)
    try:
        assert feed._thread is first, "started a second poller thread"
    finally:
        feed.stop()


def test_a_failing_poll_does_not_kill_the_loop(tmp_path):
    """One bad cycle must cost one cycle, not the rest of the day."""
    import time
    calls = []

    class _Exploding:
        def fetch(self, channel, limit=30):
            calls.append(channel)
            raise RuntimeError("t.me said no")

    feed = TelegramFeed(client=_Exploding(), master_loader=_Master(),
                        db_path=str(tmp_path / "tg.db"), channels=["A"])
    feed.start(every_seconds=0.05)
    try:
        deadline = time.time() + 2.0
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
    finally:
        feed.stop()
    assert len(calls) >= 2, "the loop died on the first failure"


def test_the_snapshot_says_whether_it_is_still_polling(tmp_path):
    feed = TelegramFeed(client=_Client(), master_loader=_Master(),
                        db_path=str(tmp_path / "tg.db"), channels=["A"])
    assert feed.poller_alive() is False
    feed.start(every_seconds=5)
    try:
        assert feed.poller_alive() is True
    finally:
        feed.stop()


# ---------------------------------------------------------------
# THE SYMBOL THE MESSAGE IS PLAINLY ABOUT
# ---------------------------------------------------------------
# 30 July 2026. The operator asked why four channels the bot polls all
# day were doing nothing:
#
#     "hey we have telegram channel called earnings pulse which will
#      post almost instant result & we are not utilising that at all"
#
# Part of the answer was a bug. 79 of 368 stored messages DISPLAYED a
# #TICKER and stored no symbol, so nothing downstream could find them --
# for_symbol() reads that column, and it is what the stock card and
# every per-stock lookup use.
#
#     #ACMESOLAR - Excellent Results     ->  symbols: (empty)
#     L&T secures mega order ... #LT     ->  symbols: (empty)

class _Loader:
    """A master loader that distinguishes tradeable from merely known --
    which is the distinction the bug collapsed."""

    def __init__(self, subscribed, blocked=()):
        self._subscribed = list(subscribed)
        self._blocked = list(blocked)

    def all_symbols(self, include_blocked=False):
        if include_blocked:
            return self._subscribed + self._blocked
        return list(self._subscribed)


def test_a_blocked_stock_is_still_recognised(tmp_path):
    """"May the bot trade this" and "does the bot know what this is" are
    different questions. all_symbols() answers the first by default, and
    reading it as the second lost 21 tickers -- including ACMESOLAR
    reporting excellent results."""
    from core.telegram_feed import TelegramFeed
    feed = TelegramFeed(master_loader=_Loader(["KAYNES"], ["ACMESOLAR"]),
                        db_path=str(tmp_path / "t.db"))
    assert "ACMESOLAR" in feed._known_symbols(), (
        "a stock the bot may not trade is still a stock it must recognise")
    assert "KAYNES" in feed._known_symbols()


def test_an_explicit_hashtag_beats_the_three_character_floor(tmp_path):
    """The floor stops a bare "LT" in prose tagging Larsen & Toubro, and
    it should. But "#LT" is somebody typing the company on purpose --
    and the floor was being applied to both paths, so
    "L&T secures mega order for 1,600 MW ... #LT" stored nothing."""
    from core.telegram_feed import TelegramFeed
    feed = TelegramFeed(master_loader=_Loader(["LT", "KAYNES"]),
                        db_path=str(tmp_path / "t.db"))
    assert "LT" in feed._known_symbols(hashtag=True)
    assert "LT" not in feed._known_symbols(), (
        "the floor must still apply to plain prose -- otherwise every "
        "'IT sector' line tags a company")


def test_the_two_sets_are_built_once_and_stay_consistent(tmp_path):
    from core.telegram_feed import TelegramFeed
    feed = TelegramFeed(master_loader=_Loader(["LT", "KAYNES"], ["ACMESOLAR"]),
                        db_path=str(tmp_path / "t.db"))
    tagged, plain = feed._known_symbols(hashtag=True), feed._known_symbols()
    assert plain <= tagged, "the prose set must be a subset of the tag set"
    assert feed._known_symbols(hashtag=True) is tagged, "not cached"


def test_a_loader_without_the_keyword_still_works(tmp_path):
    """An older MasterLoader has no include_blocked. Better the
    subscribed list than no symbols at all -- a chat feed must never be
    able to stop a trading session."""
    from core.telegram_feed import TelegramFeed

    class Old:
        def all_symbols(self):
            return ["KAYNES"]

    feed = TelegramFeed(master_loader=Old(), db_path=str(tmp_path / "t.db"))
    assert feed._known_symbols() == {"KAYNES"}


# ---------------------------------------------------------------
# A RESULTS CARD PRINTS A NAME, NOT A TICKER
# ---------------------------------------------------------------
# 30 July 2026. The first real OCR run read nine Earnings Pulse cards
# cleanly and matched almost nothing:
#
#     Aarti Industries   Data Pattern   Indegene   Nuvama Wealth
#
# symbols_in() looks for TICKERS. A card prints the COMPANY NAME. Five
# of those six are in the master under their full name, so the fix was
# not to weaken the ticker rule but to also look for what is actually
# printed.
#
# Getting there took three attempts, and the two failures are the tests
# below, because both were the SAME mistake made earlier that day with
# POINT and SOUTH: treating "rare in the master" as "is a name".

class _NamedLoader:
    def __init__(self, rows):
        self._rows = rows            # {SYMBOL: COMPANY NAME}

    def all_symbols(self, include_blocked=False):
        return list(self._rows)

    def get_by_symbol(self, symbol):
        return {"COMPANY NAME": self._rows.get(symbol)}


def _feed(rows, tmp_path):
    from core.telegram_feed import TelegramFeed
    return TelegramFeed(client=None, master_loader=_NamedLoader(rows),
                        db_path=str(tmp_path / "n.db"))


def test_a_company_named_in_full_is_found(tmp_path):
    feed = _feed({"AARTIIND": "AARTI INDUSTRIES LTD"}, tmp_path)
    assert feed.names_in("Gj Aarti Industries\nSpecialty Chemicals") == ["AARTIIND"]


def test_case_does_not_matter_for_a_full_name(tmp_path):
    """The ticker rule needs capitals so a lowercase "dollar" does not
    tag a textiles company. A NAME is two distinctive words together,
    which is its own safeguard."""
    feed = _feed({"NUVAMA": "NUVAMA WEALTH MANAGE LTD"}, tmp_path)
    assert feed.names_in("nuvama wealth reports weak quarter") == ["NUVAMA"]


def test_a_plural_either_side_still_matches(tmp_path):
    """OCR drops a trailing S about as often as the master carries one
    the card does not."""
    feed = _feed({"DATAPATTNS": "DATA PATTERNS INDIA LTD"}, tmp_path)
    assert feed.names_in("Data Pattern") == ["DATAPATTNS"]


def test_a_one_word_company_is_matched_on_that_word(tmp_path):
    feed = _feed({"INDGN": "INDEGENE LIMITED"}, tmp_path)
    assert feed.names_in("lal Indegene\nHealthcare Services") == ["INDGN"]


def test_a_rare_fragment_of_a_longer_name_is_not_a_name(tmp_path):
    """ATTEMPT TWO'S BUG. Any word belonging to exactly one company was
    treated as identifying it -- and the cards print a SECTOR line:

        "Healthcare Research, Analytics & Technology"  -> LATENTVIEW
        "Capital Markets | Stockbroking & Allied"      -> ABDL

    ANALYTICS and ALLIED are unique in the master, as FRAGMENTS of
    longer names. Rare is not the same as being a name -- exactly the
    POINT/SOUTH lesson from the same morning.
    """
    feed = _feed({"LATENTVIEW": "LATENT VIEW ANALYTICS LTD",
                  "ABDL": "ALLIED BLENDERS AND DISTILLERS LTD"}, tmp_path)
    assert feed.names_in("Healthcare Research, Analytics & Technology") == []
    assert feed.names_in("Capital Markets | Stockbroking & Allied") == []


def test_a_two_letter_first_word_does_not_make_a_generic_solo(tmp_path):
    """ATTEMPT THREE'S BUG. Filtering words under three characters
    turned "3M INDIA" into INDIA and "PI INDUSTRIES" into INDUSTRIES,
    so "Mallcom (India)" matched 3MINDIA and "Aarti Industries" also
    matched PIIND. A name is only a one-word name if the WHOLE name is
    one word."""
    feed = _feed({"3MINDIA": "3M INDIA LIMITED",
                  "PIIND": "PI INDUSTRIES LTD"}, tmp_path)
    assert feed.names_in("Mallcom (India) Industrial Products") == []
    assert feed.names_in("Aarti Industries | Specialty Chemicals") == []


def test_a_short_one_word_name_is_not_indexed(tmp_path):
    """Shorter than five characters is an abbreviation somebody else
    also uses."""
    feed = _feed({"ABC": "ABC LTD"}, tmp_path)
    assert feed.names_in("the abc of trading") == []


def test_no_master_means_no_names_not_a_crash(tmp_path):
    from core.telegram_feed import TelegramFeed
    feed = TelegramFeed(client=None, db_path=str(tmp_path / "n.db"))
    assert feed.names_in("Aarti Industries") == []


def test_the_poller_uses_both_matchers_on_a_transcript():
    src = open("core/telegram_feed.py", encoding="utf-8").read()
    block = src[src.find("ocr = self._read_photo"):]
    assert "self.symbols_in(ocr) + self.names_in(ocr)" in block[:400], (
        "a card prints 'Aarti Industries', not '#AARTIIND' -- both "
        "matchers have to run on it")
