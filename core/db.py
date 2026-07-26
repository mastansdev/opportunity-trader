"""
==========================================================
Database URL resolution -- shared by every store
==========================================================

Lifted out of news_bot/news_store.py when the news subsystem was
deleted (2026-07-26). The stock memory and the trade memory still need
it, and they should never have depended on the news package for a
generic helper in the first place.

Priority: explicit argument (tests) > DATABASE_URL env
(Railway/Postgres) > local SQLite default.

Author : H&M Opportunity Trader
==========================================================
"""

import os

DEFAULT_SQLITE_URL = "sqlite:///data/opportunity_trader.db"


def resolve_database_url(explicit=None, default=None):
    """
    Pick the database URL.

    Railway and Heroku hand out URLs starting 'postgres://', but
    SQLAlchemy 2.x wants 'postgresql://' -- normalised here so the exact
    URL the platform injects works with zero editing.
    """
    url = (explicit or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        url = default or DEFAULT_SQLITE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url
