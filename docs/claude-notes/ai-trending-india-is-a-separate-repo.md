---
name: ai-trending-india-is-a-separate-repo
description: AI Trending India lives at D:\AI Trending India and must never be mixed into the Opportunity Trader repo
metadata:
  type: feedback
---

AI Trending India (the trending-content media platform) lives in its own
repository at `D:\AI Trending India`, git-initialised on branch `main`,
first commit 22 Aug 2026. It must **never** be built inside, merged into,
or share files with `D:\Opportunity Trader`.

He stated this unprompted and emphatically ("do not club this repo in
opportunity-trader . never") after the master project instruction was
pasted into a session whose working directory was the trading bot.

**Why:** Opportunity Trader is a live equities bot holding real Dhan broker
credentials in a `.env` beside the code, and it places real orders. The two
projects share Python and nothing else — zero WordPress, AdSense, Google
Trends or Search Console references exist anywhere in the trading repo.
Entangling a content platform with a system that moves money is risk with
no upside.

**How to apply:** if a session's working directory is
`D:\Opportunity Trader` and the request is about trending content,
articles, WordPress, AdSense or SEO, stop and switch to
`D:\AI Trending India` before doing anything. Do not create files for one
project in the other's tree, even temporarily. See
[[opportunity-trader-architecture]].
