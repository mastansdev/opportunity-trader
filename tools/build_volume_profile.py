"""Rebuild each stock's own intraday volume curve.

Runs nightly, after the intraday step has stored today's minute bars.
See core/volume_pace.py for what the curve is and why the whole-day
divisor it replaces was measuring the clock instead of the stock.
"""

import sys

sys.path.insert(0, ".")

from core import volume_pace


def main():
    count = volume_pace.build_profile()
    print(f"{count} per-stock curves -> {volume_pace.PROFILE_PATH}")
    if count < 1000:
        print("WARNING: far fewer curves than the ~1,300 tradeable "
              "universe. Check data/history_candles.db has today's bars.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
