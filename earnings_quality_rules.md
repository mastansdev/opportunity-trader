# Earnings Quality Ruleset v1.0
## Upgrade spec for EarningsPulse — margin-driver attribution layer

**Purpose:** The current bot grades *changes* in P&L line items. That is pattern matching on deltas.
It cannot distinguish a business that got better from a business that got lucky. This ruleset adds
the attribution layer: *why* did margins move, and does the driver persist?

**Regression case used throughout:** PANAMAPET Q1 FY27 (Jun-2026 quarter), which the current bot
graded `Excellent / Clean / Trust is high / No distortions flagged`. Every rule below fires on that
filing. If a rebuilt bot does not flag it, the rebuild failed.

---

## GROUP A — DATA SUFFICIENCY GATES (blocking)

These run first. If a gate fails, downstream quality grades are **capped**, not computed.

### A1. Indian Q1/Q3 filings contain no balance sheet and no cash flow statement
Under SEBI LODR Reg 33, standalone/consolidated balance sheet and cash flow statement are mandatory
only **half-yearly and annually**. Q1 (June) and Q3 (December) filings contain P&L only.

```
IF quarter IN (Q1, Q3) AND market == "IN":
    earnings_quality_grade = min(grade, "UNVERIFIED")
    FORBID emitting "Cash Flow: Healthy" / "Cash Flow: Weak" / any cash flow badge
    FORBID emitting "Earnings Quality: CLEAN"
```

**Bug this fixes:** the brief emitted `Cash Flow: Healthy` for a quarter in which no cash flow
statement exists. That value was fabricated. Last real datapoint for PANAMAPET was FY26:
operating cash flow **−₹69 Cr**, free cash flow **−₹124 Cr**.

### A2. Empty field ≠ clean field
```
IF balance_sheet_signals IS EMPTY:
    FORBID "No distortions flagged"
    EMIT "Balance sheet not filed this quarter — inventory and receivables unverified"
```
Absence of evidence must never render as evidence of absence. The brief printed an empty
`Balance Sheet Signals` box and `Distortion Flags: None flagged` on the same page.

### A3. No estimates means no verdict
```
IF consensus_estimate_count == 0:
    verdict = "NO_CONSENSUS"   # suppress the field entirely
    FORBID verdict IN ("MET", "BEAT", "MISSED")
```
The brief admitted there were no quantitative estimates and then issued `Verdict: MET`.
MET against nothing is not information.

---

## GROUP B — MARGIN DECOMPOSITION (core fix)

### B1. Incremental margin test
```
incremental_margin = (ebitda_curr - ebitda_yoy) / (revenue_curr - revenue_yoy)
IF incremental_margin > 2.5 * median_margin_8q:
    FLAG "ANOMALOUS_INCREMENTAL_MARGIN"
```
**PANAMAPET:** (391.76 − 58.9) / (1735.15 − 693.22) = **31.9%** against an 8-quarter median
margin of ~9%. Ratio **3.5x**. Fires.

A business does not earn 32% on incremental revenue when its through-cycle margin is 9%.
Something other than operations is producing that.

### B2. Operating leverage ceiling test — the decisive one
Operating leverage means fixed costs spread over more revenue. It is **bounded by the size of the
fixed cost base**. This is arithmetic, not judgment.

```
fixed_costs = depreciation + employee_cost + other_fixed_opex   # prior period
fixed_cost_ratio = fixed_costs / revenue_yoy
max_leverage_gain_pp = fixed_cost_ratio * (1 - revenue_yoy / revenue_curr) * 100

observed_gain_pp = (margin_curr - margin_yoy) * 100

IF observed_gain_pp > 3 * max_leverage_gain_pp:
    FLAG "OPERATING_LEVERAGE_INSUFFICIENT"
    FORBID narrative "operational leverage" / "operating leverage realized"
```
**PANAMAPET:** quarterly depreciation ≈ ₹3.5 Cr on prior revenue of ₹693 Cr. Even generously
loading employee and admin cost, fixed costs are ~4% of revenue. Theoretical ceiling on margin
gain from leverage ≈ **2.4pp**. Observed gain = **14.1pp** (8.5% → 22.6%). Ratio **5.9x**. Fires.

The brief's `Implied Outlook: Significant operational leverage realized in Q1` is arithmetically
impossible and must be blocked by this rule.

### B3. Material cost direction test
```
IF rm_pct_of_revenue_prior > 0.70:              # processor / converter economics
    IF rm_pct_curr < rm_pct_prior AND revenue_growth_yoy > 0.50:
        FLAG "MARGIN_SOURCE_PRICE_NOT_OPERATIONS"
```
For a converter, raw material is 85–90% of revenue. If RM falls *as a share of revenue* while
revenue rises 150%, realisations rose faster than input costs. That is an inventory holding gain
or scarcity pricing — not operational improvement.

**PANAMAPET:** the brief listed `Lower material cost as % of revenue` under **Margin Drivers as a
positive**. It is the single strongest disconfirming signal in the filing and was misclassified.

---

## GROUP C — PRICE vs VOLUME DECOMPOSITION

### C1. No volume disclosure, no demand claim
```
IF volume_disclosed == False:
    FORBID narrative tokens: "strong demand", "volume-led", "demand-driven",
                             "core operations", "explosive growth"
    EMIT "Revenue growth not decomposed — volume not disclosed"
```
Revenue growth without volume disclosure cannot be attributed to demand. It may be entirely price.

### C2. Commodity cross-check
```
IF input_commodity_index_change_yoy > 0.50 AND revenue_growth_yoy > 0.50:
    presume "PRICE_DRIVEN" until volume disclosed
```
**PANAMAPET context:** Indian crude basket ran $69 (Feb-26) → $126 (Mar-26), peak $157.
Revenue +150%. Presumption is price until proven otherwise.

---

## GROUP D — PEER CORRELATION (largest single miss)

The current bot analyses one company in isolation. Isolation makes an exogenous shock look like
company execution. This is the most valuable rule in the set.

### D1. Mandatory peer pull before any quality grade
```
peers = same_value_chain_position AND same_4digit_industry   # NOT same broad sector
REQUIRE len(peers) >= 2 before assigning earnings_quality
```

### D2. Correlated margin expansion = exogenous driver
```
correlated = [p for p in peers
              if sign(p.margin_delta) == sign(subject.margin_delta)
              and abs(p.margin_delta) > 0.5 * abs(subject.margin_delta)]

IF len(correlated) >= 2:
    FLAG "SECTOR_WIDE_INPUT_PRICE_EVENT"
    margin_driver = "EXOGENOUS"
    FORBID "core operations" attribution
```
**Q1 FY27 evidence the bot had access to and did not use:**

| Company | Q1 FY27 margin | Year-ago | Reported |
|---|---|---|---|
| Panama Petrochem | 22.6% EBITDA | 8.5% | Aug 12 |
| Savita Oil | 24.76% EBITDA | ~4% | before Aug 12 |
| Gandhar Oil | 16.24% operating | 5.09% | **Jul 23** |

Three unrelated companies tripling margins in the same three months is definitionally not
execution. Gandhar reported **20 days earlier** — the read-through was available before Panama
printed.

### D3. Peer sets must be tagged by value-chain position, not sector
Sector classification puts refiners and converters in the same bucket. They have opposite
economics and different cycle timing.

```
VALUE_CHAIN_TAGS = {
  "REFINER":   ["CPCL", "MRPL", "RELIANCE", "IOC", "BPCL", "HPCL"],   # driver: GRM / crack spread
  "CONVERTER": ["PANAMAPET", "GANDHAR", "SAVITA", "APARINDS"],        # driver: blending spread + inventory
  "BRANDED":   ["CASTROLIND", "GULFOILLUB", "TIDEWATER"],             # driver: brand margin, low commodity beta
}
```
A REFINER is a **supplier** to a CONVERTER, not a peer. CPCL operates a lube-oil-base-stock unit
and sells base oil to companies like Panama. Never cross-compare across tags.

---

## GROUP E — COMMODITY / CYCLICAL LOGIC

### E1. Classify spread businesses
```
IF rm_pct_of_revenue > 0.70 AND rm_is_index_priced:
    business_model = "CONVERTER"   # spread business, not a growth business
```

### E2. For converters, a record margin is a NEGATIVE forward signal
```
IF business_model == "CONVERTER" AND margin_curr == max(margin_history_20q):
    cycle_position = "PEAK"
    forward_bias = "MEAN_REVERSION"
    EMIT "Record margin for a spread business indicates cycle position, not durable improvement"
```
This inverts the current bot's logic and is the point of the whole exercise. Best-ever margin for a
commodity converter is frequently the top tick.

### E3. Inventory days = quarters of price risk carried
```
exposure_quarters = inventory_days / 90

IF input_price_direction == "RISING":  effect = "HOLDING_GAIN"    # transient profit
IF input_price_direction == "FALLING": effect = "HOLDING_LOSS + WRITEDOWN"
```
**PANAMAPET:** 97 inventory days = **1.08 quarters** of base oil carried at historical cost.
Symmetric. The mechanism that produced Q1's windfall produces the loss on the way down.

### E4. Upstream leading indicator
Refiners capture the crack spread in real time. Converters capture it with an inventory lag of
roughly one quarter. **The upstream link turns first.**

```
IF upstream_peer.qoq_profit_change < 0 AND subject.qoq_profit_change > 0:
    FLAG "UPSTREAM_ALREADY_ROLLED_OVER"
    EMIT "Upstream {peer} peaked one quarter earlier — forward risk to next print"
```
**Live example:** CPCL Q1 FY27 PAT ₹1,016.67 Cr, GRM $8.78/bbl vs $3.22 — but **−27% QoQ**.
CPCL peaked in Q4 FY26. Panama peaked in Q1 FY27. One quarter of lag, exactly as the inventory
model predicts. CPCL's Q1 is a preview of Panama's Q2.

---

## GROUP F — NORMALISATION AND VALUATION

### F1. Never annualise a flagged quarter
```
IF any_flag_fired(B1, B2, B3, D2):
    FORBID annualising current-quarter EPS
    FORBID reporting forward P/E on annualised current EPS
```

### F2. Normalise BOTH revenue and margin
Normalising margin alone understates reversion, because in a price event revenue is itself inflated.

```
norm_revenue = trend_revenue_8q * (1 + secular_growth)     # not current revenue
norm_margin  = median_margin_8q
norm_eps     = norm_revenue * norm_margin * (1 - tax_rate) / shares
```
**PANAMAPET worked example:**
- Reported: EPS ₹51.06/qtr → annualised ₹204 → P/E at ₹518 = **2.5x**
- Margin-normalised only (₹1,735 Cr rev × 9%): EPS ≈ ₹80/yr → P/E ≈ **6.5x**
- Fully normalised (₹850 Cr trend rev × 9%): EPS ≈ ₹38/yr → P/E ≈ **13.7x**

Only the third number is decision-useful. Report all three so the user sees the gap.

### F3. Absurdly low P/E is a warning, not a signal
```
IF forward_pe_on_reported < 5 AND sector != "FINANCIALS":
    FLAG "MARKET_IMPLIED_EARNINGS_REJECTION"
    EMIT "Market is pricing these earnings as non-recurring. A 2.5x P/E is the market's
          earnings-quality verdict, and it disagrees with a 'clean' grade."
```
When a stock refuses to re-rate on a 7x profit jump, that refusal *is* the signal.

---

## GROUP G — ONE-OFFS

### G1. Scan and strip
Search filing text and notes for: retrospective price revision, insurance claim, asset/land sale,
forex gain, tax reversal, subsidy, government incentive, exceptional item, prior-period adjustment.

### G2. Always report ex-one-off alongside reported
**Live example:** CPCL's ₹1,016.67 Cr Q1 PAT includes **₹385.21 Cr** of retrospective price
revision for March supplies. Clean PAT ≈ ₹725 Cr. The one-off was disclosed in the filing and is
machine-findable.

---

## GROUP H — SIGNAL HYGIENE

### H1. Delete trivia from red flags
Remove entirely. These have zero informational content and crowd out real signals:
- board meeting duration ("concluded in just 40 minutes")
- filing time of day, PDF page count, filing file size
- number of signatories, auditor firm name changes without qualification

The brief's *only* red flag was meeting duration, while the missing balance sheet, missing cash
flow, missing volume disclosure, and sector-wide margin correlation went unflagged.

### H2. Ban unsupported trust language
```
FORBID_ALWAYS = ["Trust is high", "numbers appear clean", "no distortions",
                 "can be trusted", "verified clean"]
```
Replace with a per-field verification table showing what was checked and what could not be.

### H3. Internal consistency check
```
IF abs(ebitda_margin_computed - ebitda_margin_reported) > 0.2pp:
    FLAG "INPUT_INCONSISTENCY"
```
The two briefs disagreed with each other: 22.35% vs 22.6% EBITDA margin, ₹387 Cr vs ₹391.76 Cr
EBITDA. A system confident enough to say "trust is high" must first agree with itself.

---

## GROUP I — OUTPUT SCHEMA CHANGE

Replace the single `Quality` grade with four independent fields. A single grade forces
unwarranted synthesis.

```json
{
  "margin_driver":     "OPERATIONS | PRICE | INVENTORY_GAIN | ONE_OFF | UNVERIFIED",
  "cycle_position":    "TROUGH | MID | PEAK | UNKNOWN",
  "data_completeness": "FULL | P&L_ONLY | PARTIAL",
  "peer_correlation":  "IDIOSYNCRATIC | SECTOR_WIDE | UNKNOWN",
  "persistence":       "RECURRING | TRANSIENT | UNKNOWN",
  "falsifier":         "<what specific future datapoint would disprove this read>"
}
```

Mandatory `falsifier` field. It forces the model to state what it would take to be wrong.

---

## EXPECTED OUTPUT — PANAMAPET Q1 FY27 (regression target)

```
margin_driver:     INVENTORY_GAIN
cycle_position:    PEAK
data_completeness: P&L_ONLY  (Q1 — no balance sheet, no cash flow filed)
peer_correlation:  SECTOR_WIDE  (Gandhar +11.2pp, Savita +20.8pp, same quarter)
persistence:       TRANSIENT
falsifier:         "Volume disclosure showing tonnage +100%+ would support a demand
                    read. Q2 margin holding above 18% would disprove mean reversion."

FLAGS FIRED:
  A1  Q1 filing — cash flow and balance sheet unavailable, quality capped at UNVERIFIED
  A3  No consensus estimates — verdict suppressed
  B1  Incremental margin 31.9% vs 9% median (3.5x)
  B2  Observed +14.1pp vs operating-leverage ceiling of 2.4pp (5.9x) — leverage cannot explain
  B3  Material cost fell as % of revenue while revenue +150% — price, not operations
  C1  Volume not disclosed — demand attribution blocked
  D2  Sector-wide input price event — 2 of 2 peers correlated
  E2  Record margin in 20 quarters for a converter — cycle PEAK
  E3  97 inventory days = 1.08 quarters of price risk, symmetric on reversal
  E4  Upstream CPCL already −27% QoQ — downstream roll expected next print
  F3  Reported forward P/E 2.5x — market-implied earnings rejection

HEADLINE: "Record quarter driven by base-oil price dislocation, not operations.
           Margin at 20-quarter high for a spread business. Not annualisable."
```

Versus what shipped: `Excellent / Clean / Trust is high / No distortions flagged`.

---

## IMPLEMENTATION ORDER

1. **Group A + H** — pure guardrails, no new data needed. Stops the fabricated cash-flow badge
   and the trust language today. Highest value per hour of work.
2. **Group B** — needs only the P&L you already parse. B2 is the decisive test and is four lines
   of arithmetic.
3. **Group D** — needs a peer table with value-chain tags. Highest analytical value in the set.
4. **Groups C, E, F, G** — need commodity price feeds and filing-text search.

Groups A, B and H alone would have caught this filing.
