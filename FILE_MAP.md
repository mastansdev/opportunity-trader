# Every file in the bot, and what it does

126 python files. Grouped by job. Line counts show where the weight is.

## BROKER & ORDERS -- talks to Dhan, places and tracks real orders

| file | lines | what it does |
|---|---|---|
| `trading/live_execution.py` | 668 | LIVE execution -- real orders, real money |
| `core/broker_sync.py` | 504 | Does the bot's book match the broker's? |
| `trading/broker_stop.py` | 491 | A stop that survives this process dying |
| `core/dhan_auth.py` | 353 | The bot mints its own Dhan token |
| `trading/trade_controller.py` | 283 | Manual override control. Structural breakouts (core/strategy.py) |
| `core/adopt_positions.py` | 278 | Every position gets a stop -- including the ones he opened |
| `core/mtf_margin.py` | 254 | MTF margin -- ask Dhan, never guess |
| `core/fill_log.py` | 231 | Every fill: what we wanted, what we got |
| `trading/portfolio.py` | 204 | Portfolio -- Paper Capital Ledger + MIS Buying Power |
| `core/headroom.py` | 181 | How far can this stock still go today? |
| `trading/charges.py` | 164 | Transaction cost model -- intraday AND overnight/MTF |
| `core/capital.py` | 162 | How much may be deployed, and how much never moves |
| `core/broker_funds.py` | 153 | How much money is actually there |
| `core/order_route.py` | 138 | The one connection that must leave from the static IP |
| `trading/slippage.py` | 133 | Slippage -- what a paper fill actually costs |
| `trading/trade_logger.py` | 86 | Appends every trade to trade_log.csv. One file, one format, |
| `trading/paper_execution.py` | 83 | Paper fills. Equity only -- no segment parameter exists anywhere in this |
| `trading/execution.py` | 67 | Single gateway all buy/sell requests pass through. The Engine never |

## PRICES & CANDLES -- gets live and historical price data

| file | lines | what it does |
|---|---|---|
| `core/market_data.py` | 499 | Market Data |
| `core/history_fetch.py` | 391 | History Fetch -- years of real market, from Dhan |
| `core/delivery.py` | 359 | Delivery percentage -- who is buying to KEEP |
| `core/feed_store.py` | 317 | One store for the two feeds, so main.py can stop polling |
| `core/nse_quotes.py` | 282 | NSE's own numbers -- the reference the bot is judged against |
| `core/feed_clock.py` | 277 | One clock, and a mark for how far the feed has read |
| `core/liquidity.py` | 275 | Which names are actually tradeable |
| `core/daily_store.py` | 211 | Daily Store -- one candle per stock per day |
| `core/feed_watch.py` | 163 | Which subscriptions actually delivered anything |
| `core/tick_ohlc.py` | 153 | The exchange's own OHLC, arriving on every tick, unused |
| `core/candle_engine.py` | 149 | Candle Engine |
| `core/candle_recorder.py` | 141 | Candle Recorder -- clean OHLCV corpus for the replay bench |
| `core/atr.py` | 89 | ATR -- Average True Range (pure logic, no I/O) |

## WHAT TO WATCH -- builds the list of stocks to follow

| file | lines | what it does |
|---|---|---|
| `core/shortlist.py` | 1,655 | Shortlist -- the names worth the operator's attention, live |
| `core/ranker.py` | 872 | The best stock of the day, not the first one to trigger |
| `core/subscribe_list.py` | 568 | Subscribe List -- the pre-market YES/NO gate |
| `core/watchlist_builder.py` | 466 | The watchlist builds itself, in the order he reads it |
| `core/premarket.py` | 438 | Pre-market picture -- what happened while India slept |
| `core/preopen.py` | 416 | The pre-open session -- 09:00 to 09:08, previously invisible |
| `core/gappers.py` | 401 | The gapper card is a reason. Read it as one. |
| `core/select.py` | 339 | The move leads. The card supports. The grade never gates. |
| `core/universe_builder.py` | 323 | Universe Builder -- keep the tradeable list honest |
| `core/index_members.py` | 316 | Which stocks are in NIFTY 50, and which are in F&O |
| `core/watchlist.py` | 314 | The watchlist -- what has a catalyst today, and why |
| `core/sector_map.py` | 275 | From a sector index to the stocks inside it |
| `core/master_loader.py` | 229 | Master Loader |
| `core/watchlist_store.py` | 183 | The watchlist -- results today, and whatever he adds |
| `core/momentum_universe.py` | 171 | Momentum Universe |
| `core/instrument_master.py` | 117 | Instrument Master |

## ENTRY -- decides when to buy

| file | lines | what it does |
|---|---|---|
| `core/engine.py` | 5,043 | Engine -- Layer 1 |
| `core/auto_entry.py` | 625 | The ranker's picks reach the order path -- the missing join |
| `core/chain.py` | 566 | The six layers, as one line |
| `core/orb_engine.py` | 387 | ORB Engine |
| `core/breakout_feed.py` | 361 | Fresh breakouts -- the window that never existed |
| `core/shock.py` | 296 | Something big just happened |
| `core/rules.py` | 283 | core/rules.py  --  every trading threshold, in one place |
| `core/canslim.py` | 263 | Layer 06 -- the actionable setup, as THEY grade it |
| `core/runup.py` | 222 | Was the good news already bought before it was announced? |
| `core/trend_structure.py` | 211 | Trend Structure -- what shape has this stock been making? |
| `core/strategy.py` | 146 | Strategy -- Layer 1 |

## EXIT, STOPS & TRAILS -- decides when to sell

| file | lines | what it does |
|---|---|---|
| `core/circuit_monitor.py` | 484 | Circuit Monitor |
| `core/trailing_stop.py` | 353 | Trailing Stop -- Longs AND Shorts, mirrored |
| `core/exit_plan.py` | 286 | Where the stop goes, and how far the target can be |
| `core/closed_book.py` | 193 | The closed book -- every trade, whoever placed it |
| `core/position_plan.py` | 181 | Where you get out, and what it costs if you are wrong |

## RESULTS & NEWS -- reads earnings cards and filings

| file | lines | what it does |
|---|---|---|
| `core/news_impact.py` | 956 | News -> which stocks it helps, which it hurts |
| `core/result_read.py` | 926 | Read the WHOLE card, not the headline |
| `core/results_calendar.py` | 650 | Results Calendar -- who reports, when, and (eventually) at what TIME |
| `core/quarterly_results.py` | 608 | Quarterly Results -- did the numbers actually get BETTER? |
| `core/concall.py` | 546 | The concall card -- what management actually said |
| `core/news_watcher.py` | 530 | High-conviction news -- only what can move a stock |
| `core/results_pdf.py` | 504 | Read the numbers out of a results PDF |
| `core/subject.py` | 460 | Is this card ABOUT the stock, or does it merely mention it? |
| `core/image_text.py` | 390 | Reading the text inside a picture |
| `core/news_table.py` | 377 | One row per stock, not one row per message |
| `core/ai_news.py` | 372 | One story, one company, one verdict |
| `core/catalysts.py` | 366 | Order wins and business updates -- the reasons nobody read |
| `core/supply_events.py` | 363 | Huge volume that is SUPPLY, not demand |
| `core/announcement_watcher.py` | 357 | Announcement Watcher -- news while the market is still open |
| `core/pulse_ratings.py` | 308 | The publisher's own rating system, as the publisher defines it |
| `core/ai_budget.py` | 281 | The AI bill -- counted, capped, and refused at the ceiling |
| `core/results_gate.py` | 276 | Results gate -- block BEFORE the numbers, allow AFTER good ones |
| `core/corporate_actions.py` | 252 | Corporate Actions Fetcher -- fills the Stock Memory |
| `core/results_ingest.py` | 242 | Filing lands -> numbers on the dashboard, same minute |
| `core/ai_verdict.py` | 224 | Layer 04 -- the audit that overrules the algorithm |
| `core/margin_driver.py` | 224 | Where the margin came from -- operations, or the whole sector at once |
| `core/pulse_grid.py` | 199 | The numbers the channel already gave us |
| `core/result_tag.py` | 178 | One word per stock: EXCELLENT, GOOD or AVOID |
| `core/deal_flow.py` | 173 | Deal Flow -- who bought size yesterday |

## TELEGRAM -- pulls the publisher channels

| file | lines | what it does |
|---|---|---|
| `core/telegram_feed.py` | 1,696 | The Telegram channels, on the dashboard instead of a screen |
| `core/telegram_client.py` | 509 | The actual connection to Telegram |
| `core/telegram_web.py` | 278 | Reading public Telegram channels with no credentials |
| `core/forwarded_card.py` | 226 | Reading a FORWARDED card without tagging the wrong stock |

## MARKET CONTEXT -- what the whole market is doing

| file | lines | what it does |
|---|---|---|
| `core/why_moving.py` | 626 | Why is this stock moving? Ask BOTH stores, best answer wins |
| `core/awareness.py` | 480 | Market Situational Awareness |
| `core/market_flows.py` | 379 | FII / DII flows -- who is actually buying |
| `core/centre.py` | 345 | THE CENTRE -- one refined record per stock |
| `core/market_calendar.py` | 337 | Market Calendar -- the bot knows when the market is shut |
| `core/market_sentiment.py` | 258 | Did the market agree? -- the post-earnings sentiment page |
| `core/econ_calendar.py` | 217 | The dates that move the whole market at once |
| `core/reaction.py` | 203 | What the market did with the news |
| ~~`core/week_ahead.py`~~ | — | **Deleted 12 Aug 2026** — imported by nothing. The "week ahead" card is handled by `core/subject.py`, which correctly treats a 155-company list as evidence about none of them. |
| `core/sector_monitor.py` | 175 | Sector Monitor |
| `core/index_monitor.py` | 171 | Index Monitor -- Nifty / BankNifty / Midcap / India VIX |

## MEASURING -- did any of it work?

| file | lines | what it does |
|---|---|---|
| `core/session_replay.py` | 775 | Reading a finished session back off the disk |
| `core/outcomes.py` | 651 | What happened AFTER each chip |
| `core/recap_card.py` | 457 | The recap card -- who reported, and when |
| `core/stock_memory.py` | 424 | Stock Memory -- what the bot KNOWS about each of the 750 |
| `core/morning_ready.py` | 332 | Is the bot actually ready to trade this morning? |
| `core/trade_memory.py` | 324 | Trade Memory -- the learning loop (OBSERVATION ONLY) |
| `core/margin_outcomes.py` | 293 | Did SECTOR-WIDE MARGIN ever pay? Measured, not argued. |
| `core/signal_journal.py` | 274 | Every signal the bot saw -- including the ones it refused |
| `core/decision_log.py` | 255 | Every pick the bot would have made, written down |
| `core/reporting.py` | 250 | Who reports today, who reports tomorrow, and when in the day |
| `core/morning_brief.py` | 225 | Morning brief -- the AI layer, finally |

## SCREEN -- the dashboard you look at

| file | lines | what it does |
|---|---|---|
| `dashboard/state.py` | 5,656 | Dashboard State |
| `core/stock_events.py` | 2,466 | What has happened to each stock, and when |
| `dashboard/server.py` | 1,117 | Dashboard Server |
| `core/stock_card.py` | 391 | Everything the bot knows about ONE stock |
| `dashboard/chip_stats.py` | 120 | What each chip is WORTH -- served to the screen, kept off the path |
| `dashboard/access_token.py` | 73 | Dashboard Access Token |

## PLUMBING -- storage, logs, locks

| file | lines | what it does |
|---|---|---|
| `core/state_store.py` | 334 | State Store |
| `core/runlock.py` | 195 | One reader of the Telegram session at a time |
| `core/logger.py` | 147 | Logging -- readable, rotated, and honest about what it drops |
| `core/dhan_time.py` | 72 | Dhan Time |
| `core/db.py` | 36 | Database URL resolution -- shared by every store |

## EVERYTHING ELSE

| file | lines | what it does |
|---|---|---|
| `config.py` | 3,040 | Opportunity Trader — Config |
| `main.py` | 2,101 | Opportunity Trader -- Layer 1 entry point |
