---
name: opportunity-trader-architecture
description: "The two entry lanes, the one rule file, and which dashboard page is live — facts about Opportunity Trader not obvious from the tree"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-08-12T12:21:23.343Z
---

**Two independent paths can place a real order**, both ending at
`Engine._enter()`:

1. `core/ranker.py` → `core/auto_entry.take()` — called from `main.py`'s
   refresh loop with `dashboard_state.get_snapshot()["ranked"]["rows"]`
   plus `["early"]["rows"]`.
2. `core/engine._try_structural_entry()` — the ORB breakout lane.

`core/rules.py` (created 11 Aug 2026) is the single owner of every
shared threshold. As of 12 Aug 2026 both lanes plus `config.py` read
`RISK_PER_TRADE_RS` from it. `tests/test_rules_are_not_duplicated.py`
fails the build if a core module redeclares an owned name, and now also
checks config.py and that both lanes agree on the risk budget.

**The dashboard the operator actually uses is `dashboard/static/app.html`**
— the React page served at `/` and `/app`, three tabs (LIVE / PRE /
POST). `index.html` (`/full`), `board.html` (`/board`) and
`screen.html` (`/screen`, `/old`) are older pages still served. React
is loaded from a CDN, so app.html cannot be rendered offline; the
practical check is `node --input-type=module --check` on its single
`<script type="module">` block — a parse error there blanks the screen
silently. `tests/test_the_react_dashboard_parses.py` does this.

**Environment:** Python 3.14 (`.python-version` says 3.11 but only 3.14
is installed; deps are on 3.14). Run tests with `py -m pytest tests -q`
— takes ~5-7 minutes, ~4,050 tests. Use `py`, not `python` (the Windows
Store alias shadows it and fails).

`main.py` reads Telegram, never collects it — `tools/collector.py` runs
in a second terminal. Never run two Telegram readers at once;
`core/runlock.py` refuses, and it ages locks out over 2 hours rather
than checking whether the pid is alive, so a killed run blocks the next
one for a long time.

See [[operator-work-style]] and [[opportunity-trader-open-decisions]].
