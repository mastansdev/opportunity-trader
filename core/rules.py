"""
==========================================================
core/rules.py  --  every trading threshold, in one place
==========================================================

    "why you created this bot as a mess of files? how many times i need
     to tell you don't complicate the work."
                                -- operator, 11 August 2026

He is right, and this file is the correction.

WHAT WENT WRONG
---------------
The bot has 429 Python files, but file count was never the disease.
This was:

    MIN_MOVE_PCT        ranker 1.0   select 0.5   shortlist 2.0
                        watchlist_builder 1.0
    MIN_VOLUME_RATIO    ranker 1.2   select 1.5   watchlist 1.5
    RISK_PER_TRADE_RS   config 2000  position_plan 1500
    MIN_STOP_DISTANCE   config 0.01  position_plan 0.75
    MIN_TURNOVER_RS     config 2 Cr  universe_builder 5 Cr

---- AND THEN I CHECKED THE UNITS, AND HALF OF THAT LIST WAS WRONG ----

I put those six to him as six duplicates. Reading the call sites
instead of the declarations, only THREE are:

    RISK_PER_TRADE_RS    REAL. Same unit, same meaning, two values.
                         config's 2000 is read only by backtest/*.py.
                         position_plan's 1500 is what every live trade
                         has ever used. He configured 2000 and got 1500.

    MIN_VOLUME_RATIO     REAL. 1.2 on the entry path against 1.5
                         everywhere else, all meaning the same thing.

    MIN_MOVE_PCT         PART REAL. watchlist_builder's 1.0 was a
                         straight copy of the ranker's. But select.py's
                         0.5 measures from TODAY'S OPEN and the
                         ranker's from YESTERDAY'S CLOSE, and
                         shortlist's 2.0 is a display bar. Different
                         rules wearing one name.

    MIN_STOP_DISTANCE    NOT A DUPLICATE. Different UNITS. config's
                         0.01 is a FRACTION, used as `price * 0.01` by
                         backtest/*.py -- that is 1%. position_plan's
                         0.75 is a PERCENT. I called the 0.01 "one
                         tick, meaningless" and recommended deleting
                         it. That was wrong and it would have been a
                         real regression in the backtests.

    MIN_TURNOVER_RS      NOT A DUPLICATE. universe_builder's Rs 5 Cr is
                         an AVERAGE DAY. engine's Rs 2 Cr is TRADED SO
                         FAR TODAY. Two different questions.

    W_VOLUME             NOT A DUPLICATE. Two scoring scales.

So this file owns what is genuinely shared and deliberately leaves the
rest alone. Naming a thing twice is a bug; two things needing separate
numbers is not, and merging those would have been the worse mistake.

Nothing here is clever. It is a list of numbers with one owner. Any
module that needs a threshold imports it FROM HERE and declares none
of its own. tests/test_rules_are_not_duplicated.py fails the build if
that stops being true.

THE NUMBERS HE APPROVED, 11 August 2026
---------------------------------------
    risk per trade        Rs 1,500     (config's 2,000 is backtest-only)
    volume vs normal      1.5x         (was 1.2x on the entry path)
    price floor           Rs 50        (now applied by the ranker too)

    minimum stop          0.75%        unchanged -- not a duplicate
    minimum turnover      Rs 5 Cr      unchanged -- not a duplicate

TWO THAT ONLY LOOKED LIKE DUPLICATES
------------------------------------
The move threshold was FOUR numbers because it is not one rule.
core/ranker.py measures from YESTERDAY'S CLOSE. core/select.py
measures from TODAY'S OPEN. Those answer different questions and both
are wanted, so they are named apart here rather than merged into one
wrong number. Same for the volume weights: ranker and select score on
different scales.

    "0 knowlede is far better than half knowledge"

A single name covering two meanings is half knowledge, and it cost a
whole day of replays that measured the wrong bot.

Author : H&M Opportunity Trader
==========================================================
"""

# ==========================================================
#  MONEY
# ==========================================================

# What one losing trade costs. qty = RISK_PER_TRADE_RS / (entry - stop),
# always rounded DOWN, so the loss can never exceed this.
#
# Deliberately NOT raised to the Rs 2,000 that sat in config.py. All
# twelve replayed days were measured at 1,500 and the selector has no
# proven edge yet -- raising size before there is an edge only loses
# money faster. Raise it after, not before. His call, 11 August.
RISK_PER_TRADE_RS = 1500.0

# Margin Dhan blocks for one MTF position. Caps qty independently of
# the risk budget: a share can be affordable by risk and unaffordable
# by margin.
MTF_MARGIN_PER_POSITION_RS = 30_000.0

# Below this the stock is not traded at all, "no matter what".
#
# ---- IT LIVED IN THE WRONG PLACE UNTIL 11 AUGUST. ----
# This was enforced only inside Engine._enter -- the LAST line of the
# order path. core/ranker.py had never heard of it. So on 5 August the
# ranker scored SEPC at Rs 6.29 and MSUMI at Rs 41.07 on thirty
# separate cycles, auto_entry cleared them all thirty times, and the
# order gate threw every one away. Nothing remembered, so five minutes
# later it happened again.
#
# It belongs at the top of the funnel, not the bottom.
MIN_TRADABLE_PRICE_RS = 50.0


# ==========================================================
#  THE STOP
# ==========================================================

# Closer than this and ordinary noise takes the trade out.
MIN_STOP_DISTANCE_PCT = 0.75

# Further than this and the loss stops being small.
#
# ---- THIS IS THE MOST EXPENSIVE NUMBER IN THE BOT. ----
# Across twelve replayed days it refused 1,794 candidates across 110
# stocks -- more than every other refusal combined. The stop is
# anchored to the DAY'S LOW, so the harder a stock has run from its
# open, the further its low, and the more certain the refusal. On
# 5 August the highest-scoring stock of the entire session, UNIPARTS,
# was refused 42 times for a stop 6.78% away.
#
# The rule therefore rejects the strongest movers and admits the ones
# that barely travelled. It is left at 6.0 on purpose: core/exit_plan.py
# sizes off a stock's TYPICAL RANGE instead of its day low and is the
# real fix, but it is not on the live path yet and has not been
# replayed. Changing this number instead would be guessing.
MAX_STOP_DISTANCE_PCT = 6.0

# Target = entry + this x (entry - stop). Not a price prediction -- the
# level below which the trade is not worth taking.
MIN_REWARD_MULTIPLE = 2.0


# ==========================================================
#  WHAT COUNTS AS A MOVE
# ==========================================================
#
# TWO RULES, NOT ONE. See the header.

# core/ranker.py: measured against YESTERDAY'S CLOSE. Below this,
# nothing has happened worth looking at.
MIN_MOVE_FROM_PREV_CLOSE_PCT = 1.0

# core/select.py: measured against TODAY'S OPEN. This is the one that
# answers "is it moving NOW", which is a different question -- a stock
# can be up 5% on yesterday and down all morning.
MIN_MOVE_FROM_OPEN_PCT = 0.5

# core/shortlist.py: a DISPLAY bar, not an entry bar. "Below this,
# nothing happened" -- it decides what is worth putting a line on the
# screen for, and it is deliberately stricter than either of the two
# above. Owned here so it has one home, kept at 2.0 so nothing on the
# screen changes shape without being asked for.
SHORTLIST_MIN_MOVE_PCT = 2.0


# ==========================================================
#  WHAT COUNTS AS PARTICIPATION
# ==========================================================

# Turnover so far today against the stock's own normal for this time of
# day. Raised from the ranker's old 1.2x to the 1.5x that select.py and
# watchlist_builder.py were already using -- 1.2x is barely above an
# ordinary day and let a band of thin movers onto the entry path that
# the rest of the bot refused.
# ---- RAISED 1.5 -> 2.5 ON 20 AUGUST 2026, ON MEASUREMENT ----
#
# core/signal_journal.py scored 13,272 recorded signals against the
# candles that followed them. Volume is the ONE selector in this bot
# with a clean, monotonic edge:
#
#     under 2x normal    n=8217    44.3% up at close
#     2 - 5x             n=2286    51.0%
#     5 - 10x            n=1142    54.2%
#     over 10x           n=1267    60.0%
#
# In his words, plainly: out of every 100 alerts, a barely-busier
# stock gives 44 up and 56 down, and a stock trading ten times its
# normal volume gives 60 up and 40 down. Heavy volume is real money
# arriving, not a price twitching.
#
# 1.5 sat inside the 44-in-100 band -- the worst part of the curve
# this bot measures. 2.5 moves the floor into the band that starts
# paying, and it is deliberately NOT set at 10x: that bucket is only
# 1,267 of 13,272 signals, so a 10x floor would be a different bot
# rather than a better-behaved one.
#
#     "yes do both"       -- operator, 20 August 2026
MIN_VOLUME_RATIO = 2.5

# A stock with no published reason has to bring far more than that
# before the tape alone is accepted as the reason.
# ---- IT COLLIDED WITH THE FLOOR. 20 August 2026. ----
#
# This is the bar a stock must clear to be taken WITH NO REASON AT
# ALL -- exceptional volume standing in for an event.
#
# It was 2.5 while MIN_VOLUME_RATIO was 1.5, so "exceptional" meant
# nearly twice the ordinary bar. Raising the floor to 2.5 the same
# day made the two numbers EQUAL, and that quietly retired the reason
# requirement for the ranked lane: every stock clearing the volume
# gate would also have qualified as unexplained.
#
# Caught by tests/test_ranker.py::test_no_reason_at_all_is_refused,
# which is exactly what that test is for -- a 3.0x mover with no
# reason came back on the board.
#
# 5.0 keeps "exceptional" meaningfully above the floor and sits in a
# band the journal actually measured: 5-10x normal volume was 54.2%
# up at close against 44.3% under 2x. Not 10x -- that bucket is 1,267
# of 13,272 signals, and a bar that high would close the lane rather
# than tighten it.
# ---- HIS CONCEPT, MADE ENFORCEABLE. 21 August 2026 ----
#
#     "Opportunity Trader Bot = only trades when an event or real
#      opportunity arised in markets, NEVER in to random stocks &
#      only long positions."                    -- standing instruction
#
#     "i gave u my concept & reasons to enter into trade with evidence
#      & underlying supports. still u cannot give me the wanted
#      output."                                 -- 21 August 2026
#
# He was right, and this is the line that proved it. 21 August, the
# bot took 3 signals out of 962:
#
#     JSFB     vol 6.03x   news=NEWS      evidence
#     URBANCO  vol 5.18x   news=NEWS      evidence
#     NCC      vol 8.54x   news=None filing=None results=None
#
# NCC was bought TWICE with nothing behind it, through the lane below
# -- "exceptional volume standing in for an event". That lane was
# built on real measurement (5-10x volume closed up 54.2% against
# 44.3% under 2x) and it is still a thin edge, and it is NOT the thing
# he asked for. Volume is evidence that money moved. It is not
# evidence of WHY, and "why" is his entire premise.
#
# With this True the tape can no longer stand in for a reason. A stock
# with no published event is refused however much volume it carries.
# UNEXPLAINED_MIN_VOLUME_RATIO below is left exactly as measured, so
# setting this False restores the old behaviour with its evidence
# intact rather than losing the number.
REQUIRE_A_REASON_ALWAYS = True

UNEXPLAINED_MIN_VOLUME_RATIO = 5.0
UNEXPLAINED_WEIGHT = 0.35


# ==========================================================
#  WHAT COUNTS AS A REASON
# ==========================================================
#
#     "Opportunity Trader Bot = only trades when an event or real
#      opportunity arised in markets, NEVER in to random stocks"
#                                    -- operator, 12 August 2026
#
# BOT_SPEC.md's entry rule 2 is "a written reason exists -- no
# mechanism, no trade". Until 12 August only ONE of the two lanes that
# can place an order enforced it:
#
#     ranker -> auto_entry     refused a stock with no mechanism
#     engine ORB breakout      never asked
#
# So the rule was in the document, in the ranker, and absent from the
# lane that fired 1,047 signals on 5 August. Both lanes now import the
# answer from here, which is the only way they cannot drift apart
# again.

# Text the matcher writes when a story merely NAMED a company and
# produced no reasoning. core/news_impact.py emits "matched on: INDGN"
# for this, and on its first real run that sailed through the ranker's
# gate and ranked sixth. A lookup result reporting its own work is not
# a mechanism and must not buy anything.
NOT_A_REASON = ("matched on:", "mentioned", "no reason", "unknown")

# Shorter than this and there is no sentence there to read. A reason
# has to say what happened, not just that something did.
MIN_REASON_CHARS = 15


# The switch, so this is one line to reverse. ON because it is his
# stated strategy in one sentence -- NOT because it has been measured.
#
# ---- WHAT THE 134 RECORDED TRADES ACTUALLY SAY. 12 August 2026. ----
#
# data/trade_memory.db, 10 sessions, every ORB entry the bot made:
#
#     STRUCTURAL_LONG_BREAKOUT, had_reason=0   n=49   avg   +74
#     STRUCTURAL_LONG_BREAKOUT, had_reason=1   n= 7   avg  -691
#
# So on the only numbers that exist, this rule would have refused the
# 49 that broke even and kept the 7 that lost. That is the opposite of
# the case for it.
#
# It is still ON, and the reason is not stubbornness:
#
#   1. n=7. core/outcomes.py will not call a bucket a result under 20
#      and neither should this. Seven trades is a coincidence.
#   2. The reason columns were barely populated over that window --
#      results_grade is NULL on ALL 134 rows and news_kind on 129 of
#      them. had_reason=1 therefore does not mean "had a good reason",
#      it means "one of three lookups happened to answer". The
#      published-chip fix that filled those in only shipped on
#      10 August, the date of the last trade in the table.
#   3. It is what he asked for, in writing, twice.
#
# RE-MEASURE THIS. When had_reason=1 reaches n=20 with the grade
# columns actually populated, that number decides this flag, not this
# comment. If it still says what it says today, turn this OFF.
#
# What the ENGINE accepts as a reason is narrower than what the RANKER
# accepts, on purpose. The ranker can see volume and can let an
# unexplained mover through on 2.5x its normal turnover
# (UNEXPLAINED_MIN_VOLUME_RATIO above). The ORB lane is looking at a
# price breaking a range and nothing else, so for it a named event --
# a classified filing, a classified news item, or a published grade --
# is the whole of the evidence. No event, no trade.
ENGINE_REQUIRE_REASON = True

# ==========================================================
#  RANK BY WHAT A REASON HAS PAID, NOT BY HOW IT SOUNDS
# ==========================================================
#
#     "u need to educate & make sure bot must understand about markets
#      & which events will create opportunity to which sector stocks"
#                                 -- operator, 19 August 2026
#
# core/ranker.py multiplies core/why_moving.py's mechanism weight into
# every score, and every one of those weights was typed by hand --
# 0.95, 0.9, 0.85, 0.8, 0.65, 0.6, 0.55, 0.5. core/opportunity.py had
# separately measured what each family is worth the session after it
# appears, and the two disagree:
#
#     ORDER_WIN         +0.64%  n=80    hand weight ~0.8
#     BUSINESS_UPDATE   -0.32%  n=123   hand weight ~0.9
#
# With this ON, the measured payoff TILTS the hand weight within
# [0.5x, 1.5x]. It cannot veto a trade and cannot conjure one -- the
# other four scoring terms are untouched. Off, the hand weights stand
# exactly as before, which is the state every earlier measurement in
# this repo was taken under.
RANK_BY_MEASURED_PAYOFF = True

# ==========================================================
#  THE SAME EVENT MOVES TWO STOCKS OPPOSITE WAYS
# ==========================================================
#
#     "do the sector polarity build next"
#                                 -- operator, 19 August 2026
#
# Crude rises: airline margins fall, oil producers' realisation
# rises. core/sector_map.sides() has known which side a company is
# on since 18 August and nothing on the ranking path asked it.
#
# Measured over a year of daily bars before arming -- next Indian
# session, market median removed, signed by the commodity's move:
#
#     COPPER      producers +0.210  consumers +0.116  (84 days)
#     CRUDE OIL   producers +0.115  consumers +0.000  (132 days)
#     GOLD        producers +1.309  consumers +0.366  (75 days)
#     SILVER      producers +0.261  consumers +0.085  (144 days)
#     NATURAL GAS producers +0.006  consumers -0.031  (164 days)
#
# Five out of five in the same direction, which is the finding; one
# commodity could be luck. The magnitude is small, so the tilt is
# bounded [0.90, 1.10] and reorders a close call rather than creating
# a trade.
RANK_BY_COMMODITY_POLARITY = True

# ==========================================================
#  A SECTOR MOVING TOGETHER COUNTS AS AN EVENT
# ==========================================================
#
#     "if complete sector is being rallied then something is happening
#      underlying right?"      -- operator, 20 August 2026
#
# Ten sugar names ran 7-17% on 20 August and every one was refused
# for "no event behind it", MAGADSUGAR on 15x its normal volume. The
# reason question was asked one stock at a time.
#
# Measured over a year, next-session move minus the market median:
#
#     any lone 5% mover (control)   n=3622   +0.550
#     4 members co-moving           n=1036   +0.526    nothing
#     6 members co-moving           n= 417   +0.925
#     8 members co-moving           n= 149   +0.763
#
# So it counts only when SIX or more move together. At four it is
# indistinguishable from an ordinary mover, and a rule built on four
# would have been wrong.
SECTOR_CO_MOVE_IS_A_REASON = True


def is_a_reason(text):
    """True when `text` is a mechanism a human could act on.

    One function, both lanes. Deliberately dumb: it checks that words
    exist and that they are not the matcher talking about itself. It
    does NOT judge whether the reason is a good one -- nothing here has
    ever been measured against price, and pretending otherwise is the
    kind of unearned confidence BOT_SPEC.md's one hard rule forbids.
    """
    if not text:
        return False
    low = str(text).strip().lower()
    if len(low) < MIN_REASON_CHARS:
        return False
    return not any(bad in low for bad in NOT_A_REASON)

# Where in its own day range the stock is sitting. Below half and the
# move is over -- this is the "is it still an opportunity" test.
FADED_FROM_HIGH = 0.5

# ==========================================================
#  A BREAKOUT MAKES THE HIGH. IT DOES NOT RETURN TO IT.
# ==========================================================
#
#     "bot alert system unable to identify the difference of fresh
#      breakout or fall backs ... this stock had made high 8300 rs &
#      fell to current levels. MAKE SURE THE BOT LEARN ABOUT THESE
#      BREAKOUTS."
#                                 -- operator, 18 August 2026
#
# NAVINFLUOR, 12:30 that day. The alert read STRUCTURAL_LONG_BREAKOUT
# at 8240. The day's numbers:
#
#     open 8155   HIGH 8300   low 8151   ltp 8247   +1.18%
#
# 8240 is 0.72% BELOW a high the stock had already printed. The move
# had happened and come back; the alert called it a breakout.
#
# WHY IT PASSED. The structural path measures the break against the
# ORB -- the 09:15-09:30 opening range, NAVINFLUOR's being
# high 8230 / low 8151. That range is fixed at 09:30 and never moves
# again, so ANY later re-cross of 8230 reads as a fresh break of it,
# including the third one, including the one after the real move has
# already failed. _is_still_trending() was the only thing standing in
# the way and it asks a different question -- position inside the day
# range, generous at 0.65 -- which a 0.72% pullback clears.
#
# This is the missing question, asked directly: is this close AT the
# day's extreme, or under one that is already history? A breakout
# candle closes within a whisker of the high it just made. 0.72% is
# not a whisker; it is a stock that went there and came back.
BREAKOUT_MAX_OFF_HIGH_PCT = 0.25


# ==========================================================
#  SIZE OF THE POND
# ==========================================================

# A stock must trade at least this much on an average day, or the
# operator IS the volume and getting out costs more than getting in.
# ---- SIZED FOR SOMEONE ELSE'S ACCOUNT. 21 August 2026 ----
#
#     "2 - too thin ? we are trading with most max - 100 qty right?"
#
# He was right, and the old justification was arithmetically wrong.
# It read: "at Rs 1.2 lakh of MTF buying power a stock doing Rs 3
# crore a day means the operator IS the volume". Rs 1.2 lakh of Rs 3
# crore is 0.4% of a day. He is nowhere near being the volume.
#
# 21 August this refused THOMASCOOK at +12.81% -- ADV Rs 6.26 cr,
# under the Rs 8 cr bar. His actual size in it:
#
#     100 shares x 113.62 = Rs 11,362  =  0.018% of a day
#
# WHAT THE NUMBER SHOULD BE, FROM HIS BOOK
#
#     purse           Rs   93,463
#     MTF ~3x         Rs 2,80,000 of buying power
#     3 seats         Rs   93,000 a position, at the very most
#
# To stay under 1% of a stock's daily turnover he needs an ADV of
# Rs 0.93 cr. Rs 2 cr keeps his largest possible position under HALF
# a percent of the day, which is the point the gate was built to
# protect -- getting out costing more than getting in.
#
# Raise it again when the account does. It is a function of HIS size,
# not a property of the market, and it was never re-derived when the
# account was.
MIN_LIQUIDITY_CR = 2.0

# What a stock must average per day to enter the universe at all.
#
# NOT the same rule as config.MIN_TURNOVER_RS, which is Rs 2 Cr TRADED
# SO FAR TODAY and is read by core/engine.py's liquidity floor. One is
# a property of the stock, the other a property of the session. They
# looked like a disagreement and are not, so both survive -- named
# apart here so nobody merges them.
MIN_UNIVERSE_TURNOVER_RS = 50_000_000

# How many positions may be open at once.
MAX_OPEN_POSITIONS = 3


# ==========================================================
#  THE CLOCK
# ==========================================================

# The early lane: Row 1 only, graded overnight, before the ranker has
# any tape to read.
EARLY_ENTRY_FROM = "09:15"
FIRST_NEW_ENTRY = "09:30"

# After this, a new position has no room left to work.
LAST_NEW_ENTRY = "15:15"


# ==========================================================
#  SCORING WEIGHTS -- TWO SCALES, DELIBERATELY APART
# ==========================================================
#
# core/ranker.py and core/select.py score on different scales. They
# shared the name W_VOLUME and disagreed (2.5 vs 1.00), which read as
# a bug and is not one. Named apart so nobody "fixes" it again.

RANKER_W_EXCESS_SECTOR = 3.0    # beating its own sector
RANKER_W_SECTOR_LEAD = 1.5      # its sector beating the market
RANKER_W_VOLUME = 2.5           # money behind the move
RANKER_W_MECHANISM = 2.0        # strength of the named reason
RANKER_W_PERSISTENCE = 1.5      # still moving now

SELECT_W_VOLUME = 1.00
SELECT_W_EXTENDING = 0.80
SELECT_W_MOVE = 0.50
SELECT_W_CARD = 0.60


# ==========================================================
#  THE ROLL OF NAMES THE TEST GUARDS
# ==========================================================
#
# tests/test_rules_are_not_duplicated.py reads this list and fails if
# any core module declares one of these names itself. That is what
# stops the sediment growing back.
OWNED = (
    "RISK_PER_TRADE_RS",
    "MTF_MARGIN_PER_POSITION_RS",
    "MIN_TRADABLE_PRICE_RS",
    "MIN_STOP_DISTANCE_PCT",
    "MAX_STOP_DISTANCE_PCT",
    "MIN_REWARD_MULTIPLE",
    "MIN_MOVE_FROM_PREV_CLOSE_PCT",
    "MIN_MOVE_FROM_OPEN_PCT",
    "SHORTLIST_MIN_MOVE_PCT",
    "MIN_MOVE_PCT",              # the old shared name -- must not return
    "MIN_VOLUME_RATIO",
    "UNEXPLAINED_MIN_VOLUME_RATIO",
    "UNEXPLAINED_WEIGHT",
    "FADED_FROM_HIGH",
    "MIN_LIQUIDITY_CR",
    "MIN_UNIVERSE_TURNOVER_RS",
    "MAX_OPEN_POSITIONS",
)

# core/engine.py's own MIN_TURNOVER_RS (Rs 2 Cr traded so far today)
# and core/subscribe_list.py's derived one are DIFFERENT rules and are
# not owned here. Listed so the next person does not "tidy" them in.
NOT_OURS = ("MIN_TURNOVER_RS", "MIN_STOP_DISTANCE_PCT_AS_FRACTION")
