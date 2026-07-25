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

from config import (
    PAPER_STARTING_CAPITAL, MIS_DEFAULT_MARGIN_PCT, MIS_MARGIN_OVERRIDES,
)


class Portfolio:

    def __init__(self, starting_capital=PAPER_STARTING_CAPITAL,
                 default_margin_pct=MIS_DEFAULT_MARGIN_PCT,
                 margin_overrides=None):
        self.starting_capital = starting_capital
        self.available_capital = starting_capital
        self.realized_pnl = 0.0
        # 2026-07-24 (evening) real MIS margin model -- see config.py's
        # MIS_DEFAULT_MARGIN_PCT block. margin BLOCKED for a position is
        # notional x its margin fraction (default 20% = 5x leverage),
        # not the full notional.
        self.default_margin_pct = default_margin_pct
        self.margin_overrides = (
            margin_overrides if margin_overrides is not None
            else dict(MIS_MARGIN_OVERRIDES)
        )

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
        used = self.used_margin(open_positions)
        return {
            "starting_capital": round(self.starting_capital, 2),
            "available_capital": round(self.available_capital, 2),
            "deployed_capital": round(deployed, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            # Notional buying power = capital / default margin% (the
            # leveraged deployable size, e.g. 10L / 0.20 = 50L).
            "buying_power": round(self.buying_power, 2),
            # REAL margin blocked right now (notional x per-stock
            # margin%), and real cash still free for new margin.
            "used_margin": round(used, 2),
            "available_margin": round(self.starting_capital - used, 2),
            # Back-compat key some readers still use -- now points at
            # available MARGIN (real cash), not notional headroom.
            "available_buying_power": round(self.starting_capital - used, 2),
            "margin_utilization_pct": round(
                (used / self.starting_capital * 100) if self.starting_capital else 0, 1
            ),
        }

    # --------------------------------------------------
    # MIS margin -- GATES entries (core/engine.py). 2026-07-24
    # (evening): rebuilt as a real replica -- a position blocks
    # notional x its per-stock margin fraction of REAL cash, not the
    # full notional. See config.py's MIS_DEFAULT_MARGIN_PCT block.
    # --------------------------------------------------

    def margin_pct(self, symbol):
        """Per-stock MIS margin fraction (default 20% = 5x leverage;
        overrides for volatile/ASM/GSM names)."""
        return self.margin_overrides.get(symbol, self.default_margin_pct)

    def margin_required(self, symbol, price, qty):
        """Real cash a broker blocks to hold this position intraday:
        notional x the stock's margin fraction."""
        return price * qty * self.margin_pct(symbol)

    @property
    def buying_power(self):
        """Total NOTIONAL that can be deployed on the account's real
        cash at the default margin rate -- capital / margin% (e.g.
        Rs 10L / 0.20 = Rs 50L). Display/reference only."""
        return self.starting_capital / self.default_margin_pct

    def used_margin(self, open_positions):
        """
        REAL margin blocked across every open position right now --
        sum of each position's notional x its own margin%. Long or
        short alike. Fixed at entry price (a favourable move doesn't
        release margin you're still holding the position against).
        """
        return sum(
            self.margin_required(symbol, position["entry_price"], position["qty"])
            for symbol, position in open_positions.items()
        )

    def available_margin(self, open_positions):
        """Real cash still free to block as margin for new trades."""
        return self.starting_capital - self.used_margin(open_positions)

    def has_buying_power_for(self, open_positions, symbol, price, qty):
        """The gate core/engine.py's _enter() checks before opening
        ANY new position -- is there enough free MARGIN (real cash)
        to block for this trade at the stock's margin rate."""
        return self.margin_required(symbol, price, qty) \
            <= self.available_margin(open_positions)

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
