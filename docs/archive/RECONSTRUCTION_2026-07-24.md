# Trading Reconstruction — 2026-07-24 (PAPER)

Rebuilt from `logs/trade_log.csv` by pairing every entry to its exit(s)
per symbol (handling partial exits), with the real charge model applied.
This was a LIVE PAPER session that ran on the MORNING code — most of the
fixes below were built *after* close, so this is a clean "before" picture.

## Headline

| Metric | Value |
|---|---|
| Round-trip trades | 201 (122 LONG, 79 SHORT) |
| Win rate | 41.8% (84 win / 100 loss / 17 flat) |
| Gross P&L | **−₹76,314** |
| Est. charges | −₹15,953 |
| **Net P&L** | **−₹92,268** |
| Avg win / avg loss | ₹243 / −₹968 |
| Profit factor | 0.21 |
| LONG / SHORT P&L | −₹64,237 / −₹12,078 |

## The day in one line

**One manual click lost ₹53,100 — 70% of the entire day's loss.**

APARINDS, MANUAL BUY at 12:44:19, flat **100 shares @ ₹14,610 = ₹14.6 lakh
notional on a single click**. It fell ₹531/share in ~5 minutes and the
trailing stop closed it at 14,079 → **−₹53,100**. This is two known bugs
firing at once:
1. **Unguarded manual size** — flat 100 qty, no notional cap (Audit #1).
2. **Earnings-day spike** — APAR is the exact APAR-class risk the earnings
   filter is meant to catch.

For contrast, the *structural* APAR entry the same day was ATR-sized to
**3 shares** — a rounding error. The damage came entirely from the manual
flat-100 path.

**Strip APAR out and the day's gross is −₹23,214**, not −₹76,314.

## What the rest of the numbers say

- **Losers run ~4× bigger than winners** (avg loss ₹968 vs avg win ₹243,
  profit factor 0.21). Winners are cut short, losers given room — the
  asymmetry the ATR→structure stop redesign targets.
- **Longs were the pain** (−₹64k vs −₹12k short). In a broadly weak tape,
  long breakouts kept failing.
- **Churn:** 36% of trades (72 of 201) were held <1 minute for −₹6,985 —
  the manual-exit / Exit-All instant churn. 133 of the exit legs were
  MANUAL_EXIT.
- **Overtrading drag:** 201 round trips → ₹15,953 in charges (~₹79/trade).
  Trade count itself is a cost.
- **Timing:** 60 structural entries in the 09:00 hour (open burst) and 81
  in the 14:00 hour — a heavy afternoon push, against the "moves exhaust by
  ~10:30" insight. No structural entries after 15:15 (square-off held).
- **Circuit exits worked:** 12 CIRCUIT_PROXIMITY exits fired cleanly.

## Top winners / losers

Winners: MOTILALOFS SHORT +₹2,695 · UNITDSPR LONG +₹2,500 · LAURUSLABS
LONG +₹1,100 · AEGISLOG SHORT +₹1,000 · HEG LONG +₹960.

Losers: **APARINDS LONG −₹53,100** · ENDURANCE SHORT −₹2,600 · JSLL SHORT
−₹2,335 · IMFA SHORT −₹1,420 · DATAPATTNS LONG −₹1,350 (held 0.3 min).

## What's already fixed vs. this session

- **Manual sizing cap (DONE).** Manual entries now route through risk-based
  qty + the ₹2L notional cap. On APAR that caps ~14 shares instead of 100 →
  the ₹53,100 loss becomes ~₹7,400. **This single fix reclaims ~₹45k of
  today's loss.**
- **Wider stops / trail-activation (DONE)** — addresses winners being cut.
- **Square-off entry leak (DONE)** — held today.

## Re-simulation under CURRENT dynamic settings (verification only)

Re-ran today's trades with the current sizing rules (risk ₹2,000 / 1% stop,
₹2L notional cap, ₹200 min price), **holding each trade's real entry & exit
prices** and only re-sizing quantity. Caveat, operator-flagged: today's real
session was muddied by restarts, lag and code errors — this is a deliberate
sanity check of the sizing changes, NOT a verdict on the strategy.

| | Actual (as traded) | Re-sim (current sizing) |
|---|---|---|
| Gross P&L | −₹76,314 | **−₹28,182** |
| Charges | −₹15,953 | −₹22,302 |
| Net P&L | −₹92,268 | **−₹50,483** |
| Trades | 201 | 190 (11 dropped, <₹200) |
| Avg notional | mixed (flat-100/fixed) | ₹199,205 |

- **APARINDS: −₹53,100 → −₹6,903** (qty 100 → 13, capped at ₹2L). The single
  biggest effect — the sizing cap defuses the blowup.
- **Flat-100 momentum-test batch (91 trades): −₹65,525 → −₹19,780.**
- **Still a losing day.** With prices held, the entries/exits themselves lost;
  bigger size amplified winners (MOTILALOFS +₹5,902, HEG +₹2,995) AND losers
  (SHRIRAMFIN −₹4,450, JLHL −₹3,823). The net improvement is almost entirely
  the APAR cap, not better signals.
- **Charges rose to ₹22,302** — sizing everything to ₹2L raises turnover; 190
  trades is over-trading.

**Limitation:** only QUANTITY was re-sized. Real entry/exit PRICES were held,
so dynamic stops/targets (2.5×ATR trail, partial exits) would change the exit
prices — especially the momentum-test trades that ran fixed ₹1000/₹2500
brackets. A true replay needs today's candle/tick data from `diagnostics.log`
(a mini-backtest) — not done here.

## What this session argues for next (backlog)

1. **Earnings "violence" filter (#2)** — APAR must never be manually or
   structurally buyable on a spike day. Needs the full earnings list (#12).
2. **ATR→structure stops (#1)** — fix the 4:1 loss:win asymmetry.
3. **Fewer, better trades** — 201 round trips / ₹16k charges is overtrading;
   ties to signal prioritization (#5) and the churn/re-entry controls.
