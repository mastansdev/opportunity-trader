"""
==========================================================
Portfolio -- Paper Capital Ledger + MIS Buying Power
==========================================================

Two DIFFERENT jobs live in this one class, deliberately kept
apart:

  1. available_capital / realized_pnl (on_buy/on_sell/on_short/
     on_cover) -- DISPLAY/TRACKING ONLY, unchanged since Phase 1.
     Does NOT gate entries. available_capital can go NEGATIVE --
     that's not a bug, it's the honest consequence of
     LAYER1_FIXED_QTY having no capital awareness. The dashboard
     shows that number as-is rather than hiding it behind an
     artificial floor. This is a notional ledger, not a real
     margin model (no interest, no short-sell fees).

  2. buying_power / used_margin / available_buying_power
     (has_buying_power_for) -- Phase 2, operator-approved
     2026-07-23. THIS ONE GATES ENTRIES: core/engine.py's
     _enter() refuses to open ANY new position (structural or
     manual) once buying power is used up. buying_power is a
     flat leverage multiple of starting_capital
     (config.MIS_LEVERAGE_MULTIPLIER, see its own comment for
     why a single flat number, not real per-stock margin).
     used_margin is the ENTRY-price notional of every currently
     open position (long or short alike -- MIS margin is treated
     as symmetric here, another documented simplification), NOT
     marked to market -- it doesn't fluctuate as the position
     moves, only when a position opens or closes. Unlike
     entry_blocked (core/engine.py) this is never persisted on
     its own and never "for the rest of the day" -- it's fully
     derived from starting_capital (config) + whatever open
     positions already get restored from state_store, so it's
     always correct fresh, restart or not.

Author : H&M Opportunity Trader
==========================================================
"""

from config import PAPER_STARTING_CAPITAL, MIS_LEVERAGE_MULTIPLIER


class Portfolio:

    def __init__(self, starting_capital=PAPER_STARTING_CAPITAL,
                 leverage_multiplier=MIS_LEVERAGE_MULTIPLIER):
        self.starting_capital = starting_capital
        self.available_capital = starting_capital
        self.realized_pnl = 0.0
        self.leverage_multiplier = leverage_multiplier

    # --------------------------------------------------

    def on_buy(self, price, qty):
        """Deducts the notional cost of a new position from
        available capital."""
        self.available_capital -= price * qty

    def on_sell(self, entry_price, exit_price, qty):
        """
        Releases the notional that was tied up in the position
        and credits/debits the realized gain or loss. Returns
        the realized P&L for this trade.
        """
        notional_out = exit_price * qty
        pnl = (exit_price - entry_price) * qty

        self.available_capital += notional_out
        self.realized_pnl += pnl

        return pnl

    # --------------------------------------------------

    def on_short(self, price, qty):
        """Selling to OPEN a short -- credits the notional as
        proceeds received, mirroring on_buy()'s debit for a
        long."""
        self.available_capital += price * qty

    def on_cover(self, entry_price, exit_price, qty):
        """
        Buying back to CLOSE a short. Mirrors on_sell() exactly,
        with the P&L direction flipped: profit when price FALLS.
        Returns the realized P&L for this trade.
        """
        notional_out = exit_price * qty
        pnl = (entry_price - exit_price) * qty

        self.available_capital -= notional_out
        self.realized_pnl += pnl

        return pnl

    # --------------------------------------------------

    def deployed_capital(self, open_positions, get_price):
        """
        Current notional value of everything still open,
        marked to the latest known price -- falls back to
        entry price if no live price is available yet (e.g.
        the very tick that just opened it).
        """
        total = 0.0
        for symbol, position in open_positions.items():
            price = get_price(symbol) or position["entry_price"]
            total += price * position["qty"]
        return total

    def snapshot(self, open_positions, get_price):
        deployed = self.deployed_capital(open_positions, get_price)
        return {
            "starting_capital": round(self.starting_capital, 2),
            "available_capital": round(self.available_capital, 2),
            "deployed_capital": round(deployed, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "buying_power": round(self.buying_power, 2),
            "used_margin": round(self.used_margin(open_positions), 2),
            "available_buying_power": round(
                self.available_buying_power(open_positions), 2
            ),
        }

    # --------------------------------------------------
    # MIS buying power -- GATES entries (core/engine.py). See
    # module docstring for how this differs from
    # available_capital above.
    # --------------------------------------------------

    @property
    def buying_power(self):
        """Total leveraged capital for the day -- fixed, doesn't
        change as positions open/close, only if starting_capital
        or the leverage multiplier itself changes."""
        return self.starting_capital * self.leverage_multiplier

    def used_margin(self, open_positions):
        """
        ENTRY-price notional of every currently open position,
        long or short alike. Fixed at entry -- does NOT track the
        live price like deployed_capital() does, so a position
        moving in your favor doesn't free up margin it never
        actually released in reality (you're still holding the
        same shares/short).
        """
        return sum(
            position["entry_price"] * position["qty"]
            for position in open_positions.values()
        )

    def available_buying_power(self, open_positions):
        return self.buying_power - self.used_margin(open_positions)

    def has_buying_power_for(self, open_positions, price, qty):
        """The actual gate core/engine.py's _enter() checks before
        opening ANY new position, structural or manual."""
        return price * qty <= self.available_buying_power(open_positions)

    # --------------------------------------------------
    # Restart persistence (core/state_store.py)
    # --------------------------------------------------

    def export_state(self):
        return {
            "available_capital": self.available_capital,
            "realized_pnl": self.realized_pnl,
        }

    def load_state(self, state):
        self.available_capital = state["available_capital"]
        self.realized_pnl = state["realized_pnl"]
