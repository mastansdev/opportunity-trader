"""
Read-only diagnostic for the news store. Prints the distribution of
what's stored (by direction/confidence, by classifier, by tier) and a
handful of sample rows, so we can SEE why the feed looks repetitive.
Changes nothing. Run:  py tools/diagnose_news.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func

from news_bot.news_store import default_store


def main():
    store = default_store()
    t = store.news_items
    with store.engine.connect() as c:
        total = c.execute(select(func.count()).select_from(t)).scalar_one()
        print(f"TOTAL ROWS: {total}\n")

        print("--- by direction + confidence (most common first) ---")
        for r in c.execute(
            select(t.c.direction, t.c.confidence, func.count().label("n"))
            .group_by(t.c.direction, t.c.confidence)
            .order_by(func.count().desc())
        ).all():
            pct = (r.n / total * 100) if total else 0
            print(f"  {str(r.direction):8} {str(r.confidence):>4}  ->  {r.n:6}  ({pct:4.1f}%)")

        print("\n--- by tier (COMPANY = named stock, BROAD = sector/theme) ---")
        for r in c.execute(
            select(t.c.tier, func.count().label("n"))
            .group_by(t.c.tier).order_by(func.count().desc())
        ).all():
            print(f"  {str(r.tier):10} -> {r.n}")

        print("\n--- by matched_field (HOW it matched) ---")
        for r in c.execute(
            select(t.c.matched_field, func.count().label("n"))
            .group_by(t.c.matched_field).order_by(func.count().desc())
        ).all():
            print(f"  {str(r.matched_field):18} -> {r.n}")

        print("\n--- top 10 reasons (the classifier's verdict text) ---")
        for r in c.execute(
            select(t.c.reason, func.count().label("n"))
            .group_by(t.c.reason).order_by(func.count().desc()).limit(10)
        ).all():
            print(f"  {r.n:6}  {str(r.reason)[:60]}")

        print("\n--- how many DISTINCT stories (guids) vs rows ---")
        distinct_guids = c.execute(
            select(func.count(func.distinct(t.c.guid)))
        ).scalar_one()
        print(f"  {distinct_guids} distinct stories -> {total} rows "
              f"({total/max(distinct_guids,1):.1f} stocks per story on average)")

        print("\n--- 8 most recent rows (what the feed shows) ---")
        for r in c.execute(
            select(t.c.symbol, t.c.priority, t.c.direction, t.c.confidence,
                   t.c.reason, t.c.title)
            .order_by(t.c.created_at.desc()).limit(8)
        ).all():
            print(f"  [{r.priority}] {r.symbol:10} {str(r.direction):8} "
                  f"{str(r.confidence):>4} | {str(r.reason)[:28]:28} | "
                  f"{str(r.title)[:45]}")


if __name__ == "__main__":
    main()
