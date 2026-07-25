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


class MasterLoader:

    def __init__(self, csv_path=MASTER_CSV_PATH):
        self.csv_path = csv_path
        self._by_symbol = {}
        self._by_security_id = {}

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

        for _, row in df.iterrows():
            record = row.to_dict()
            self._by_symbol[record["SYMBOL"]] = record
            self._by_security_id[str(record["SECURITY ID"])] = record

        return len(df)

    # --------------------------------------------------

    def get_by_symbol(self, symbol):
        return self._by_symbol.get(symbol)

    def get_by_security_id(self, security_id):
        return self._by_security_id.get(str(security_id))

    def all_symbols(self):
        return list(self._by_symbol.keys())

    def security_id(self, symbol):
        record = self._by_symbol.get(symbol)
        return record["SECURITY ID"] if record else None
