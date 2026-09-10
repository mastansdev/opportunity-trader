---
name: day-trader-telugu-weekends-and-links
description: "Skip Day Trader Telugu on weekends. The link rule already existed since 2 Aug — check NOISE before writing another one"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-05T11:44:59.172Z
---

**His instruction, 5 September 2026:** *"daytrader telugu needs to be
avoided on weekends & links they are posting"* — *"they will be posting
their youtube links all weekends."*

**And immediately after:** *"we made that to avoid links from that
channel right? forgot again?? ... not now since begining."*

He was right. `core/stock_events.NOISE` has matched YouTube links,
`/shorts/` and "must watch" **since 2 August**, from his own earlier
instruction. It works — there are ZERO events of kind NOISE on file, so
none of those posts has ever reached a stock. A second rule
(`is_video_promo`) was written before checking, measured worse than the
existing one on all 2,016 stored messages, and deleted the same hour.

**How to apply:**
- Day Trader Telugu is not polled on Saturday or Sunday. This is about
  that channel's weekend behaviour, NOT about collecting at weekends —
  the weekend is exactly when gaps form and every other channel must
  keep being read. See [[telegram-catchup-should-walk-forward]].
- **Before adding any filter, grep for one that already exists**, and
  audit it by asking what each pattern holds back ON ITS OWN. That
  audit is what found the real bugs:

      follow us on   84 msgs, 26 naming a stock — "Follow us on
                     @etnowlive" is ET Now's WATERMARK on every news
                     card. Mine, added and reverted the same hour.
      subscribe      24 msgs, 17 naming a stock — "subscribes to a
                     rights issue", "net mobile subscriber adds",
                     "IPO subscribed 24%". Finance vocabulary.
      deadline       4 msgs, 3 naming a stock — an order win states
                     its delivery deadline.

  Noise fell 157 → 45; 112 real messages came back.

**Why this class of bug is expensive:** a published reason is MANDATORY
before the ranker evaluates a stock at all, so a word that silently
discards a filing does not cost a panel row, it costs the door. See
[[what-the-event-edge-actually-measures]].

**A correction to what I first told him:** the ACC rows were NOT caused
by the YouTube posts. The `symbols` column in telegram.db lists words
that looked like tickers; no event was ever filed from those messages.
The one real ACC mis-tag came from a news card where "ACC" meant
Advanced Chemistry Cell, the battery scheme.

Still open: a counterparty filed as the subject — "ARTSON LTD: RECEIVES
ORDER ... FOR NTPC NABINAGAR" was filed against NTPC, while OrderBook
Pulse tagged the same order correctly as #ARTSON.
