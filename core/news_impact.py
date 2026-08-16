"""
==========================================================
News -> which stocks it helps, which it hurts
==========================================================

    "every news will be connected to their respective stocks in memory
     brain and the same thing will be displayed upon demand. for
     example if by seeing the news item of this ABS braking. i need the
     info of which stocks are going to impact both + & -ve way"
                                    -- operator, 30 July 2026

    "i'm not asking that bot will trade by this news. for now we will
     build the system."

THE PROBLEM THIS SOLVES
-----------------------
On 29 July a story about MoRTH softening the mandatory-ABS rule moved
Bosch. The bot had no idea, for two separate reasons:

  1. BOSCHLTD was not in the universe at all (Rs 41,250, above the old
     Rs 10,000 ceiling -- removed 29 July, back on the next rebuild).

  2. Even subscribed, core/news_watcher.py only matches a story to a
     company that FILED it. A regulation story is nobody's filing. The
     link from "ABS braking rule" to Bosch runs through what Bosch
     DOES, and that is sitting unused in data/master_stocks.csv:

         BOSCHLTD   SECTOR   AUTOMOBILE
                    THEMES   AUTO ANCILLARY | AUTO COMPONENTS
                    BUSINESS MANUFACTURES AUTOMOTIVE COMPONENTS

WHY A KEYWORD MATCH IS NOT ENOUGH
---------------------------------
The operator's own example is the proof. One sentence, opposite signs:

    softening mandatory ABS-for-all-2W
        Hero, Bajaj, TVS, Eicher   POSITIVE  (a cost they now avoid)
        Bosch, Endurance, ABS makers NEGATIVE (demand they now lose)

Every one of those is "AUTOMOBILE". A theme match returns all eight
with no sign at all, which is the least useful possible answer. Naming
who gains and who loses needs actual reasoning about who pays and who
supplies, so that step goes to the model that already exists in this
project (core/morning_brief.py, claude-sonnet-5).

THE RULES THIS IS HELD TO
-------------------------
  1. NOTHING HERE REACHES THE TRADING ENGINE. The operator was
     explicit -- "i'm not asking that bot will trade by this news".
     No import of core.engine, enforced by a test.

  2. THE MODEL MAY ONLY CHOOSE FROM SYMBOLS WE ACTUALLY HAVE. It is
     handed a shortlist built from the master file and must pick from
     it. It cannot invent a ticker, and anything not in the master is
     dropped before storage.

  3. NO KEY, NO GUESSING. Without ANTHROPIC_API_KEY the candidates are
     still found and stored with direction UNKNOWN and the matched
     keyword as the reason. A missing direction is honest; a made-up
     one is not.

  4. EVERY ROW CARRIES ITS REASON. "BOSCHLTD negative -- makes ABS
     units, loses mandated demand" can be judged in one glance.
     A bare "-1" cannot.

Author : H&M Opportunity Trader
==========================================================
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn

DB_PATH = os.path.join("data", "news_memory.db")
MODEL = "claude-sonnet-5"
TIMEOUT_SECONDS = 30

POSITIVE, NEGATIVE, UNKNOWN = "POSITIVE", "NEGATIVE", "UNKNOWN"

# What a story is ABOUT, which is a different question from what it
# does to a price. STOCK = it names companies or a line of business.
# MACRO = it names neither, so it belongs to the market and gets no
# impact rows at all. See candidates() for why this distinction had to
# be made explicit.
STOCK, MACRO = "STOCK", "MACRO"

# WHAT KIND OF STATEMENT this is, which is a third question again --
# separate from what it is about (scope) and what it does to a price
# (direction). Added 30 July 2026 after tools/telegram_check.py showed
# what News Pulse actually posts.
#
#   NEWS  something happened. An order was won, results were filed, a
#         regulator proposed a rule.
#   TIP   somebody thinks you should buy something. "Sumeet Bagadia
#         recommends buying Gland Pharma, PG Electroplast", "Analysts
#         recommend mid-cap stocks with 'Strong Buy'".
#
# The distinction is not cosmetic and it is not about accuracy. The
# matcher identifies GLAND and PGEL in that sentence CORRECTLY and with
# high confidence -- which is exactly what makes an unlabelled tip more
# dangerous than a mismatched one. Stored as "news", a stranger's buy
# call becomes indistinguishable from a filing, and any future step that
# reads this table for conviction would treat it as evidence.
#
# Labelled, it can be read and can never be promoted.
NEWS, TIP = "NEWS", "TIP"

# An explicit recommendation marker. Deliberately narrow -- these must
# be phrases that CANNOT appear in a factual report of an event. "Sees
# revenue growth" is a company guiding; "buy with target 450" is
# somebody advising. Only the second kind belongs here.
_TIP_MARKERS = (
    r"stock pick", r"brokerage call", r"\bstrong buy\b", r"\bstrong sell\b",
    r"\brecommends?\s+(?:buying|selling|to\s+buy|to\s+sell)\b",
    r"\bbuy\s+(?:call|recommendation)\b", r"\btop\s+picks?\b",
    r"\bbuy\b[^.\n]{0,40}\btarget\b", r"\btarget\s+price\b",
    r"\baccumulate\b", r"\badd\s+on\s+dips\b", r"\bbook\s+profits?\b",
    r"\bintraday\s+(?:pick|call|tip)s?\b", r"\bmulti[- ]?bagger\b",
)


def looks_like_a_tip(text):
    """True if this is somebody's recommendation rather than a report of
    an event. See NEWS / TIP above for why it must be marked."""
    lowered = str(text or "").lower()
    return any(re.search(p, lowered) for p in _TIP_MARKERS)


def is_not_a_story(headline, body=""):
    """True for a post that carries no statement at all, and so has
    nothing to be stored about.

    Measured on the live database, 30 July 2026:

      SECTION HEADERS -- News Pulse posts its own dividers as messages.
      "STOCK PICK", "FII / DII FLOWS", "INDIA MACRO & STRATEGY",
      "EARNINGS & RESULTS". Four of the 63 stored stories were these.

      BARE LINKS -- Day Trader Telugu posts a YouTube URL and nothing
      else. Three of the 63. There is no headline, no body and nothing
      to reason about, but each still occupied a row and appeared on the
      panel as an empty story.

    Both are noise with a story's shape, and neither can ever produce a
    useful link. Refusing them at the door is cheaper than filtering
    them at every read.
    """
    text = f"{headline or ''} {body or ''}"
    # Strip emoji/symbols and URLs, then see whether any prose is left.
    words = [w for w in re.split(r"\s+", text) if w and not w.startswith("http")]
    words = [w for w in words if re.search(r"[A-Za-z]{2,}", w)]
    if len(words) <= 2:
        return True
    # A header is a short, wholly-uppercase label with no sentence in it.
    stripped = re.sub(r"[^A-Za-z&/ ]", "", str(headline or "")).strip()
    if stripped and len(stripped.split()) <= 5 and stripped.isupper() \
            and not (body or "").strip():
        return True
    return False

# Words too common to mean anything on their own. Matching "INDIA" or
# "LIMITED" would shortlist the whole universe.
STOPWORDS = {
    "INDIA", "INDIAN", "LIMITED", "LTD", "THE", "AND", "FOR", "WITH",
    "FROM", "THIS", "THAT", "WILL", "MAY", "NEW", "OTHER", "OTHERS",
    "COMPANY", "COMPANIES", "SHARE", "SHARES", "STOCK", "STOCKS",
    "MARKET", "MARKETS", "CRORE", "LAKH", "RUPEE", "SECTOR", "GROUP",
    "SERVICES", "PRODUCTS", "MANUFACTURES", "MANUFACTURING", "GENERAL",
    # Ordinary English adjectives. These are dangerous in a way the
    # words above are not: a common adjective can appear in exactly ONE
    # company's description, which makes the rarity test in
    # _is_name_word() treat it as that company's NAME.
    #
    #   "Coforge anticipates a strong Q2 on LARGE deal wins"
    #       -> WELCORP, whose row reads "LARGE DIAMETER STEEL PIPES"
    #
    # LARGE belongs to one company, so it looked like an identifier.
    # It is not. Rarity means a word is distinctive only if the word
    # itself carries meaning; these do not.
    "LARGE", "SMALL", "GREAT", "STRONG", "WEAK", "BEST", "BETTER",
    "GOOD", "MAJOR", "MINOR", "HIGH", "LOW", "BIG", "LONG", "SHORT",
    "FIRST", "LATEST", "FULL", "MAIN", "TOTAL",
    # Generic BUSINESS nouns. Measured on the live database, 30 July 2026.
    # A News Pulse digest carrying a supply-chain paragraph produced:
    #
    #   BLACKBUCK  matched on: TECH, CHAIN, PLATFORM, SUPPLY
    #   DELHIVERY  matched on: CHAIN, SUPPLY, PLATFORM
    #   PDSL       matched on: CHAIN, SUPPLY, BRAND
    #   BBTC       matched on: TRADING, AUTO, INDUSTRY
    #
    # Not one of those companies was in the story. These words sit in
    # hundreds of CORE BUSINESS and THEMES cells and appear in any prose
    # about commerce, so they carry no evidence in either direction --
    # the same reason INDIA and LIMITED are above.
    "CHAIN", "SUPPLY", "PLATFORM", "BRAND", "BRANDS", "TRADING",
    "INDUSTRY", "INDUSTRIES", "INDUSTRIAL", "INVESTMENT", "INVESTMENTS",
    # NOT "SYSTEM"/"SYSTEMS". Tried on 30 July and reverted the same
    # minute: ASK Automotive's whole business is "BRAKING SYSTEMS", and
    # stopwording it dropped ASKAUTOLTD from the MoRTH ABS story -- the
    # operator's own worked example. "braking" appears lowercase
    # mid-sentence there, so it is not treated as a name and the pair is
    # the only thing carrying the match. A generic word is still evidence
    # when it is half of a specific phrase.
    "TECH", "TECHNOLOGY", "TECHNOLOGIES", "SOLUTION", "SOLUTIONS",
    "GLOBAL", "INTERNATIONAL", "NATIONAL", "ENTERPRISE",
    "ENTERPRISES", "HOLDING", "HOLDINGS", "CAPITAL", "FINANCE",
    "FINANCIAL", "DIGITAL", "RETAIL", "CONSUMER", "BUSINESS",
    "DEVELOPMENT", "PROJECT", "PROJECTS", "EQUIPMENT", "MATERIALS",
}


def _stem(word):
    """Crudest possible singular form.

    "Two wheeler makers" against a master row saying TWO WHEELERS
    matched only TWO and WHEELER -- one hit short of the threshold --
    so HEROMOTOCO, BAJAJ-AUTO and TVSMOTOR were all dropped from the
    ABS story while ENDURANCE survived. Losing the biggest names in a
    story because of one letter is not a threshold problem, it is a
    matching problem.
    """
    if len(word) > 4 and word.endswith("IES"):
        return word[:-3] + "Y"
    if len(word) > 3 and word.endswith("SES"):
        return word[:-2]
    if len(word) > 3 and word.endswith("S") and not word.endswith("SS"):
        return word[:-1]
    return word


def _words(text):
    return {_stem(w)
            for w in re.findall(r"[A-Za-z][A-Za-z&\-]{2,}", str(text or "").upper())
            if w not in STOPWORDS}


_TOKEN = re.compile(r"#?[A-Za-z][A-Za-z&\-]{2,}")
_SENTENCE_END = re.compile(r"[.!?:\n]\s*$")


def _proper_nouns(text):
    """The words in a story that are being used as NAMES.

    WHY CASE MATTERS -- the second bug found on 30 July 2026, after the
    taxonomy columns were already fixed. Once matching was restricted to
    identity columns, a new kind of false positive appeared:

        "...focuses strictly on current facts..."   -> FACT LTD
        "...does not have a flexible..."            -> EPL (FLEXIBLE PACKAGING)
        "...path..."                                -> DR. LAL PATH LABS
        "...soft..."                                -> ORACLE FIN SERV SOFT LTD

    Every one is an ordinary English word that happens to sit inside one
    company's registered name. Rarity cannot tell them apart: FACT is
    rare in a list of 750 Indian companies and completely unremarkable
    in English.

    Capitalisation can. "facts" in running prose is a common noun;
    "#KAYNES", "Coforge" and "Dalmia Bharat" are proper nouns. _words()
    uppercases everything and throws that signal away, so this keeps it.

    A token counts as a name if it is hashtagged, ALL CAPS, or
    capitalised somewhere other than the start of a sentence -- the
    sentence-initial exclusion is why "Flexible packaging demand rose"
    does not tag EPL.
    """
    raw = str(text or "")
    if not raw.strip():
        return set()
    # A headline written entirely in capitals carries no case signal at
    # all. Returning everything would be worse than returning nothing:
    # it would restore exactly the behaviour this function prevents.
    letters = [c for c in raw if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return set()

    found = set()
    for match in _TOKEN.finditer(raw):
        token = match.group(0)
        word = token.lstrip("#")
        if not word[:1].isupper():
            continue
        hashtagged = token.startswith("#")
        if not hashtagged:
            before = raw[:match.start()]
            # Skip a capital that is there only because a new sentence
            # started -- that is how "Flexible packaging demand rose"
            # would otherwise tag EPL.
            #
            # The FIRST token of the whole text is deliberately NOT
            # skipped. A headline leads with its subject: "Coforge
            # anticipates a strong Q2", "Dalmia Bharat subsidiary
            # acquires...". Excluding position zero threw away the
            # single most reliable name in every story.
            if before.strip() and _SENTENCE_END.search(before):
                continue
        upper = word.upper()
        if upper in STOPWORDS:
            continue
        found.add(_stem(upper))
    return found


class NewsImpact:
    """Connects one news item to the stocks it helps and hurts.

    Read-only with respect to trading. Fail-quiet: no key, no network
    or a bad answer costs the panel, never the session.
    """

    def __init__(self, master_loader=None, db_path=DB_PATH, client=None,
                 model=MODEL, budget=None):
        self.master_loader = master_loader
        self.db_path = db_path
        self.model = model
        self._client = client
        self._client_tried = client is not None
        # Every paid call goes through one meter. Injectable so a test
        # can hand in a tmp_path ledger and never touch data/ai_spend.db.
        if budget is None:
            from core.ai_budget import AiBudget
            budget = AiBudget()
        self._budget = budget
        self._lock = threading.Lock()
        self._profiles = None
        self._identity_owners = None
        self._ensure()

    # ------------------------------------------------------------

    def _ensure(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS news ("
                " news_id TEXT PRIMARY KEY, at TEXT, seen_at TEXT,"
                " source TEXT, headline TEXT, body TEXT, url TEXT,"
                " reasoned INTEGER DEFAULT 0, scope TEXT DEFAULT 'STOCK',"
                " kind TEXT DEFAULT 'NEWS')")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS impact ("
                " news_id TEXT, symbol TEXT, direction TEXT,"
                " reason TEXT, confidence REAL, how TEXT,"
                " PRIMARY KEY (news_id, symbol))")
            conn.execute("CREATE INDEX IF NOT EXISTS impact_symbol "
                         "ON impact (symbol)")
            conn.commit()
            self._migrate(conn)
            conn.close()
        except (sqlite3.Error, OSError) as exc:
            warn(f"[IMPACT] Could not open {self.db_path}: {exc}")

    # Columns added after this table first shipped. CREATE TABLE IF NOT
    # EXISTS does NOTHING to a table that already exists, so a new
    # column here without a matching ALTER means every INSERT fails
    # forever. That is not hypothetical -- it is exactly what silenced
    # the Telegram messages table for months (core/telegram_feed.py's
    # _migrate). Any column added below must be added here too.
    _EXTRA_NEWS_COLUMNS = (
        ("scope", "TEXT DEFAULT 'STOCK'"),
        ("kind", "TEXT DEFAULT 'NEWS'"),
    )

    def _migrate(self, conn):
        try:
            have = {row[1] for row in
                    conn.execute("PRAGMA table_info(news)")}
        except sqlite3.Error as exc:
            warn(f"[IMPACT] Could not read the news schema: {exc}")
            return
        if not have:
            return
        added = []
        for column, coltype in self._EXTRA_NEWS_COLUMNS:
            if column in have:
                continue
            try:
                conn.execute(f"ALTER TABLE news ADD COLUMN "
                             f"{column} {coltype}")
                added.append(column)
            except sqlite3.Error as exc:
                warn(f"[IMPACT] Could not add column {column}: {exc}")
        if added:
            conn.commit()
            decision(f"[IMPACT] Schema migrated -- added: "
                     f"{', '.join(added)}.")

    # ------------------------------------------------------------
    # step 1 -- who could this possibly be about
    # ------------------------------------------------------------

    # Which master-file columns may IDENTIFY a story's subject, and
    # what a hit in each is worth. This split is the whole fix; see
    # candidates() for what it repaired.
    #
    #   IDENTITY  the company itself. A hit here means the story names
    #             this business. COMPANY NAME and KEYWORDS are the only
    #             columns in the master that are about one company.
    #   BUSINESS  what it does. A hit means the story is about this
    #             line of work -- good evidence, not proof.
    #   TAXONOMY  which bucket it was filed under. A fixed vocabulary of
    #             six to eight values shared by hundreds of stocks. NOT
    #             searched at all (see TAXONOMY_COLUMNS).
    IDENTITY_COLUMNS = ("COMPANY NAME", "KEYWORDS")
    BUSINESS_COLUMNS = ("CORE BUSINESS", "INDUSTRY", "THEMES")
    # Kept for the model's description string, never used as needles.
    TAXONOMY_COLUMNS = ("SECTOR", "BUSINESS_TYPE", "ECONOMIC_SENSITIVITY",
                        "COMMODITY_EXPOSURE")

    IDENTITY_WEIGHT = 3
    BUSINESS_WEIGHT = 2
    # A word that belongs to exactly ONE company in the master is that
    # company's NAME, and a story using it is talking about them. This
    # is measured off the master file, not declared:
    #
    #     BRAKING    1 stock     KAYNE    1 stock     FEDERAL  1 stock
    #     THREE      2 stocks    WHEELER  5 stocks    SYSTEM  14 stocks
    #     AUTO      23 stocks    BANK    34 stocks    ESTATE  20 stocks
    #
    # Without this, no single threshold works. Earnings Pulse posts
    # "#KAYNES - Great Results" -- one identity word and nothing else --
    # which is the most valuable message the feed carries. Any cutoff
    # high enough to reject "three members voted" (THREE, shared by the
    # three-wheeler makers) also rejects that. Rarity separates them.
    UNIQUE_OWNER_LIMIT = 1

    # ------------------------------------------------------------
    # A SINGLE NAME WORD IS NOT ALWAYS A NAME -- 30 July 2026
    # ------------------------------------------------------------
    # Rarity in the MASTER FILE is not the same as rarity in ENGLISH,
    # and the `named` bypass above only tested the first. Measured over
    # the 457 links then in the store, 63% were generic word matches,
    # and the worst of them all came in through this door:
    #
    #     CAPLIPOINT <- "Career Point wins Rs 17.6cr contract"  [POINT]
    #     SOUTHBANK  <- "CODI deposit insurance, South..."      [SOUTH]
    #
    # POINT belongs to exactly one company in the master, and it is a
    # proper noun in "Career Point", so every test passed. The story is
    # about a different company entirely.
    #
    # The bypass has to stay -- Earnings Pulse posts "#KAYNES - Great
    # Results", one identity word and nothing else, and that is the most
    # valuable message the feed carries. So the rule is not "two words";
    # it is that a LONE name word must be the company's own handle:
    #
    #     KAYNES   == KAYNES        the ticker itself           KEEP
    #     ADFFOOD  -> ADFFOODS      a distinctive prefix of it  KEEP
    #     POINT    -> CAPLIPOINT    not a prefix                DROP
    #     SOUTH    -> SOUTHBANK     a prefix, but a common word DROP
    #     NLC      -> NLCINDIA      a prefix, but only 3 chars  DROP
    #
    # NLC is a real loss -- NLC India was the customer in that order
    # story. Three-letter tokens are exactly what generates false links,
    # so it goes with the rest, and KEYWORDS is where a genuine alias
    # belongs (see the KEYWORDS task).
    LONE_NAME_MIN_PREFIX = 4
    # Common words that happen to be unique in the master. Rarity across
    # 973 companies says nothing about rarity in a news headline.
    LONE_NAME_STOPS = {
        "SOUTH", "NORTH", "EAST", "WEST", "CENTRAL", "GLOBAL", "NATIONAL",
        "UNITED", "GENERAL", "UNION", "FIRST", "PRIME", "SUPREME", "APEX",
        "SUMMIT", "PIONEER", "MODERN", "ROYAL", "CROWN", "ORIENT", "STAR",
        "POINT", "GRAND", "PREMIER", "SUPER", "MASTER", "EXPRESS", "CAPITAL",
    }

    def _is_lone_name(self, symbol, word):
        """Is this ONE word enough to say the story is about `symbol`?

        Only if it is the company's own handle -- the ticker, or a
        distinctive prefix of it. Everything else needs corroboration
        from a second identity word or from the business score.
        """
        word = (word or "").upper()
        symbol = (symbol or "").upper()
        if word == symbol:
            return True
        if word in self.LONE_NAME_STOPS:
            return False
        return (len(word) >= self.LONE_NAME_MIN_PREFIX
                and symbol.startswith(word))

    def _stock_profiles(self):
        """{SYMBOL: (identity words, business words, description)} for
        the whole master. Built once."""
        if self._profiles is not None:
            return self._profiles
        profiles = {}
        if self.master_loader is not None:
            try:
                for symbol in self.master_loader.all_symbols(
                        include_blocked=True):
                    row = self.master_loader.get_by_symbol(symbol) or {}
                    identity = _words(" ".join(
                        str(row.get(f) or "") for f in self.IDENTITY_COLUMNS))
                    # The ticker itself is an identity word. "#KAYNES"
                    # and "Kaynes Technology" must both match.
                    identity |= _words(symbol)
                    business = _words(" ".join(
                        str(row.get(f) or "") for f in self.BUSINESS_COLUMNS))
                    business -= identity        # never counted twice
                    profiles[symbol.upper()] = (
                        identity, business,
                        f"{row.get('COMPANY NAME') or symbol} -- "
                        f"{row.get('CORE BUSINESS') or row.get('SECTOR') or ''}"
                        f" [{row.get('THEMES') or ''}]",
                    )
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[IMPACT] master read failed: {exc}")
        self._profiles = profiles
        # How many companies each identity word belongs to. Built here
        # because it is a property of the whole master, not of one row.
        counts = {}
        for identity, _biz, _desc in profiles.values():
            for word in identity:
                counts[word] = counts.get(word, 0) + 1
        self._identity_owners = counts
        return profiles

    def _is_name_word(self, word):
        """True if this word belongs to exactly one company -- i.e. it
        is a name, not a category."""
        if self._identity_owners is None:
            self._stock_profiles()
        return (self._identity_owners or {}).get(word, 99) \
            <= self.UNIQUE_OWNER_LIMIT

    def candidates(self, text, limit=25, min_score=6):
        """Stocks this story could plausibly be about, and why.

        WHAT WAS WRONG BEFORE (fixed 2026-07-30)
        ----------------------------------------
        Every master column was poured into one flat bag of words and
        any two shared words qualified. That included
        ECONOMIC_SENSITIVITY, whose entire vocabulary is six values:

            CONSUMER DRIVEN, GOVERNMENT SPENDING, EXPORT ORIENTED,
            INTEREST RATE SENSITIVE, IMPORT DEPENDENT, NONE

        105 stocks carry INTEREST RATE SENSITIVE. So a US macro
        headline --

            "Federal Reserve holds interest rates steady"

        -- shared INTEREST and RATE with all 105 of them and was stored
        against DBREALTY, CGCL, BRIGADE, ARVSMART, ANANTRAJ and AGIIL
        with the reason "matched on: INTEREST, RATE, REAL". Not one of
        those companies was in the story. A single macro line produced a
        large share of the 166 links then in the database, every one of
        them direction UNKNOWN.

        Worse, KEYWORDS -- the one column in master_database.xlsx that
        exists to be matched against -- was not in the blob at all. The
        matcher read the classification field as if it identified a
        company, and ignored the field that does.

        THE RULE NOW
        ------------
        A story must share a word with a company's IDENTITY or its
        BUSINESS to be about that company. Taxonomy columns describe
        which macro bucket a stock sits in; belonging to a bucket the
        news mentions is not the same as being in the news. So they
        cannot create a candidate -- they only survive in the
        description handed to the model.

        `min_score` is 6 because the weights make that meaningful: two
        identity words, or one identity plus one business, or three
        business words. A SINGLE shared category word scores 3 and is
        rejected -- that is what dropped ATUL from the ABS story (it
        shares only "PERFORMANCE") and APOLLO (only "SYSTEM"). A story
        that uses a company's NAME bypasses the threshold entirely.

        Returns [] for a story that names nobody, which is the honest
        answer for macro news. See remember() for how that is stored.
        """
        needles = _words(text)
        if not needles:
            return []
        # Words the story uses as NAMES, not merely as words. A rare
        # word only identifies a company if it is also being used as a
        # proper noun -- see _proper_nouns().
        names = _proper_nouns(text)
        self._stock_profiles()          # ensures owner counts exist
        scored = []
        for symbol, (identity, business, _desc) in \
                self._stock_profiles().items():
            id_hits = needles & identity
            biz_hits = needles & business
            if not id_hits and not biz_hits:
                continue
            named = sorted(w for w in id_hits
                           if w in names and self._is_name_word(w))
            score = (len(id_hits) * self.IDENTITY_WEIGHT
                     + len(biz_hits) * self.BUSINESS_WEIGHT)
            # Either the story uses this company's NAME, or it shares
            # enough with what they do. One shared category word is
            # never enough on its own.
            #
            # And ONE name word only counts when it is the company's own
            # handle -- see _is_lone_name(). Two or more name words
            # corroborate each other ("SOUTH INDIAN BANK"), so they are
            # taken at face value.
            strong_name = bool(named) and (
                len(named) > 1 or self._is_lone_name(symbol, named[0]))
            if not strong_name and score < min_score:
                continue
            scored.append((score + (self.IDENTITY_WEIGHT if strong_name else 0),
                           symbol, sorted(id_hits) + sorted(biz_hits),
                           len(id_hits), named))
        # A story that NAMES the company outranks one that merely shares
        # its line of business, whatever the raw word count says.
        scored.sort(key=lambda x: (-(1 if x[4] else 0), -x[0], -x[3], x[1]))
        return [{"symbol": s, "hits": h, "score": n, "identity_hits": i,
                 "named_by": nm} for n, s, h, i, nm in scored[:limit]]

    # ------------------------------------------------------------
    # step 2 -- who gains and who loses
    # ------------------------------------------------------------

    def _get_client(self):
        if not self._client_tried:
            self._client_tried = True
            # ---- THE MASTER SWITCH. 10 August 2026. ----
            # config.AI_ENABLED says "Nothing calls out while
            # False". Three modules built a client without asking,
            # so on 10 August every call went out and came back
            # "credit balance is too low" -- silently, as DEBUG
            # lines, all afternoon.
            try:
                from config import AI_ENABLED
            except Exception:                              # noqa: BLE001
                AI_ENABLED = False
            if not AI_ENABLED:
                return None
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                warn("[IMPACT] No ANTHROPIC_API_KEY -- news will be linked "
                     "to stocks by keyword only, with NO direction. "
                     "Winners and losers need the reasoning step.")
                return None
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=key, timeout=TIMEOUT_SECONDS)
            except Exception as exc:                       # noqa: BLE001
                warn(f"[IMPACT] Anthropic client unavailable ({exc}).")
        return self._client

    PROMPT = """You are helping an Indian equity trader understand news.

NEWS:
{headline}
{body}

These are the ONLY companies you may name. Each line is
SYMBOL -- what the company does:

{candidates}

For each company that this news genuinely affects, say whether the
effect is POSITIVE or NEGATIVE for its share price, and why, in one
short sentence naming the mechanism.

Rules:
- Use ONLY symbols from the list above. Never invent one.
- Leave out any company the news does not really touch. Most of the
  list usually does not belong in the answer.
- The same news is often POSITIVE for one group and NEGATIVE for
  another. A rule that forces buying a part helps the part maker and
  hurts the manufacturer who must fit it; relaxing that rule reverses
  both.
- confidence is 0.0 to 1.0, your honest confidence in the direction.

Reply with JSON only, no other text:
{{"impacts": [
  {{"symbol": "XXX", "direction": "POSITIVE", "confidence": 0.8,
    "reason": "one short sentence"}}
]}}"""

    def _reason(self, headline, body, candidates):
        client = self._get_client()
        if client is None or not candidates:
            return None
        profiles = self._stock_profiles()
        listing = "\n".join(
            # [2] is the description. It was [1] until the profile tuple
            # grew a third field for tiered matching; getting this index
            # wrong feeds the model a Python set instead of a business
            # description, so it is named rather than counted.
            f"{c['symbol']} -- {profiles.get(c['symbol'], (set(), set(), ''))[2]}"
            for c in candidates)
        # ---- IT SPENT WITHOUT RECORDING, AND WITHOUT A CAP ----
        #
        #     "last time 5$ were used within no time but that time u
        #      claimed it will last atleast 60-90 days as per the
        #      usage. but 5$ completed within 5 days."
        #                             -- operator, 16 August 2026
        #
        # data/ai_spend.db holds 1,892 rows for 31 Jul - 5 Aug totalling
        # $1.4321, and the arithmetic checks out exactly against Haiku
        # 4.5's published rates. It reported TWO purposes: news_direction
        # and ai_check.
        #
        # This call was never one of them. Five modules reach
        # messages.create() and only three recorded anything or asked
        # may_call() first -- so the ledger under-reported BY
        # CONSTRUCTION and the Rs 2,500 monthly cap could not bind on
        # the calls it did not know about.
        #
        # This one is the expensive shape: max_tokens=1200 against
        # news_direction's 200, with 1,500 characters of body in the
        # prompt where that one sends a 600-character headline.
        allowed, why = self._budget.may_call()
        if not allowed:
            warn(f"[IMPACT] Not calling: {why}. Keyword links only.")
            return None

        try:
            reply = client.messages.create(
                model=self.model, max_tokens=1200,
                messages=[{"role": "user", "content": self.PROMPT.format(
                    headline=headline, body=(body or "")[:1500],
                    candidates=listing)}])
            text = "".join(getattr(b, "text", "") for b in reply.content)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[IMPACT] reasoning failed ({exc}) -- keyword links only.")
            return None

        usage = getattr(reply, "usage", None)
        if usage is not None:
            self._budget.record(
                self.model, purpose="news_impact",
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_read_tokens=getattr(
                    usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(
                    usage, "cache_creation_input_tokens", 0) or 0)

        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            diagnostic(f"[IMPACT] unparseable reply: {text[:200]}")
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            diagnostic(f"[IMPACT] bad JSON: {text[:200]}")
            return None

        allowed = {c["symbol"] for c in candidates}
        out = []
        for row in (data.get("impacts") or []):
            symbol = str(row.get("symbol") or "").strip().upper()
            direction = str(row.get("direction") or "").strip().upper()
            # A symbol we do not have, or a direction we did not ask
            # for, is dropped rather than shown. The model must not be
            # able to put a ticker on this screen that the master file
            # has never heard of.
            if symbol not in allowed or direction not in (POSITIVE, NEGATIVE):
                continue
            try:
                confidence = float(row.get("confidence"))
            except (TypeError, ValueError):
                confidence = None
            out.append({"symbol": symbol, "direction": direction,
                        "reason": str(row.get("reason") or "")[:300],
                        "confidence": confidence, "how": "reasoned"})
        return out

    # ------------------------------------------------------------

    @staticmethod
    def news_id(headline, source="", at=None):
        """Identity is the HEADLINE, not the channel.

        The same story arrives from three of the four channels within
        minutes. Keying on source stored it three times and the panel
        showed the same sentence three times -- which is how a feed
        stops being read. `source` and `at` are kept as columns, they
        just do not make a story a different story.
        """
        raw = re.sub(r"[^A-Z0-9 ]", "", str(headline).upper())
        raw = re.sub(r"\s+", " ", raw).strip()
        return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]

    def record(self, headline, body="", source="", url="", at=None,
               reason_it=True):
        """Store one news item and everything it touches.

        Returns the stored impact rows. Idempotent on the same
        headline+source+time.
        """
        headline = (headline or "").strip()
        if not headline:
            return []
        # A section divider or a bare URL is not a story. Refused at the
        # door rather than stored and filtered later -- see
        # is_not_a_story() for what was actually in the database.
        if is_not_a_story(headline, body):
            diagnostic(f"[IMPACT] not a story, skipped: {headline[:60]!r}")
            return []
        news_id = self.news_id(headline, source, at)
        if self.already_have(news_id):
            return self.for_news(news_id)

        # A recommendation is stored, labelled, and never reasoned about
        # as though it were an event. Asking the model "who gains from
        # this news" about somebody's buy call would launder an opinion
        # into a direction with a confidence attached to it.
        kind = TIP if looks_like_a_tip(f"{headline} {body}") else NEWS
        if kind == TIP:
            reason_it = False

        candidates = self.candidates(f"{headline} {body}")

        # MACRO. A story that names no company and no line of business
        # is about the market, not about a stock, and it is stored that
        # way -- kept and readable, with ZERO impact rows.
        #
        # The alternative was what this used to do: fan a Fed rate
        # decision out across all 105 stocks tagged INTEREST RATE
        # SENSITIVE. Six realty microcaps "matched on: INTEREST, RATE,
        # REAL" and none of them were in the story. An empty impact list
        # says "this moves everything, so it distinguishes nothing",
        # which is true and useful. A list of 105 says nothing at all
        # and costs a reasoning call to say it.
        scope = MACRO if not candidates else STOCK
        if scope == MACRO:
            reason_it = False

        impacts = self._reason(headline, body, candidates) if reason_it else None
        reasoned = impacts is not None
        if not reasoned:
            # No key, no network, or an unusable reply. Keep the links
            # WITHOUT a direction rather than inventing one -- "these
            # stocks share the subject" is still worth showing, and it
            # is clearly a different claim from "these stocks gain".
            impacts = [{"symbol": c["symbol"], "direction": UNKNOWN,
                        "reason": "matched on: " + ", ".join(c["hits"][:4]),
                        "confidence": None, "how": "keyword"}
                       for c in candidates[:10]]

        when = at.isoformat() if hasattr(at, "isoformat") else (at or "")
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "INSERT OR REPLACE INTO news (news_id, at, seen_at,"
                    " source, headline, body, url, reasoned, scope, kind)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (news_id, when,
                     datetime.now().isoformat(timespec="seconds"),
                     source, headline[:500], (body or "")[:2000], url,
                     1 if reasoned else 0, scope, kind))
                conn.executemany(
                    "INSERT OR REPLACE INTO impact (news_id, symbol,"
                    " direction, reason, confidence, how)"
                    " VALUES (?,?,?,?,?,?)",
                    [(news_id, i["symbol"], i["direction"], i["reason"],
                      i["confidence"], i["how"]) for i in impacts])
                conn.commit()
                conn.close()
        except sqlite3.Error as exc:
            warn(f"[IMPACT] could not store: {exc}")
            return impacts

        if reasoned and impacts:
            plus = [i["symbol"] for i in impacts if i["direction"] == POSITIVE]
            minus = [i["symbol"] for i in impacts if i["direction"] == NEGATIVE]
            decision(f"[IMPACT] {headline[:60]} -> "
                     f"+{plus or '-'} / -{minus or '-'}")
        return impacts

    def already_have(self, news_id):
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute("SELECT 1 FROM news WHERE news_id = ?",
                               (news_id,)).fetchone()
            conn.close()
            return bool(row)
        except sqlite3.Error:
            return False

    def scope_of(self, news_id):
        """STOCK or MACRO -- whether this story named anybody.

        Matters for reading an empty impact list correctly. MACRO plus
        zero links means "this moves the whole market, so it singles out
        nothing", which is a finding. STOCK plus zero links would mean
        the matcher found nobody, which is a different thing entirely.
        Without this column the two are indistinguishable.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute("SELECT scope FROM news WHERE news_id = ?",
                               (news_id,)).fetchone()
            conn.close()
        except sqlite3.Error:
            return None
        return (row[0] if row and row[0] else STOCK) if row else None

    def kind_of(self, news_id):
        """NEWS or TIP. See the constants for why this is kept apart
        from scope and from direction."""
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute("SELECT kind FROM news WHERE news_id = ?",
                               (news_id,)).fetchone()
            conn.close()
        except sqlite3.Error:
            return None
        return (row[0] if row and row[0] else NEWS) if row else None

    # ------------------------------------------------------------
    # recall
    # ------------------------------------------------------------

    def for_news(self, news_id):
        """Winners and losers for one story."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM impact WHERE news_id = ? "
                "ORDER BY direction, confidence DESC", (news_id,))]
            conn.close()
            return rows
        except sqlite3.Error:
            return []

    def for_symbol(self, symbol, limit=10, hours=None):
        """Every story that touched one stock -- the operator's
        "recall the memory of any stock on demand", for news."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            sql = ("SELECT i.symbol, i.direction, i.reason, i.confidence,"
                   " i.how, n.headline, n.source, n.at, n.url"
                   " FROM impact i JOIN news n ON n.news_id = i.news_id"
                   " WHERE i.symbol = ?")
            params = [str(symbol).strip().upper()]
            if hours:
                sql += " AND n.seen_at >= ?"
                params.append((datetime.now()
                               - timedelta(hours=hours)).isoformat())
            sql += " ORDER BY n.seen_at DESC LIMIT ?"
            params.append(limit)
            rows = [dict(r) for r in conn.execute(sql, params)]
            conn.close()
            return rows
        except sqlite3.Error:
            return []

    def recent(self, limit=20, hours=None):
        """Recent stories, each with its winners and losers attached --
        what the dashboard panel renders."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM news"
            params = []
            if hours:
                sql += " WHERE seen_at >= ?"
                params.append((datetime.now()
                               - timedelta(hours=hours)).isoformat())
            sql += " ORDER BY seen_at DESC LIMIT ?"
            params.append(limit)
            stories = [dict(r) for r in conn.execute(sql, params)]
            conn.close()
        except sqlite3.Error:
            return []
        for story in stories:
            rows = self.for_news(story["news_id"])
            story["positive"] = [r for r in rows if r["direction"] == POSITIVE]
            story["negative"] = [r for r in rows if r["direction"] == NEGATIVE]
            story["unknown"] = [r for r in rows if r["direction"] == UNKNOWN]
            story["reasoned"] = bool(story.get("reasoned"))
        return stories

    def status(self):
        try:
            conn = sqlite3.connect(self.db_path)
            news = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            links = conn.execute("SELECT COUNT(*) FROM impact").fetchone()[0]
            reasoned = conn.execute(
                "SELECT COUNT(*) FROM news WHERE reasoned = 1").fetchone()[0]
            conn.close()
        except sqlite3.Error:
            return {"news": 0, "links": 0, "reasoned": 0, "available": False}
        # ---- IT REPORTED "ON" WHILE NOTHING REASONED. 12 Aug 2026. ----
        #
        #     "bot is getting results, news. but i'm not sure whether bot
        #      knows it."                          -- operator
        #
        # This asked ONE of the two questions _get_client() asks, and
        # not the one that was false. config.AI_ENABLED -- the master
        # switch, turned off on 10 August after every call came back
        # "credit balance is too low" -- means no client is ever built.
        # The key was still in .env, so this returned True, and
        # main.py's startup line printed
        #
        #     [IMPACT] 3736 stories, 5163 stock links, reasoning ON
        #
        # every morning while the real number was zero. Measured on the
        # store: 4 August reasoned 361 of 461 stories; from 6 August to
        # 11 August it reasoned 0 of 1,561, and every impact link in
        # that window is `how = keyword` with `direction = UNKNOWN`.
        #
        # That matters beyond the panel: core/ranker.py REFUSES a
        # keyword match -- "reason is a lookup, not a mechanism" -- so
        # the ranked lane was starved of reasons for a week while the
        # screen said the reasoning was running.
        #
        # Both conditions now, and the blocker is named so the panel can
        # say WHICH one to fix.
        try:
            from config import AI_ENABLED
        except Exception:                                  # noqa: BLE001
            AI_ENABLED = False
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        blocked = None
        if not AI_ENABLED:
            blocked = ("config.AI_ENABLED is False -- the master switch. "
                       "No paid call leaves this process, so news is "
                       "linked by keyword only, with no direction.")
        elif not has_key:
            blocked = ("no ANTHROPIC_API_KEY -- news is linked by keyword "
                       "only, with no direction.")
        return {"news": news, "links": links, "reasoned": reasoned,
                "available": True,
                "reasoning_on": bool(AI_ENABLED and has_key),
                "ai_enabled": bool(AI_ENABLED),
                "has_key": has_key,
                "blocked_by": blocked}
