"""
What the bot has learned so far — read-only report.

Prints the trade memory grouped by the CONDITIONS each trade was taken
in: sector, hour of entry, direction, exit reason, symbol. Nothing here
changes trading; the memory has no vote (see core/trade_memory.py).

Run:  py tools/learning_report.py            (all sessions)
      py tools/learning_report.py 3          (only buckets with >=3 trades)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trade_memory import default_trade_memory


def _table(title, rows, label="bucket"):
    print(f"\n--- {title} ---")
    if not rows:
        print("   (nothing yet)")
        return
    print(f"   {label:<22}{'trades':>7}{'win%':>7}{'total P&L':>12}{'avg':>9}")
    for r in rows:
        print(f"   {str(r['key']):<22}{r['trades']:>7}{r['win_rate']:>6.0f}%"
              f"{r['total_pnl']:>12,.0f}{r['avg_pnl']:>9,.0f}")


def main(min_trades=1):
    m = default_trade_memory()
    o = m.overall()

    print("=" * 62)
    print("  WHAT THE BOT HAS LEARNED")
    print("=" * 62)

    if not o["trades"]:
        print("\nNo trades remembered yet. Run a session first.")
        return

    print(f"\nSessions recorded : {o['sessions']}")
    print(f"Trades remembered : {o['trades']}")
    print(f"Win rate          : {o['win_rate']:.1f}%  ({o['wins']}W)")
    print(f"Total P&L         : Rs {o['total_pnl']:,.0f}")
    print(f"Avg win / avg loss: Rs {o['avg_win']:,.0f} / Rs {o['avg_loss']:,.0f}")
    if o["avg_loss"]:
        print(f"Win:loss size     : {abs(o['avg_win'] / o['avg_loss']):.2f} : 1")

    _table("By SECTOR", m.by_sector(min_trades), "sector")
    _table("By ENTRY HOUR", m.by_hour(min_trades), "hour")
    _table("By DIRECTION", m.by_direction(min_trades), "direction")
    _table("By EXIT REASON", m.by_exit_reason(min_trades), "reason")
    _table("By SYMBOL (repeat offenders)", m.by_symbol(max(min_trades, 2)),
           "symbol")

    print("\n" + "=" * 62)
    if o["sessions"] < 20:
        print(f"  ⚠  Only {o['sessions']} session(s). These numbers are NOT")
        print("     yet evidence -- small samples look like patterns long")
        print("     before they are one. The memory has no vote by design.")
    else:
        print(f"  {o['sessions']} sessions recorded. Patterns holding across")
        print("  this many days are worth acting on -- review before wiring")
        print("  any of it into a trading rule.")
    print("=" * 62)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
