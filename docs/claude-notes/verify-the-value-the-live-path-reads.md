---
name: verify-the-value-the-live-path-reads
description: "A passing suite proves the constant, not the code path — twice in one session I shipped a switch that never ran"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-08-23T17:26:46.828Z
---

Before reporting a behaviour change in Opportunity Trader, trace the value
the LIVE path actually reads and demonstrate the new behaviour. A test that
asserts a constant proves the constant.

Twice on 23 Aug 2026 I shipped a switch that never ran, suite green both
times, and reported the behaviour as changed:

- `ENABLE_SLOT_ROTATION` left `False` after being asked to fix seat timing
- `core/rules.py:LAST_NEW_ENTRY` set to 15:30 when **no code reads it** —
  `core/auto_entry.py` imports `config.LAST_ENTRY_TIME`, and a second gate
  (`_position_ceiling()` returning 0 past `config.STAGED_NO_ENTRY_AFTER`)
  would have defeated it regardless

The repo often holds the same clock in three places: `core/rules.py` as
documentation, `config.py` as the live dial, and a module-level copy parsed
at import. Grep every name before editing one, and check for a SECOND gate
on the same path.

**Why:** he trades real money on what I report. A false "this is fixed" is
worse than no change, because he stops looking. He caught both by asking me
to confirm rather than trusting the summary.

**How to apply:** exercise the real function at the boundary and print the
outcome (e.g. `refuse_reason()` at 09:16 / 15:29 / 15:30) before claiming a
window moved. Assert the value the live module holds, not the one in the
rules file. See [[operator-work-style]] — never assume, every number needs
an n.
