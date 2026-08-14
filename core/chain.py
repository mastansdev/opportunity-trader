"""
==========================================================
The six layers, as one line
==========================================================

    "in live markets i cannot see +10/+8 chips right? thats your work
     to make sure the code does the backgorund & show the final output
     to end user with clear case"
                                    -- operator, 2 August 2026

He is right, and it is the argument against everything built this
weekend if it is not answered. Ten chips on a fifty-row table at 09:15
is not a screen anybody reads; it is a screen somebody scrolls past.

So the chain is assembled HERE, in the background, and the panel shows
one bright line. The six layers do not go away -- they collapse behind
it, one click, exactly as they are.

WHAT IT MUST NOT SAY
--------------------
    "Have you forgot SEBI mandates about no stock buy / sell
     recommendations? no one gives that signals."

Nobody in this chain issues an instruction. Earnings Pulse: "We don't
tell you whether to buy, hold, or skip a name." Stockbee publishes
criteria, not calls. So this line reports STATE -- how many of the six
reads are present, whether they agree, and whether the market has had
a chance to price it. A test fails if buy, sell, hold or skip appear.

THE FIVE STATES
---------------
    ALIGNED    the reads that exist point the same way
    SPLIT      two reads contradict each other -- the Cockpit's own
               purpose: "see disagreements, not an opaque score"
    FLAGGED    a one-off, a red flag, or a quality warning
    PRICED     the tape has already answered it
    THIN       too few layers to say anything

Colour carries the state so the row is readable without reading.

WHY "SPLIT" IS NOT A FAILURE STATE
----------------------------------
It is the most valuable one. SYRMA: the algorithm said Weak, the audit
read the concall and said BEAT on 67% revenue growth, and the tape did
nothing. That is not a stock to skip -- it is the only kind of stock
where the crowd has not caught up. Measured across the store, the
audit contradicts the algorithm on ONE IN FOUR cards.

A single-word verdict would have hidden every one of them.

Author : H&M Opportunity Trader
==========================================================
"""

import re

# The six reads, in the publisher's own order and their own names.
LAYERS = (
    ("EXPECTATION", "01", "BASELINE"),
    ("RESULT", "02", "BACKWARD"),
    ("AI_VERDICT", "04", "FORWARD"),
    ("MARKET_ANSWER", "05", "SAFETY"),
    ("SETUP", "06", "SETUP"),
)

ALIGNED, SPLIT, FLAGGED, PRICED, THIN = (
    "ALIGNED", "SPLIT", "FLAGGED", "PRICED", "THIN")

# ---------------------------------------------------------------
# THE CALL -- 2 August 2026
# ---------------------------------------------------------------
#     "again this is confusing. how many times i need to beg u? all
#      data must process at backend. on display at why? only chips
#      buy , wait , avoid can be used right? this is our own bot & we
#      r not selling anything to any one at all"
#
# He is right and I was wrong. He raised SEBI to explain why the
# CHANNELS publish verdicts instead of calls -- they sell to the
# public. I then turned his own point back on him and refused to put
# a call on a private dashboard he built for himself. That is not what
# the rule covers, and he had to say it four times.
#
# So: three words. Everything else happens behind them.
#
# WHAT THESE ARE, HONESTLY. This is HIS rule, written down and applied
# consistently by the bot. It is not a measured edge -- nothing has
# tested whether these three buckets beat the market, because the
# layers they read are between eight and eighty samples old. The bot's
# job is to apply the rule the same way every time and to be quick
# about it, which is exactly what he asked for.
BUY, WAIT, AVOID = "BUY", "WAIT", "AVOID"

# Where a call sorts on a list. Used with canslim.tier_rank(), which
# leads -- the operator's instruction was that the TIER decides primary
# focus. This only settles ties inside a tier.
#
# AVOID sits BELOW "no call yet", deliberately. An unread name is a
# question; an AVOID is an answer, and it is the one answer that must
# never sit at the top of a list he is scanning for something to buy.
CALL_ORDER = {BUY: 0, WAIT: 1, AVOID: 3}
NO_CALL = 2


def call_rank(state):
    """0 for BUY, 3 for AVOID, 2 for a name nothing has read yet."""
    return CALL_ORDER.get(str(state or "").strip().upper(), NO_CALL)

_GOOD_GRADE = ("EXCELLENT", "GREAT")
_BAD_GRADE = ("WEAK", "POOR")

_OVERRULES = re.compile(r"AI AUDIT OVERRULES", re.I)
_TAPE_SPLIT = re.compile(r"TAPE DISAGREED", re.I)
_TAPE_MOVED = re.compile(r"TAPE (AGREED|DISAGREED)", re.I)
_UNPRICED = re.compile(r"REPORTED AFTER CLOSE", re.I)
_ONE_OFF = re.compile(r"^ONE-?OFF\b|NOT CLEAN", re.I)
_CLEAN = re.compile(r"^CLEAN\s*\|", re.I)
_EXCELLENT = re.compile(r"^PULSE:\s*Excellent\b", re.I)
# ---- THE TIER IS A COUNT, NOT A GRADE ----
# Their guide: "The rank is how many of these three frameworks are
# simultaneously aligned. A stock at the top of the list has passed
# all three."
#
#     EXCEPTIONAL   all three agree -- 8 of 90 on 1 August
#     STRONG        two agree
#     MIXED         one or two, with something failing
#     WEAK          the frameworks disagree
#
# "Focus on the top one or two names. Width of the list is not width
# of the opportunity." So EXCEPTIONAL is evidence in its own right --
# three independent frameworks pointing the same way is the strongest
# read in the whole chain -- and STRONG is supporting, not equal.
_ALL_THREE = re.compile(r"CANSLIM EXCEPTIONAL\b", re.I)
_TOP_TIER = re.compile(r"CANSLIM (EXCEPTIONAL|STRONG)\b", re.I)
# The chart layer saying the setup is poor. It was read only as a
# bonus when it was good, and ignored when it was bad -- APTUS came
# back BUY carrying "CANSLIM WEAK -- 30 of 90 today".
_WEAK_TIER = re.compile(r"CANSLIM WEAK\b", re.I)
_LOW_BAR = re.compile(r"^EXPECTED (NEUTRAL|BEARISH)\b", re.I)


def _heads(events, kind):
    return [str(e.get("headline") or "") for e in events
            if str(e.get("kind") or "").upper() == kind]


# ---------------------------------------------------------------
# THE OPERATOR'S RULE, IN FULL -- 2 August 2026
# ---------------------------------------------------------------
#     "without any thing stock doesn't move, that something is we need
#      to find out + volumes supports the data + ride untill the
#      momentum stays - exit once it gone ruthlessly + repeat the
#      process on only high setups"
#
# Five parts. The chain implemented ONE of them -- find the catalyst --
# and called the answer BUY. That is how SATIN, down 9.95% on the day,
# came back BUY: it had a beat two days earlier and nothing in the
# chain knew what the price had done since.
#
#   1  a catalyst        the six reads. Built.
#   2  volume confirms   the bot computes vol_ratio on every row and
#                        the chain never saw it.
#   3  ride the momentum the engine's job, not this chip's.
#   4  exit ruthlessly   the 2.5% stop. Not this chip's either.
#   5  only high setups  which is what 2 and the guards below enforce.
#
# So parts 1 and 2 belong here, and part 2 was missing entirely.

# Volume at or under its own normal means nobody turned up. A catalyst
# nobody traded is a catalyst the market has not accepted yet -- his
# rule is explicit that volume must SUPPORT the data.
VOLUME_CONFIRMS = 1.5

# Down this much on the day and the story has already been answered,
# whatever the cards said last night. The falling-knife guard.
FALLING_HARD_PCT = -3.0

# Up this much and the move he was trying to be early to has happened.
#     "if i bought even a good stock at near Upper Circuit whats the
#      use?"                              -- operator, 1 August 2026
ALREADY_RUN_PCT = 9.0


def read(events, vol_ratio=None, change_pct=None):
    """Everything the chain knows about one stock, as plain facts.

    Deliberately separate from the wording. What is true and what the
    chip says are two questions, and mixing them is how a screen ends
    up asserting more than the data does.

    `vol_ratio` and `change_pct` are TODAY, from the shortlist row.
    Without them the chain is reading last night's cards and calling
    it a view on this morning's price.
    """
    events = list(events or [])
    present = {name for name, _n, _lbl in LAYERS
               if _heads(events, name)}

    grades = [str(e.get("grade") or "").upper() for e in events
              if str(e.get("kind") or "").upper() == "RESULT"]
    every = " || ".join(str(e.get("headline") or "") for e in events)
    chips = [str(e.get("headline") or "") for e in events]

    return {
        "layers": len(present),
        "present": present,
        "strong_result": any(g in _GOOD_GRADE for g in grades)
                          or any(_EXCELLENT.match(c) for c in chips),
        "weak_result": any(g in _BAD_GRADE for g in grades),
        "clean": any(_CLEAN.match(c) for c in chips),
        "flagged": any(_ONE_OFF.match(c) for c in chips),
        "audit_overrules": bool(_OVERRULES.search(every)),
        "tape_split": bool(_TAPE_SPLIT.search(every)),
        "tape_answered": bool(_TAPE_MOVED.search(every)),
        "unpriced": bool(_UNPRICED.search(every)),
        "top_tier": bool(_TOP_TIER.search(every)),
        "all_three": bool(_ALL_THREE.search(every)),
        "weak_tier": bool(_WEAK_TIER.search(every)),
        "low_bar": any(_LOW_BAR.match(c) for c in chips),
        # ---- TODAY, not last night ----
        "vol_ratio": vol_ratio,
        "change_pct": change_pct,
        "volume_confirms": (vol_ratio is not None
                            and vol_ratio >= VOLUME_CONFIRMS),
        "volume_absent": (vol_ratio is not None
                          and vol_ratio < VOLUME_CONFIRMS),
        "falling_hard": (change_pct is not None
                         and change_pct <= FALLING_HARD_PCT),
        "already_run": (change_pct is not None
                        and change_pct >= ALREADY_RUN_PCT),
    }


# ---- A CALL THAT REWRITES ITSELF IS NOT A CALL. 3 August 2026. ----
#
#     "in dashboard chips are changing constantly - on Yasho some times
#      AVOID, BUY, WAIT, EXCELLENT"
#                                     -- operator, first live session
#
# call() is pure and recomputed on every dashboard refresh -- once a
# second -- from facts that move with price:
#
#     falling_hard   change_pct <= -3.0
#     volume_absent  vol_ratio  <   1.5
#
# YASHO traded 4090 -> 4199 -> 4002 -> 4077 that morning. It crossed
# -3.0% repeatedly, so the chip read BUY, then AVOID, then WAIT, then
# BUY again, seconds apart, while he was deciding whether to hold. A
# recommendation that changes faster than a person can act on it is
# worse than no recommendation: it costs attention and gives nothing.
#
# TWO GUARDS, BOTH NEEDED
# -----------------------
# A BAND stops the flicker at the threshold itself. Once a stock is
# judged falling_hard it must recover meaningfully -- not by a hair --
# before that stops being true.
#
# A MINIMUM HOLD stops everything else. A new call has to survive for
# HOLD_SECONDS before it replaces the one on screen. A real move
# through the band still lands within a few seconds; noise never does.
#
# Kept OUT of call() itself, which stays pure and testable. This is a
# thin layer over it, and the raw call is still available to anything
# that wants the instantaneous answer.
HYSTERESIS_BAND_PCT = 0.75      # how far back it must come to be "not falling"
HYSTERESIS_VOL_BAND = 0.25      # same idea for the volume ratio
HOLD_SECONDS = 20.0             # a new call must survive this long


def steady_facts(facts, previous=None):
    """`facts`, with the two continuous flags widened by a band.

    `previous` is the last call for this symbol. Only when the previous
    call was AVOID does falling_hard need the extra recovery to clear,
    which is what stops a stock hovering at -3.00% toggling forever.
    """
    facts = dict(facts or {})
    change = facts.get("change_pct")
    if change is not None and previous == AVOID:
        facts["falling_hard"] = change <= (FALLING_HARD_PCT
                                           + HYSTERESIS_BAND_PCT)
    ratio = facts.get("vol_ratio")
    if ratio is not None and previous == WAIT:
        facts["volume_absent"] = ratio < (VOLUME_CONFIRMS
                                          + HYSTERESIS_VOL_BAND)
        facts["volume_confirms"] = not facts["volume_absent"]
    return facts


class SteadyCall:
    """call(), held still long enough for a human to read it.

    One instance per process. Remembers what each symbol was last told
    and refuses to change it until the new answer has persisted.

    Deliberately NOT persisted to disk: a call is about right now, and
    a stale one restored at 09:15 would be a lie with a timestamp.
    """

    def __init__(self, hold_seconds=HOLD_SECONDS):
        self.hold_seconds = hold_seconds
        self._shown = {}        # symbol -> (call, since)
        self._waiting = {}      # symbol -> (candidate, first_seen)

    def __call__(self, symbol, facts, now=None):
        import time
        now = time.monotonic() if now is None else now
        symbol = str(symbol or "").upper()

        shown = self._shown.get(symbol)
        previous = shown[0] if shown else None
        fresh = call(steady_facts(facts, previous))

        if previous is None:
            self._shown[symbol] = (fresh, now)
            self._waiting.pop(symbol, None)
            return fresh

        if fresh == previous:
            # Whatever it was thinking of changing to, it changed its
            # mind. That is exactly the flicker, and it never reaches
            # the screen.
            self._waiting.pop(symbol, None)
            return previous

        waiting = self._waiting.get(symbol)
        if waiting is None or waiting[0] != fresh:
            self._waiting[symbol] = (fresh, now)
            return previous

        if now - waiting[1] >= self.hold_seconds:
            self._shown[symbol] = (fresh, now)
            self._waiting.pop(symbol, None)
            return fresh
        return previous

    def since(self, symbol):
        """When the call on screen was last CHANGED, or None.

        A chip that says when it decided is honest. One that silently
        rewrites itself is not -- which is the whole complaint.
        """
        got = self._shown.get(str(symbol or "").upper())
        return got[1] if got else None


def state(facts):
    """One of the five states.

    Order matters and is deliberate:

      FLAGGED first -- a one-off outranks everything positive beside
        it. ONE-OFF measured -1.61% and beat the market 28% of the
        time; burying that under an agreement is how a screen flatters
        itself.

      SPLIT second -- a contradiction is worth more than an agreement,
        because the agreement is what everybody else can see too.

      Then THIN, then PRICED, then ALIGNED.
    """
    if not facts or not facts.get("layers"):
        return THIN
    if facts.get("flagged"):
        return FLAGGED
    if facts.get("audit_overrules") or facts.get("tape_split"):
        return SPLIT
    if facts["layers"] < 2:
        return THIN
    if facts.get("tape_answered") and not facts.get("unpriced"):
        return PRICED
    return ALIGNED


def call(facts):
    """BUY, WAIT or AVOID. One of three words, always.

    THE RULES, in the order they are applied. Order is the design --
    the first one that matches wins, so what comes first is what
    outranks everything after it.

    AVOID
      1. A one-off or quality flag. ONE-OFF measured -1.61% and beat
         the market 28% of the time. It outranks every positive read
         beside it, because the positive reads are describing a profit
         that is not repeatable.
      2. A weak quarter the audit AGREED with. Two independent reads
         both saying the numbers are bad.

    BUY
      3. The evidence is positive, nothing is flagged, and the market
         has NOT already answered it. Positive means any of: an
         EXCELLENT or GREAT grade, a CLEAN brief, or the audit
         overruling a weak grade upward -- SYRMA, where the algorithm
         said Weak and the audit found revenue up 67%.
         Needs two reads minimum. One source is an opinion.

    WAIT
      4. Everything else. Positive but the tape already moved; sources
         disagreeing; or too little to say. WAIT is not a soft no --
         it is "this is not the moment", which on a chain built around
         being early is a real answer.
    """
    facts = facts or {}
    if not facts.get("layers"):
        return WAIT

    if facts.get("flagged"):
        return AVOID
    # ---- A CONTESTED WEAK IS NOT A WEAK, 2 August 2026 ----
    #
    #   "pls make sure to follow the pro channel way in building our
    #    own chips. we cannot deviate from NSE & PRO CHANNELS."
    #
    # From Earnings Pulse's own CANSLIM guide, verbatim:
    #
    #   "A stock tagged Weak by Pulse but accompanied by a green 360
    #    brief -- one-off charge, strong guidance, analyst upgrades
    #    expected -- can still appear in the CANSLIM Ratings list at
    #    the discretion of the qualitative layer."
    #
    # They built for this case deliberately. CONCORDBIO on 1 August had
    # FOUR grades on one quarter -- GOOD, MIXED, OK and WEAK -- plus a
    # CLEAN brief from Earnings 360 and a CANSLIM listing, and it rose
    # 6.77%. The old rule read the WEAK, ignored the other three, and
    # printed AVOID.
    #
    # That is the bot overruling the publisher. AVOID now requires the
    # weak reading to be UNCONTESTED: no CLEAN brief, no strong grade
    # from another source, no audit overruling it upward.
    contested = (facts.get("clean") or facts.get("strong_result")
                 or facts.get("audit_overrules"))
    if facts.get("weak_result") and not contested:
        return AVOID
    # ---- THE FALLING KNIFE, 2 August 2026 ----
    # SATIN came back BUY while it was down 9.95% on the day. It had a
    # beat two sessions earlier and the chain had no idea what the
    # price had done since. A stock in free-fall has answered the
    # story, whatever last night's cards said.
    if facts.get("falling_hard"):
        return AVOID

    # EXCEPTIONAL is a positive read on its own: earnings quality,
    # chart structure and gap potential all aligned. Requiring a
    # separate strong grade beside it would discard the one layer that
    # already checked all three.
    positive = (facts.get("strong_result") or facts.get("clean")
                or facts.get("audit_overrules") or facts.get("all_three"))
    if not positive:
        return WAIT
    if facts["layers"] < 2:
        return WAIT
    # ---- VOLUME MUST SUPPORT THE DATA ----
    #     "without any thing stock doesn't move, that something is we
    #      need to find out + volumes supports the data"
    # A catalyst nobody traded is a catalyst the market has not
    # accepted. WAIT, not AVOID -- the story may still be true, it
    # just has not been believed yet.
    if facts.get("volume_absent"):
        return WAIT
    # ---- WHAT THE TIER ACTUALLY MEANS ----
    #
    # Their guide, verbatim: "The rank is how many of these three
    # frameworks are simultaneously aligned" -- earnings quality, chart
    # structure, gap potential.
    #
    # So CANSLIM WEAK does NOT mean "bad stock". It means the three
    # frameworks do not agree with each other. Treating it as a verdict
    # on the company was my reading, not theirs.
    #
    # It still holds a BUY back, because their own instruction is
    # "focus on the top one or two names -- width of the list is not
    # width of the opportunity". A stock where the frameworks disagree
    # is not one of the top names.
    if facts.get("weak_tier") and not facts.get("top_tier"):
        return WAIT
    # Already answered by the tape, and not held over a close.
    if facts.get("tape_answered") and not facts.get("unpriced"):
        return WAIT
    if facts.get("tape_split"):
        # The grade and the price point opposite ways. That is worth
        # opening, not acting on blind.
        return WAIT
    # ---- ALREADY RUN ----
    #     "if i bought even a good stock at near Upper Circuit whats
    #      the use?"
    # The point of the whole chain is to be early. A stock up 9% has
    # made the move it was surfaced for.
    if facts.get("already_run"):
        return WAIT
    return BUY


def reason(facts):
    """The short WHY, for the hover. Never shown on the row itself."""
    facts = facts or {}
    verdict = call(facts)
    if verdict == AVOID:
        if facts.get("flagged"):
            return "earnings quality flag -- the profit is not repeatable"
        if facts.get("falling_hard"):
            return (f"down {facts.get('change_pct', 0):.1f}% today -- "
                    f"the story has already been answered")
        return "weak quarter, and the audit agrees"
    if verdict == BUY:
        bits = []
        if facts.get("audit_overrules"):
            bits.append("the audit overrules a weak grade")
        if facts.get("strong_result"):
            bits.append("strong result")
        if facts.get("clean"):
            bits.append("clean brief")
        if facts.get("unpriced"):
            bits.append("not priced yet")
        if facts.get("low_bar"):
            bits.append("low bar")
        if facts.get("all_three"):
            bits.append("CANSLIM EXCEPTIONAL -- all three frameworks agree")
        elif facts.get("top_tier"):
            bits.append("CANSLIM STRONG")
        if facts.get("volume_confirms"):
            bits.append(f"volume {facts['vol_ratio']:.1f}x confirms")
        return ", ".join(bits) or "the reads agree"
    if not facts.get("layers"):
        return "nothing on this stock yet"
    if facts["layers"] < 2:
        return "one read only -- not enough"
    if facts.get("volume_absent"):
        return (f"volume only {facts.get('vol_ratio', 0):.1f}x -- "
                f"nobody has traded the story")
    if facts.get("weak_tier"):
        return "CANSLIM: the three frameworks do not agree"
    if facts.get("already_run"):
        return (f"already up {facts.get('change_pct', 0):.1f}% today -- "
                f"the move has happened")
    if facts.get("tape_split"):
        return "the grade and the price point opposite ways"
    if facts.get("tape_answered"):
        return "the tape has already answered it"
    return "the reads do not add up to anything yet"


def summary(events, vol_ratio=None, change_pct=None):
    """The chip. Three words, nothing else.

        "background proces must follow all the points but chips shows
         only call to action"

    Everything read() computes still happens. It decides the word and
    then gets out of the way.
    """
    facts = read(events, vol_ratio=vol_ratio, change_pct=change_pct)
    if not facts["layers"]:
        return None
    return call(facts)


def rank(facts):
    """A sort key, so the loudest rows float without inventing a score.

    NOT points and never added to the score. It orders equals: two
    rows both ALIGNED, the one with more reads behind it goes first.
    """
    order = {SPLIT: 4, ALIGNED: 3, FLAGGED: 2, PRICED: 1, THIN: 0}
    facts = facts or {}
    base = order.get(state(facts), 0) * 10
    return base + min(facts.get("layers", 0), 6)
