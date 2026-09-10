---
name: phone-work-via-cloud-sessions
description: "From 10 Sep 2026 he codes from the Claude app (cloud sessions) with the laptop off; GitHub is the bridge, CLAUDE.md + docs/ carry the context"
metadata: 
  node_type: memory
  type: project
  originSessionId: 16056bf4-7288-47a5-b025-94575658f3a9
  modified: 2026-09-10T10:33:22.332Z
---

Set up 10 September 2026. He is out of town with the laptop **off**, coding
only — no trading. Remote Control / Dispatch need the laptop on, so the
route is **Claude Code cloud sessions** in the app's Code tab.

- Claude account: **hmonlineservices9@gmail.com** (Pro). GitHub repo
  `mastansdev/opportunity-trader` is on his other account (mastansaheb9) —
  connected via GitHub OAuth; the two accounts differing is fine.
- `main` pushed 10 Sep (725cd1c..6df747b, 192 commits). Before that GitHub
  was 189 commits behind.
- Phone sessions cannot see this memory dir. The context travels in the
  repo: `CLAUDE.md`, `docs/handoff/` (open problems, error digest, trades
  CSV) and `docs/claude-notes/` (a **copy** of these notes — it drifts;
  re-copy after updating notes here).
- His rule for this week: build rules/fixes on branches from the phone;
  they go into the bot only after he is home, pulls, tests, runs PAPER.

**The push incident, so it is not repeated.** `x.session` (a live Telethon
login, 256-byte auth key) was committed at the repo root on 31 Aug, plus
~300 MB of rotated logs and a PDF (14 Aug). I stripped them from the
unpushed range with `git filter-branch --index-filter ... origin/main..main`
— and the checkout at the end **deleted x.session from disk** too. Restored
byte-for-byte from `refs/original`. `*.session` is gitignored now. Local
branch `backup/pre-phone-clean-20260910` and `refs/original/refs/heads/main`
still contain x.session: **never push them.** Lesson: a history rewrite
also rewrites the working tree; copy untracked-to-be files aside first.

**When he is back:** `git pull` on the laptop, full suite (known failures:
F&O list stale, sector membership ×3), PAPER session, then ON.

Related: [[bot-review-7-to-10-sep-2026]], [[the-one-switch]],
[[telegram-push-breaks-ocr]].
