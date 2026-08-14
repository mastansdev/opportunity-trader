"""
Re-link every stored news story with the fixed matcher.

    py tools/news_impact_rematch.py            show what would change
    py tools/news_impact_rematch.py --apply    actually rewrite

WHY
---
The links already in news_memory.db were produced by the old matcher,
which searched ECONOMIC_SENSITIVITY -- a six-value classification
column -- as though it identified a company. On 30 July 2026 the live
database held 63 stories and 166 links, and one macro line,

    "Federal Reserve holds interest rates steady, but three members
     voted to raise rates."

was stored against DBREALTY, CGCL, BRIGADE, ARVSMART, ANANTRAJ and
AGIIL with the reason "matched on: INTEREST, RATE, REAL". Not one of
those companies was in the story. Uncapped, that single line matched
140 of 750 stocks.

Those rows cannot be repaired in place -- they were never about
anything. This deletes the keyword-derived links and rebuilds them from
the stories, which are kept.

WHAT IT WILL NOT TOUCH
----------------------
Rows with `how` != 'keyword'. If the reasoning step ever ran and
produced a real direction with a real explanation, that is a judgement
and this script has no business overwriting it. Only the direction-less
keyword links are rebuilt.

DRY RUN BY DEFAULT. It prints the before/after for every story and
changes nothing unless --apply is given.
"""

import sys
from collections import Counter

sys.path.insert(0, ".")

from core.logger import decision, warn


def main(apply=False):
    import sqlite3

    from core.master_loader import MasterLoader
    from core.news_impact import (MACRO, NEWS, STOCK, TIP, NewsImpact,
                                  is_not_a_story, looks_like_a_tip)

    # MasterLoader's constructor only records the path -- load() is what
    # actually reads the CSV. Without it every lookup returns nothing,
    # the matcher finds no candidates, and this script would happily
    # delete all 166 links and write none back. The guard below caught
    # exactly that on the first live run.
    master_loader = MasterLoader()
    total = master_loader.load()
    decision(f"Master file: {total} symbols "
             f"({len(master_loader.all_symbols(include_blocked=True))} "
             f"including blocked).")

    impact = NewsImpact(master_loader=master_loader)
    profiles = impact._stock_profiles()
    if not profiles:
        warn("The master file produced no stock profiles -- refusing to "
             "rewrite links against an empty universe.")
        sys.exit(1)
    decision(f"Matcher ready: {len(profiles)} stock profiles.")

    conn = sqlite3.connect(impact.db_path)
    conn.row_factory = sqlite3.Row
    stories = [dict(r) for r in conn.execute(
        "SELECT news_id, headline, body, source FROM news ORDER BY seen_at")]
    before_total = conn.execute(
        "SELECT COUNT(*) FROM impact WHERE how = 'keyword'").fetchone()[0]
    kept_reasoned = conn.execute(
        "SELECT COUNT(*) FROM impact WHERE how != 'keyword'").fetchone()[0]

    decision(f"{len(stories)} stories, {before_total} keyword links, "
             f"{kept_reasoned} reasoned links (kept untouched).")
    decision("")

    # Rows that were never stories at all -- News Pulse's own section
    # dividers ("STOCK PICK", "FII / DII FLOWS") and Day Trader Telugu's
    # bare YouTube links. They have a story's shape and no statement in
    # them, and they were stored before is_not_a_story() existed.
    noise = [s for s in stories if is_not_a_story(s["headline"], s["body"])]
    if noise:
        decision(f"  {len(noise)} stored row(s) are not stories and will "
                 f"be deleted:")
        for s in noise:
            decision(f"      [{s['source']}] {s['headline'][:56]!r}")
        decision("")
    stories = [s for s in stories if s not in noise]

    tips = [s for s in stories
            if looks_like_a_tip(f"{s['headline']} {s['body'] or ''}")]
    if tips:
        decision(f"  {len(tips)} row(s) are RECOMMENDATIONS, not events, "
                 f"and will be marked TIP:")
        for s in tips:
            decision(f"      [{s['source']}] {s['headline'][:56]}")
        decision("")

    changes, after_total, macro_count = [], 0, 0
    for story in stories:
        news_id = story["news_id"]
        old = [r["symbol"] for r in conn.execute(
            "SELECT symbol FROM impact WHERE news_id = ? AND how = 'keyword'"
            " ORDER BY symbol", (news_id,))]
        candidates = impact.candidates(
            f"{story['headline']} {story['body'] or ''}")
        new = [c["symbol"] for c in candidates[:10]]
        scope = MACRO if not candidates else STOCK
        if scope == MACRO:
            macro_count += 1
        after_total += len(new)
        if set(old) != set(new):
            changes.append((story, old, new, scope, candidates))

    for story, old, new, scope, candidates in changes:
        dropped = sorted(set(old) - set(new))
        added = sorted(set(new) - set(old))
        decision(f"  {story['headline'][:66]}")
        decision(f"      {scope:<5} {len(old)} -> {len(new)}")
        if dropped:
            decision(f"      dropped: {', '.join(dropped[:12])}"
                     f"{' ...' if len(dropped) > 12 else ''}")
        if added:
            named = {c['symbol'] for c in candidates if c.get('named_by')}
            decision(f"      added  : " + ", ".join(
                f"{s}{'*' if s in named else ''}" for s in added[:12]))

    decision("")
    decision("=" * 66)
    decision(f"  keyword links   {before_total} -> {after_total}")
    decision(f"  stories changed {len(changes)} of {len(stories)}")
    decision(f"  macro stories   {macro_count} (kept, zero links each)")
    decision(f"  * = matched the company's own name")
    decision("=" * 66)

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing written. Re-run with --apply to "
                 "rewrite.")
        conn.close()
        return

    now_scope = Counter()
    try:
        conn.execute("DELETE FROM impact WHERE how = 'keyword'")
        for story in noise:
            conn.execute("DELETE FROM impact WHERE news_id = ?",
                         (story["news_id"],))
            conn.execute("DELETE FROM news WHERE news_id = ?",
                         (story["news_id"],))
        for story in stories:
            news_id = story["news_id"]
            blob = f"{story['headline']} {story['body'] or ''}"
            candidates = impact.candidates(blob)
            scope = MACRO if not candidates else STOCK
            kind = TIP if looks_like_a_tip(blob) else NEWS
            now_scope[scope] += 1
            now_scope[kind] += 1
            conn.execute("UPDATE news SET scope = ?, kind = ? "
                         "WHERE news_id = ?", (scope, kind, news_id))
            conn.executemany(
                "INSERT OR REPLACE INTO impact (news_id, symbol, direction,"
                " reason, confidence, how) VALUES (?,?,?,?,?,?)",
                [(news_id, c["symbol"], "UNKNOWN",
                  "matched on: " + ", ".join(c["hits"][:4]), None, "keyword")
                 for c in candidates[:10]])
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        warn(f"Rewrite failed, nothing changed: {exc}")
        conn.close()
        sys.exit(1)

    final = conn.execute("SELECT COUNT(*) FROM impact").fetchone()[0]
    conn.close()
    decision("")
    decision(f"  DONE. impact table now holds {final} rows "
             f"({dict(now_scope)}).")
    decision("  Every one still has direction UNKNOWN -- naming winners "
             "and losers needs ANTHROPIC_API_KEY. Once that is set, run")
    decision("  py tools/news_impact_backfill.py to reason over them.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
