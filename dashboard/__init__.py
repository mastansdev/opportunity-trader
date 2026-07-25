"""
==========================================================
Dashboard
==========================================================

Live, read-only view onto the trading engine plus a small set
of operator actions (manual BUY/SELL), served over a local
FastAPI + WebSocket server (dashboard/server.py) and a single
static HTML page (dashboard/static/index.html).

Nothing here ever mutates engine state directly from the
server thread -- state.py builds a read-only snapshot on a
timer from the main loop, and server.py only ever reads that
snapshot or forwards a REQUEST (never an action) into
trading/trade_controller.py, picked up on the engine's own
tick thread. Same reasoning as everywhere else in this
codebase: one thread owns the engine, everyone else asks.

Author : H&M Opportunity Trader
==========================================================
"""
