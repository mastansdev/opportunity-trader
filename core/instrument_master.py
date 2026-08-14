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

        # ---- iloc[0] WAS PICKING BLIND. 8 August 2026. ----
        #
        #     "BUT YOU NEED TO CHECK WITH NSE/CHROME FOR THE CHOLAFIN,
        #      ELECTCAST, MOTHERSON . ID'S & CHECK WITH DHAN DATABASE"
        #                                        -- operator
        #
        # Measured that morning with tools/probe_silent.py against the
        # live account: Dhan refuses to quote CHOLAFIN (19257),
        # ELECTCAST (18116) and MOTHERSON (25510) on NSE_EQ, while
        # HINDALCO (1363) comes back at 1059.60 in the same call. All
        # three had been passing tools/verify_master_database.py every
        # night as CORRECT.
        #
        # They agreed because the verifier calls THIS function. If two
        # rows match a symbol, iloc[0] took whichever pandas happened
        # to order first, wrote it into the master, and then compared
        # the master against itself and found no fault. A check that
        # shares its bug with the thing it checks can never fail.
        #
        # Ambiguity now SAYS SO. Silence about a second candidate is
        # how a stock the operator holds 2,000 shares of went six
        # sessions with no price and nothing reported it.
        ids = sorted({str(v) for v in match["SEM_SMST_SECURITY_ID"]})
        if len(ids) > 1:
            series = None
            if "SEM_SERIES" in match.columns:
                # An NSE cash listing trades in the EQ series. BE, BZ
                # and the rest are restricted books and are not what
                # the feed subscribes to.
                preferred = match[match["SEM_SERIES"].astype(str)
                                  .str.upper().str.strip() == "EQ"]
                if len(preferred) == 1:
                    series = str(preferred.iloc[0]["SEM_SMST_SECURITY_ID"])
            warn(f"[INSTRUMENT_MASTER] '{symbol}' matches {len(ids)} NSE "
                 f"equity rows in Dhan's master: {', '.join(ids)}. "
                 + (f"Taking the EQ-series row ({series})."
                    if series else
                    "No single EQ-series row to break the tie -- "
                    "REFUSING to guess. Run py tools/find_scrip.py "
                    f"{symbol} and set it by hand."))
            if series is None:
                return None
            self._security_id[symbol] = series
            return series

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
