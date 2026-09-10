---
name: two-market-caps-free-float-and-total
description: "Free float feeds the order gate; total feeds the SEBI size band. Two stores, never swapped."
metadata: 
  node_type: memory
  type: project
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T02:30:30.248Z
---

Built 6 Sep 2026, after he asked what market cap is and why the bot
only had it for 500 stocks.

**`core/market_cap.py` — FREE FLOAT.** Only the shares that actually
trade. From NSE index lists. **500 symbols and that is the ceiling**:
measured 6 Sep, `NIFTY 500` serves 500 with ffmc; `MICROCAP 250`,
`TOTAL MARKET` and `SMALLCAP 100` return **zero rows** from that API;
`MIDCAP 150`/`SMALLCAP 250`/`NIFTY 50` are inside NIFTY 500 so they
add nothing. This is what `cause_effect.standing_reason()` divides by
for the 20%-of-company gate.

**`core/company_size.py` — TOTAL market cap.** Every share. From
`data/LIST_NSE.xlsx`, NSE's SEBI-LODR filing, HIS file, on disk since
8 Aug. **No network.** 2,773 companies, **1,741 of his 1,976 (88%)**.
Bands are NSE's own Rank column (verified contiguous 1..2,773 and in
size order): 1-100 LARGE, 101-250 MID, 251+ SMALL. On his universe:
99 large, 150 mid, 1,492 small, 235 with no size.

**Why separate modules:** so a later edit cannot reach for the wrong
one. 47% of the *floating* company is the fact that opens the standing
order door; 47% of the *total* company is a different number.

**It decides nothing.** There is no market-cap gate anywhere on the
entry path — rules, ranker, auto_entry, engine, results_gate all carry
zero references. The only size floor in the repo is the Rs 2,000 cr one
in `core/centre.py`, and **nothing calls `centre.py`** at all.

**Why it exists:** every trade now records `mcap_band` and `mcap_cr`
beside `door`, `volume_x`, `jump_x`, `liveness`. On 6 Sep his book
could not answer whether size predicts anything — under the rules
running since 29 Aug there were **2 large, 3 mid and 56 small** trades.
Five non-small. Not because the question is hard but because nothing
wrote the size down. The 200 rows already on file are left blank; the
band joins on at read time when the old era is wanted.

Refresh: `py tools/refresh_company_size.py` (only when a newer
LIST_NSE.xlsx is dropped in; NSE publishes twice a year).

See [[what-the-event-edge-actually-measures]] and
[[never-mix-old-data-with-new-rules]].
