"""
Decision-correctness tests for SectorMonitor -- proves the
breadth-based panic detection fires on genuinely broad sector
declines and stays quiet on everything else (one bad stock,
too few names, a green sector, no data yet).
"""

from core.sector_monitor import SectorMonitor


class _FakeMarketData:
    def __init__(self, day_opens=None, latest_prices=None):
        self.day_opens = day_opens or {}
        self.latest_prices = latest_prices or {}

    def get_day_open(self, symbol):
        return self.day_opens.get(symbol)

    def get_latest_price(self, symbol):
        return self.latest_prices.get(symbol)


class _FakeMasterLoader:
    def __init__(self, symbols_sectors):
        self.records = {s: {"SECTOR": sec} for s, sec in symbols_sectors.items()}

    def all_symbols(self):
        return list(self.records.keys())

    def get_by_symbol(self, symbol):
        return self.records.get(symbol)


def _loader(**symbols_sectors):
    return _FakeMasterLoader(symbols_sectors)


def test_flags_a_sector_that_is_broadly_and_sharply_declining():
    loader = _loader(SUNPHARMA="PHARMA", CIPLA="PHARMA", DRREDDY="PHARMA", LUPIN="PHARMA")
    market_data = _FakeMarketData(
        day_opens={"SUNPHARMA": 100, "CIPLA": 100, "DRREDDY": 100, "LUPIN": 100},
        latest_prices={"SUNPHARMA": 96, "CIPLA": 95, "DRREDDY": 97, "LUPIN": 96},
    )
    monitor = SectorMonitor(market_data, loader)
    monitor.refresh()

    assert monitor.is_panicking("PHARMA") is True
    assert "PHARMA" in monitor.panicking_sectors()


def test_does_not_flag_when_only_one_stock_drags_the_average_down():
    """One bad stock in an otherwise flat sector must not trip
    the panic flag -- decline_ratio guards against this, not
    just the average."""
    loader = _loader(TCS="IT", INFY="IT", WIPRO="IT", HCLTECH="IT")
    market_data = _FakeMarketData(
        day_opens={"TCS": 100, "INFY": 100, "WIPRO": 100, "HCLTECH": 100},
        latest_prices={"TCS": 40, "INFY": 100.5, "WIPRO": 100.2, "HCLTECH": 100.1},
    )
    monitor = SectorMonitor(market_data, loader)
    monitor.refresh()

    assert monitor.is_panicking("IT") is False


def test_does_not_flag_a_sector_with_too_few_reporting_symbols():
    loader = _loader(TCS="IT", INFY="IT")  # only 2, below MIN_SYMBOLS
    market_data = _FakeMarketData(
        day_opens={"TCS": 100, "INFY": 100},
        latest_prices={"TCS": 90, "INFY": 91},
    )
    monitor = SectorMonitor(market_data, loader)
    monitor.refresh()

    assert monitor.is_panicking("IT") is False


def test_does_not_flag_a_green_sector():
    loader = _loader(TCS="IT", INFY="IT", WIPRO="IT")
    market_data = _FakeMarketData(
        day_opens={"TCS": 100, "INFY": 100, "WIPRO": 100},
        latest_prices={"TCS": 105, "INFY": 106, "WIPRO": 104},
    )
    monitor = SectorMonitor(market_data, loader)
    monitor.refresh()

    assert monitor.is_panicking("IT") is False


def test_symbols_with_no_data_yet_are_excluded_not_counted_as_declines():
    loader = _loader(A="X", B="X", C="X", D="X")
    market_data = _FakeMarketData(
        day_opens={"A": 100, "B": 100, "C": 100},  # D never ticked
        latest_prices={"A": 95, "B": 94, "C": 96},
    )
    monitor = SectorMonitor(market_data, loader)
    monitor.refresh()

    # A, B, C alone are broad enough (3 >= MIN_SYMBOLS) and sharply
    # down -- should still flag even though D is silent.
    assert monitor.is_panicking("X") is True


def test_is_symbol_in_panicking_sector_looks_up_the_symbols_own_sector():
    loader = _loader(SUNPHARMA="PHARMA", CIPLA="PHARMA", DRREDDY="PHARMA", TCS="IT")
    market_data = _FakeMarketData(
        day_opens={"SUNPHARMA": 100, "CIPLA": 100, "DRREDDY": 100, "TCS": 100},
        latest_prices={"SUNPHARMA": 95, "CIPLA": 94, "DRREDDY": 96, "TCS": 101},
    )
    monitor = SectorMonitor(market_data, loader)
    monitor.refresh()

    assert monitor.is_symbol_in_panicking_sector("SUNPHARMA") is True
    assert monitor.is_symbol_in_panicking_sector("TCS") is False


def test_is_symbol_in_panicking_sector_false_for_unknown_symbol():
    monitor = SectorMonitor(_FakeMarketData(), _loader())
    monitor.refresh()
    assert monitor.is_symbol_in_panicking_sector("NOPE") is False


def test_before_any_refresh_nothing_is_flagged():
    loader = _loader(SUNPHARMA="PHARMA", CIPLA="PHARMA", DRREDDY="PHARMA")
    market_data = _FakeMarketData(
        day_opens={"SUNPHARMA": 100, "CIPLA": 100, "DRREDDY": 100},
        latest_prices={"SUNPHARMA": 90, "CIPLA": 90, "DRREDDY": 90},
    )
    monitor = SectorMonitor(market_data, loader)

    assert monitor.is_panicking("PHARMA") is False
    assert monitor.panicking_sectors() == set()
