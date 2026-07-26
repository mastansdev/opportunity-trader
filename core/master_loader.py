"""
==========================================================
Master Loader
==========================================================

Loads data/master_stocks.csv -- the single source of truth
for the 750-stock universe. Every other module that needs
symbol -> security_id, sector, industry, or any company
tag calls THIS, not its own copy of the data.

Validated at load time, every time: no empty cells, no
duplicate symbols, no duplicate security IDs. If the file
is ever edited badly, the bot refuses to start rather than
run on broken data.

Author : H&M Opportunity Trader
==========================================================
"""

import os

MASTER_CSV_PATH = os.path.join("data", "master_stocks.csv")

REQUIRED_COLUMNS = [
    "SECURITY ID", "SYMBOL", "COMPANY NAME", "SECTOR", "INDUSTRY",
    "CORE BUSINESS", "BUSINESS_TYPE", "OWNERSHIP",
    "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY", "KEYWORDS", "THEMES",
]

# Written by tools/morning_universe.py before the open -- see
# core/subscribe_list.py for what makes a stock NO (T2T, ETF, price
# band, illiquid, ex-date, unclassified). OPTIONAL on purpose: a file
# that predates the feature, or a hand-made test fixture, has no such
# column and every row is then treated as tradeable. The bot must never
# refuse to start just because the morning tool hasn't been run.
SUBSCRIBE_COLUMN = "SUBSCRIBE"


class MasterLoader:

    def __init__(self, csv_path=MASTER_CSV_PATH):
        self.csv_path = csv_path
        self._by_symbol = {}
        self._by_security_id = {}
        # Every row stays in _by_symbol regardless of SUBSCRIBE, because
        # sector lookups and news keyword matching are still wanted for
        # a blocked stock. Only the FEED list is filtered.
        self._subscribed = []
        self._blocked = {}
        # False means the morning tool has never been run against this
        # file -- main.py warns loudly, because it then subscribes to
        # everything including T2T names.
        self.has_subscribe_column = False

    # --------------------------------------------------

    def load(self):
        import pandas as pd

        if not os.path.exists(self.csv_path):
            raise RuntimeError(
                f"Master stock database not found at {self.csv_path}."
            )

        df = pd.read_csv(self.csv_path, dtype={"SECURITY ID": str})

        missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing_cols:
            raise RuntimeError(
                f"Master database missing required columns: {missing_cols}"
            )

        empty_cells = df[REQUIRED_COLUMNS].isna().sum().sum()
        if empty_cells:
            raise RuntimeError(
                f"Master database has {empty_cells} empty cell(s). "
                f"Fix the source file before trading."
            )

        dup_symbols = df["SYMBOL"].duplicated()
        if dup_symbols.any():
            raise RuntimeError(
                f"Duplicate SYMBOL rows: "
                f"{df.loc[dup_symbols, 'SYMBOL'].tolist()}"
            )

        dup_ids = df["SECURITY ID"].duplicated()
        if dup_ids.any():
            raise RuntimeError(
                f"Duplicate SECURITY ID rows: "
                f"{df.loc[dup_ids, 'SECURITY ID'].tolist()}"
            )

        has_subscribe = SUBSCRIBE_COLUMN in df.columns
        self.has_subscribe_column = has_subscribe

        for _, row in df.iterrows():
            record = row.to_dict()
            symbol = record["SYMBOL"]
            self._by_symbol[symbol] = record
            self._by_security_id[str(record["SECURITY ID"])] = record

            if has_subscribe:
                flag = str(record.get(SUBSCRIBE_COLUMN) or "").strip().upper()
                # Anything that isn't an explicit "NO" is subscribed --
                # fail-open. A blank or garbled cell must not silently
                # drop a stock from the feed.
                if flag == "NO":
                    self._blocked[symbol] = str(
                        record.get("SUBSCRIBE_REASON") or "marked NO"
                    )
                    continue
            self._subscribed.append(symbol)

        return len(df)

    # --------------------------------------------------

    def get_by_symbol(self, symbol):
        return self._by_symbol.get(symbol)

    def get_by_security_id(self, security_id):
        return self._by_security_id.get(str(security_id))

    def all_symbols(self, include_blocked=False):
        """
        Symbols to SUBSCRIBE to -- i.e. SUBSCRIBE = YES only.

        This is what main.py builds the WebSocket subscription from, so
        a T2T / illiquid / ex-date stock never reaches the feed, never
        appears in gainers-losers, and can never be traded by accident.
        Pass include_blocked=True for the full master list (the news
        matcher wants that -- news about a blocked stock is still worth
        recording).
        """
        if include_blocked:
            return list(self._by_symbol.keys())
        return list(self._subscribed)

    def blocked_symbols(self):
        """{symbol: reason} for everything the morning run marked NO."""
        return dict(self._blocked)

    def security_id(self, symbol):
        record = self._by_symbol.get(symbol)
        return record["SECURITY ID"] if record else None
