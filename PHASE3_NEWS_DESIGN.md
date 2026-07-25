# Phase 3: News Intelligence & Sell-Side Design Notes

Status: DESIGN LOCKED (pending final build). Nothing in this document is live code yet.
This captures every decision made in design discussion so nothing gets lost or re-argued.

---

## 1. Trading Rules Confirmed

### 1.1 End-of-day square-off
- ALL open positions -- long AND short -- must be force-closed by **15:15 IST**, no exceptions,
  regardless of P&L. This extends the existing EOD square-off loop (already in main.py for longs)
  to also cover shorts.
- Equity intraday short-selling in India legally cannot carry overnight (cash segment). This is a
  hard compliance constraint, not just a strategy choice.

### 1.2 Sell side (short) -- symmetric to buy side
- Entry trigger (structural): price breaks below (ORB low - buffer), mirroring the existing
  (ORB high + buffer) buy trigger exactly.
- Stop loss: high of the candle that confirms the breakdown (mirrors a candle-based stop
  concept for longs too -- to be applied symmetrically once Phase 2 formally starts).
- Two separate short setups, tracked independently (see 1.4):
  1. **Structural short** -- pure ORB-low breakdown, NO news requirement. Exists so the bot can
     still catch bearish moves that have no visible news yet (see Concern #2 below).
  2. **News-confirmed short** -- same structural trigger, but only arms/fires if a HIGH-priority
     bearish news item exists for that stock that session (see Section 3).
- Position sizing for shorts: same fixed qty = 1 as current buy side, until Phase 2 sizing exists.

### 1.3 Exit method -- trailing stop replaces fixed 1:1 R:R
- Lesson learned (user's own past experience): a fixed 1:1 target/stop bracket cut winners short
  and got medium-momentum trades stopped out on noise before the real move developed.
- New rule: NO fixed target. Use the candle-based structural stop to enter, then trail:
  - Longs: trail stop up to below each new higher low as price rises.
  - Shorts: trail stop down to above each new lower high as price falls.
- Trade exits only when the trailing stop is hit, or forced by the 15:15 EOD square-off --
  whichever comes first.
- Exact trailing formula (candle-based vs ATR-based vs percentage-based) -- candle-based is the
  working assumption; final confirmation pending before code is written.

### 1.4 Structural vs News-confirmed setups tracked separately
- Every trade must be tagged with which setup produced it (structural-long, structural-short,
  news-confirmed-short, later: news-confirmed-long if added, first-15-min-momentum if built).
- Reason: so performance of each setup type can be evaluated independently. Do not let
  news-gating silently replace pure structural logic -- prove each piece on its own.

---

## 2. Deferred / Separate Scope Items

### 2.1 First-15-minute momentum setup
- Some stocks rally hard inside the ORB range-formation window itself (before the range is even
  complete). Classic ORB logic correctly excludes these -- the range isn't done forming, so there's
  nothing to break out of yet. This is not a bug in ORB; it's a different pattern entirely.
- Decision: this needs its own separately-built and separately-tracked setup (e.g., detects
  unusual price move + volume within the opening window), NOT a modification to ORB itself.
  Scope and build only after core buy/sell sides are proven. Not started yet.

### 2.2 Market-regime routing (bullish / flat / bearish)
- Concept: classify each session's regime and route setup eligibility accordingly --
  bullish regime -> only buy-side setups eligible; bearish -> only sell-side; flat/unclear ->
  require BOTH structural trigger AND matching-direction news confirmation (stricter bar) before
  taking either side.
- Proposed regime inputs: broad index trend (Nifty/Sensex), breadth across the 750-stock universe
  (advances vs declines), possibly India VIX to separate genuine flat/choppy from quiet-but-trending.
- OPEN QUESTION (unresolved): does "bullish/bearish/flat" mean broad-market regime, or
  per-sector/per-stock regime? Needs user confirmation before this is built.

### 2.3 Results-calendar awareness
- Quarterly results are calendar-predictable (4x/year per company). Plan: preload a results
  calendar so the bot knows in advance which stocks report on a given day, and can treat
  result-day gaps/breakouts with different (likely more cautious) handling than a random
  news-driven move. Not built yet.

---

## 3. News Pipeline Architecture (Phase 3 core)

### 3.1 Two-component design: "News Bot" + "Brain Bot"
User-proposed and confirmed as the right shape:
- **News Bot** = ingestion + classification + triage. Runs independently, fully testable on its
  own, produces categorized/logged output. Never places trades itself.
- **Brain Bot** = the trading engine (ORB + regime + risk logic). Only ever sees HIGH-priority
  news items that News Bot has already filtered and classified. Never sees raw headlines directly.
- This decoupling matches the project's existing philosophy: build and prove each piece in
  isolation before trusting it to influence real decisions.

### 3.2 Pipeline stages inside News Bot

**Stage 1 -- Ingestion (free, RSS-based)**
- Sources: NSE/BSE official announcement RSS (fast, authoritative, company-filing-specific) +
  general financial media RSS (Moneycontrol, Economic Times, Business Standard) for macro/policy
  news that never shows up as a company filing (e.g., tariffs).
- Polling interval during market hours: every 30-60 seconds (honest limitation -- this is
  poll-based, not true instant push; a paid real-time feed would be faster but isn't justified
  until a measured gap proves the free version insufficient).

**Stage 2 -- Matching (free, rule-based, no AI cost)**
- Every incoming headline is checked against the verified master database: SECTOR, INDUSTRY,
  KEYWORDS, THEMES, COMMODITY_EXPOSURE, COMPANY NAME.
- No match to any of the 750 stocks/sectors -> classified **DUMMY**, discarded immediately.
  Zero AI spend on pure noise. (Majority of raw headlines end here.)

**Stage 3 -- AI Classification (paid, Claude Haiku, only for Stage 2 survivors)**
- For each matched candidate: send headline + the matched company's verified profile fields
  (SECTOR, OWNERSHIP, COMMODITY_EXPOSURE, ECONOMIC_SENSITIVITY) to Claude Haiku.
- Returns: direction (bullish / bearish / neutral), confidence, and which specific company fact
  justified the call (auditability -- so every classification is explainable, not a black box).

**Stage 4 -- Priority tiering**
- Two independent axes, not one nested structure:
  - **Priority**: DUMMY (stage 2 reject) / MID (matched but low confidence, low materiality, or
    neutral) / HIGH (matched + high confidence + material event type, e.g. tariff, regulatory
    action, M&A, major contract -- not a routine/minor filing).
  - **Direction**: bullish / bearish / neutral -- recorded on MID items too, not just HIGH.
    Reason: MID-tier items must not be thrown away. They're exactly the kind of data needed to
    later research Concern #2 (silent movers -- stocks that moved before news became "obviously"
    high priority). Keep and log everything; only decide what's ACTIVELY PUSHED based on priority.
- Only items where priority == HIGH are pushed onward to Brain Bot. DUMMY and MID are logged for
  audit/backtesting but do not influence live trading.

### 3.3 Interface -- how News Bot reaches Brain Bot
- Decoupled via a shared local queue/log (e.g., a lightweight file or local DB table that News
  Bot writes HIGH-priority items to, and Brain Bot polls during its own tick loop) -- not a direct
  function call. Keeps News Bot independently testable/runnable without touching the trading
  engine, consistent with how the rest of this codebase is already split into independently
  tested modules (core/, trading/, tests/ per module).

### 3.4 How this resolves earlier concerns
- **Concern #1 (news timing/types)**: results are calendar-predictable (handled separately, see
  2.3); company filings are near-real-time via NSE/BSE RSS; general news has more variable lag --
  addressed honestly above, free-tier limitation acknowledged.
- **Concern #2 (silent movers, no news yet)**: solved by NOT requiring news for the structural
  short (1.2) or the existing structural long -- pure price action still catches these regardless
  of news presence. News-confirmed short is a separate, higher-conviction addition, not a
  replacement.
- **Concern #4 (market sentiment routing)**: separate module (2.2), not yet built, open question
  on scope (broad market vs per-sector) pending user answer.
- **Concern #5 (1:1 R:R issue)**: resolved via trailing-stop redesign (1.3).

---

## 4. Cost estimate (for reference)
- Claude Haiku 4.5: $1/M input tokens, $5/M output tokens.
- Estimated realistic load: 300-500 AI classification calls/day (after free matching layer
  filters out non-candidates) -> roughly $5-15/month (~₹480-1,450/month at ~₹96.4/USD),
  scaling with actual news volume. Daily call cap to be added in code so cost cannot run away
  unexpectedly.
- Compared to StockInsights.ai (India-specific corporate filings API, considered and rejected
  for now): ₹60,000-72,000/year fixed subscription. Free RSS + own matching + AI classification
  chosen instead -- cheaper, fully auditable, and doesn't blind-trust a third party's tagging.

---

## 5. Status / Next Steps
- [x] Confirm exact trailing-stop formula -- candle-based, confirmed. Built for BOTH LONG and
      SHORT, mirrored (2026-07-23: shorts added to the engine). `core/trailing_stop.py`: a
      LONG's initial stop = low of the breakout candle itself, then ratchets up (never down) to
      the lowest low of the last `TRAILING_STOP_WINDOW_CANDLES` (5, tunable in config.py) closed
      candles; a SHORT's initial stop = high of the breakdown candle itself, ratchets down
      (never up) to the highest high of the same window -- a rolling window either way, not just
      the latest candle, specifically to avoid the same "cuts winners short on noise" failure as
      the old fixed 1:1 R:R. No fixed target, same as decided here. Exit trigger is TICK-TOUCH,
      not candle-close -- confirmed with the operator: entries wait for close confirmation, but a
      stop's job is capital protection and must fire immediately on breach. 13 tests
      (`tests/test_trailing_stop.py`) + wired into `core/engine.py` with its own tests. State
      persists across a restart (`core/state_store.py`) so a crash mid-trade doesn't lose how far
      the stop had ratcheted, in either direction.
- [ ] Confirm market-regime scope (broad market vs per-sector) before building 2.2
- [x] Build News Bot Stage 1 -- ingestion (RSS). `news_bot/ingestion.py` + `news_bot/sources.py`
      + `news_bot/models.py`. 6 tests in `tests/test_news_ingestion.py`, all passing. Per-source
      fetch/parse failures are isolated and logged loudly, never silent, never crash the whole run.
- [x] Build News Bot Stage 2 -- matching (rule-based, free, no AI). `news_bot/matching.py`.
      7 tests in `tests/test_news_matching.py`, all passing, run against the real 750-row
      master_stocks.csv. Two tiers: COMPANY (SYMBOL / COMPANY NAME hit -> single stock, high
      confidence) and BROAD (SECTOR / INDUSTRY / KEYWORDS / THEMES / COMMODITY_EXPOSURE hit ->
      many stocks, lower per-stock confidence). No match -> DUMMY, zero AI spend.
  - RSS source list corrected using REAL evidence from the previous bot (orb-auto-trader),
    which actually ran on the real trading machine, not a cloud sandbox: ECONOMIC_TIMES and
    LIVEMINT confirmed working -- enabled. MONEYCONTROL confirmed broken (persistent
    invalid-feed error even with a proper browser header) -- disabled by default.
    BUSINESS_STANDARD confirmed broken (explicit HTTP 403 Forbidden even with a proper header)
    -- disabled by default. (Claude's own dev-sandbox test found the opposite for Moneycontrol/
    Business Standard vs ET -- that sandbox result is NOT trusted; it's a different network
    with different rules than the machine the bot runs on.) Full detail in `news_bot/sources.py`.
  - NSE + BSE corporate announcements are NOT fetched via RSS/XML at all -- that approach was
    tried by the previous bot (`adapters/nse_adapter.py`) and never got past a stub, and was
    independently re-confirmed broken in this build's own sandbox testing (unparseable/binary
    responses, blocked connections). Instead, `news_bot/exchange_announcements.py` uses the
    `nse` and `bse` PyPI packages (BennyThadikaran's NseIndiaApi / BseIndiaApi) -- the SAME
    packages the previous bot already proved working for results-calendar data
    (`collectors/results_calendar_collector.py`). Both expose a general `.announcements()`
    method for corporate filings, which this module uses, with real field names confirmed from
    each package's own published GitHub sample response (not guessed).
    NSE gives the exact stock symbol directly per filing (`symbol` field) -- that's passed
    through as `NewsItem.known_symbol`, so Stage 2 treats it as ground truth instead of
    guessing from text. BSE gives a BSE-specific numeric scrip code, not an NSE symbol, so BSE
    items fall through to normal text matching against the company name/headline (same
    limitation as general news).
    KNOWN RISK, carried over from the previous bot's own hard-won lesson
    (`tools/news_pipeline_check.py`): NSE and BSE have both been observed refusing connections
    from cloud/datacenter IPs (this build's sandbox got `ProxyError`/`ConnectionError` from
    both; the previous bot's Railway deployment saw the same for BSE). This has only been
    confirmed failing from cloud/sandboxed origins, NOT from a normal home/residential IP --
    which is what this bot runs from in PAPER mode. `EXCHANGE_NSE_ENABLED` /
    `EXCHANGE_BSE_ENABLED` flags in `news_bot/config.py` let either be switched off in one line
    if the first real run proves one unreliable.
  - Known limitation, documented in `news_bot/matching.py`: many COMPANY NAME values in the
    master DB are abbreviated/truncated as stored in the Dhan scrip master (e.g. "ZF COM VE
    CTR SYS IND LTD"), not full legal names a real headline would use -- so SYMBOL and
    SECTOR/INDUSTRY/KEYWORDS/THEMES/COMMODITY matching carry more of the real-world load than
    exact company-name phrase matching does, for now.
- [x] Build News Bot Stage 3 -- AI classification (Claude Haiku, paid, only for Stage 2
      survivors). `news_bot/classification.py`. Model: claude-haiku-4-5-20251001. Returns
      direction/confidence/materiality/reason, strictly validated -- a bad/unparseable
      response raises ClassificationError, never a guessed default. 9 tests, all passing,
      no real network calls (injected fake client). Daily spend capped by
      `news_bot/call_budget.py` (persisted, date-tagged JSON counter -- survives a restart,
      per MAX_AI_CALLS_PER_DAY in news_bot/config.py). 5 tests.
- [x] Build News Bot Stage 4 -- priority tiering. `news_bot/priority.py`. HIGH requires
      confidence >= 70 AND materiality == material AND direction != neutral, all three;
      anything else matched is MID, never discarded. 7 tests.
- [x] Build News Bot -> Brain Bot interface (shared log/queue). `news_bot/news_queue.py` --
      every MID+HIGH item appended to an audit log (backtesting later); HIGH items also
      appended to a separate queue file. `NewsQueueReader` is the Brain-Bot-side reader,
      date-scoped to today only. 5 tests. `news_bot/pipeline.py` orchestrates ingest ->
      match -> classify (budget-capped) -> tier -> record as one poll cycle, run every
      POLL_INTERVAL_SECONDS by main.py's own news thread. 5 tests.
- [x] Wire Brain Bot to consume HIGH-priority items -- `core/news_gate.py` (`NewsGate`) is
      the ONLY bridge into `core/engine.py`, and stays a thin reader: it never decides
      anything itself. UPDATE (2026-07-23, operator-approved): the veto step originally
      deferred here is now built, deliberately scoped tight -- `core/engine.py`'s
      `_try_structural_entry()` blocks a structural signal ONLY when that exact symbol has a
      same-day HIGH item pointing the OPPOSITE direction (e.g. bearish news vs a bullish
      breakout). It blocks just that one direction, for that one symbol, for the rest of the
      day -- a later signal in the OTHER direction (agreeing with the news) still trades
      normally. Manual dashboard buys bypass this entirely (explicit operator override). Paired
      with a second, breadth-only check -- `core/sector_monitor.py` flags a sector as broadly,
      sharply declining and blocks new LONG entries there (never SHORT) -- both because "we can
      buy or sell the affected stocks... no need to fight with markets" (operator's own framing
      for why this isn't a blanket news veto). Both blocks persist across a restart
      (`core/engine.py`'s `entry_blocked`, via `core/state_store.py`) and are visible on the
      dashboard's Risk Filters panel. Tests: `tests/test_news_gate.py`,
      `tests/test_sector_monitor.py`, and the news/sector sections of `tests/test_engine.py`.
- [ ] First-15-min momentum setup -- deferred, separate build later
- [ ] Results calendar integration -- deferred, separate build later
