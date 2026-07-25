"""
==========================================================
Instrument Master
==========================================================

Single source of truth for symbol -> security_id: Dhan's
own live scrip master, fetched fresh, not a hand-maintained
local file that can drift out of date.

Equity (NSE_EQ) only -- this loader will refuse to resolve
anything else.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import decision, warn

COMPACT_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


class InstrumentMaster:

    def __init__(self):
        self._df = None
        self._security_id = {}   # symbol -> security_id

    # --------------------------------------------------

    def load(self):
        import pandas as pd

        self._df = pd.read_csv(COMPACT_CSV_URL, low_memory=False)
        decision(
            f"[INSTRUMENT_MASTER] Loaded {len(self._df)} rows "
            f"from live Dhan scrip master."
        )

    # --------------------------------------------------

    def resolve(self, symbol):
        if symbol in self._security_id:
            return self._security_id[symbol]

        if self._df is None:
            raise RuntimeError(
                "InstrumentMaster.load() must be called before resolve()."
            )

        match = self._df[
            (self._df["SEM_EXM_EXCH_ID"] == "NSE")
            & (self._df["SEM_INSTRUMENT_NAME"] == "EQUITY")
            & (self._df["SEM_TRADING_SYMBOL"] == symbol)
        ]

        if match.empty:
            warn(f"No NSE equity match for symbol '{symbol}' -- skipping.")
            return None

        security_id = str(match.iloc[0]["SEM_SMST_SECURITY_ID"])
        self._security_id[symbol] = security_id
        return security_id

    # --------------------------------------------------

    def resolve_watchlist(self, symbols):
        resolved = {}
        for symbol in symbols:
            security_id = self.resolve(symbol)
            if security_id is not None:
                resolved[symbol] = security_id
        return resolved
