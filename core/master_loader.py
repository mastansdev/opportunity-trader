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

# Which of the above must actually be FILLED IN, and on which rows.
#
# 2026-07-26. tools/morning_universe.py queues every newly listed NSE
# scrip into the master with only its identity resolved -- SECURITY ID,
# SYMBOL, COMPANY NAME -- and SUBSCRIBE=NO, reason "new listing --
# awaiting sector classification". That is the CORRECT behaviour: the
# stock is recorded but deliberately not tradeable until a human
# classifies it.
#
# But load() used to demand all twelve columns on EVERY row, so the
# morning run adding 186 new listings made the master unloadable, and
# main.py:127 calls load() before anything else. The bot would not have
# STARTED on Monday -- killed by rows it had itself decided not to
# trade.
#
# So the rule is now scoped to what each column is FOR:
#   IDENTITY       -- needed to subscribe to a feed and map a tick back
#                     to a row. Mandatory on every row, no exceptions:
#                     a blank here is genuine corruption.
#   CLASSIFICATION -- needed to make a DECISION about a stock (sector
#                     strength gate, news keyword matching). Mandatory
#                     only where the bot can actually act, i.e. rows
#                     that are not SUBSCRIBE=NO.
#
# A blocked row with no sector is a to-do item. A TRADEABLE row with no
# sector is a bug that would silently break the top-8 sector gate, and
# that still refuses to start.
IDENTITY_COLUMNS = ["SECURITY ID", "SYMBOL", "COMPANY NAME"]
CLASSIFICATION_COLUMNS = [c for c in REQUIRED_COLUMNS
                          if c not in IDENTITY_COLUMNS]

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

        # Identity must be complete on every row -- see the
        # IDENTITY_COLUMNS comment above.
        blank_identity = df[IDENTITY_COLUMNS].isna().any(axis=1)
        if blank_identity.any():
            rows = df.loc[blank_identity, "SYMBOL"].fillna("<no symbol>")
            raise RuntimeError(
                f"Master database has {int(blank_identity.sum())} row(s) "
                f"with missing identity "
                f"({', '.join(IDENTITY_COLUMNS)}): "
                f"{list(rows)[:10]}. Fix the source file before trading."
            )

        # Classification only has to be filled in where the bot can act
        # on it. Rows the morning tool has already marked NO are allowed
        # to be unclassified -- that is exactly what "new listing --
        # awaiting sector classification" means.
        if SUBSCRIBE_COLUMN in df.columns:
            tradeable = (df[SUBSCRIBE_COLUMN].astype(str).str.strip()
                         .str.upper() != "NO")
        else:
            tradeable = df.index == df.index      # no column -> all rows

        unclassified = tradeable & df[CLASSIFICATION_COLUMNS].isna().any(axis=1)
        if unclassified.any():
            rows = df.loc[unclassified, "SYMBOL"]
            raise RuntimeError(
                f"Master database has {int(unclassified.sum())} TRADEABLE "
                f"row(s) with missing classification: {list(rows)[:10]}. "
                f"Either classify them or mark them SUBSCRIBE=NO -- a "
                f"tradeable stock with no SECTOR silently breaks the "
                f"sector-strength gate."
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
        # AN UNLOADED LOADER USED TO LIE.
        #
        # 31 July 2026, minutes before the first real order:
        #
        #   py tools/live_order_test.py --symbol REDINGTON
        #   REDINGTON not found in the master database.
        #
        # REDINGTON is row 560 of that file, security id 14255. The
        # tool had constructed a MasterLoader and never called load(),
        # so _by_symbol was an empty dict and every lookup in the
        # database returned None -- reported, reasonably enough, as
        # "not found".
        #
        # "not in the database" and "the database was never opened"
        # are opposite problems and they had identical symptoms. On a
        # LIVE morning that reads as a data error and sends you into
        # the CSV looking for a missing row that is right there.
        #
        # load() is idempotent and takes about a second. Doing it here
        # means no caller can ever ask this question too early again.
        if not self._by_symbol:
            self.load()
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
        # Same trap as get_by_symbol() above, and a worse one to fall
        # into: None here means "we cannot identify this instrument",
        # which every caller correctly treats as "do not trade it".
        # An unloaded loader would answer that about all 1,084 stocks.
        record = self.get_by_symbol(symbol)
        return record["SECURITY ID"] if record else None
