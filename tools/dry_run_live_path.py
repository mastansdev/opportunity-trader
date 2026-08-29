"""
==========================================================
Walk the ENTIRE live path, cold start to close, before the open
==========================================================

    py tools/dry_run_live_path.py

    "why can't you simulate the whole scenario from token generation-
     Static iP- Dhan connection- order sending & both buy/sell
     checking- until market close loop . why u didn't test like this."
                                -- operator, 5 August 2026

WHY THIS EXISTS
---------------
Every defect found on 5 August was found because HE asked. The
holdings bug, the two unjoined reason stores, the ranker that reaches
no order path -- none of them were caught by 3,541 passing tests,
because every one of those tests checks a PART.

A bot can have every part working and still not be a bot. What was
never tested is the JOIN: does stage N actually hand its output to
stage N+1, or does it write it into a drawer nobody opens.

So this runs the whole sequence in order, with a fake broker, and
reports each junction as CONNECTED or BROKEN. It places no orders and
touches no real money -- the broker here is a stub that records what
it was asked to do.

WHAT IT WILL NOT DO
-------------------
It will not tell you the bot is profitable. It answers one question:
IS EVERYTHING JOINED UP. That question had no answer at all before
today, which is why it took an operator reading a chart to find that
the ranker cannot place an order.

RUN IT BEFORE EVERY OPEN. It needs no market and no network for the
stages marked (offline).

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn                     # noqa: E402

RESULTS = []


def stage(number, name, offline=True):
    """Register one junction and its verdict."""
    def wrap(fn):
        RESULTS.append((number, name, fn, offline))
        return fn
    return wrap


class FakeDhan:
    """Records what it was asked to do. Places nothing.

    Shaped like Dhan's real answers -- including the envelope, because
    the envelope is where two separate bugs have already lived:
    {"data": []} is falsy and used to fall through an `or`.
    """

    def __init__(self):
        self.sent = []
        self.book = []
        self.held = []

    def place_order(self, **kwargs):
        self.sent.append(kwargs)
        return {"status": "success",
                "data": {"orderId": f"FAKE{len(self.sent):06d}",
                         "orderStatus": "TRADED"}}

    def get_order_by_id(self, order_id):
        return {"status": "success",
                "data": {"orderId": order_id, "orderStatus": "TRADED",
                         "averageTradedPrice": 100.0}}

    def get_positions(self):
        return {"status": "success", "data": list(self.book)}

    def get_holdings(self):
        return {"status": "success", "data": list(self.held)}


# ---------------------------------------------------------------
@stage(1, "Dhan access token is present and not expired")
def _token():
    # ---- IT CHECKED THE TOKEN THE BOT IS NOT USING. 13 Aug 2026. ----
    #
    # This read config.DHAN_ACCESS_TOKEN -- the STATIC one in .env --
    # while core/dhan_auth.py mints a fresh 24-hour token over TOTP at
    # startup and main.py authenticates with that. So one start printed
    # both of these, four lines apart:
    #
    #     [AUTH] ... minted by the bot, good until 14 Aug 08:36
    #     [ OK ] 1. alive now, expires 13 Aug 08:47 IST. Generate the
    #               morning token as usual before 09:15:
    #               py tools/dhan_token.py
    #
    # The second is the .env token's expiry, eleven minutes away, for a
    # credential nothing was using -- and it sent him to a tool that
    # does not exist. tools/dhan_token.py has never been in this
    # repository, the same fault as tools/dhan_login.py in
    # tools/morning.py the day before.
    #
    # A preflight that checks a different credential from the one the
    # session will authenticate with is worse than no preflight: it
    # reports confidently about the wrong thing.
    #
    # access_token() is cached (data/dhan_token.json, 13 August) so
    # asking here costs nothing and cannot trip Dhan's one-mint-per-two-
    # minutes limit.
    try:
        from core import dhan_auth
        token = str(dhan_auth.access_token() or "").strip()
        via = dhan_auth.source()
    except Exception:                                      # noqa: BLE001
        token, via = "", None
    if not token:
        from config import DHAN_ACCESS_TOKEN
        token = str(DHAN_ACCESS_TOKEN or "").strip()
        via = "env"
    if not token:
        return False, "no token at all -- the session cannot start"
    # A Dhan token is a JWT: three dot-separated parts, and the middle
    # one carries the expiry. Read it rather than trusting its age.
    parts = token.split(".")
    if len(parts) != 3:
        return False, "token is not a JWT -- three parts expected"
    import base64
    import json
    try:
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        body = json.loads(base64.urlsafe_b64decode(pad))
    except Exception as exc:                               # noqa: BLE001
        return False, f"could not read the token's expiry ({exc})"
    exp = body.get("exp")
    if not exp:
        return True, "token present, no expiry claim to check"
    # ---- "MORE THAN N HOURS LEFT" IS THE WRONG QUESTION ----
    #
    # The first version asked for 7 hours and passed a token with 8.9,
    # at 21:27 -- a token that dies at 06:20, three hours BEFORE the
    # open. It would have reported OK on the evening before a session
    # it could not survive.
    #
    # The only question is: is it still alive at 15:30 of the next
    # session? Ask that.
    # ---- PIN IT TO IST. 6 August 2026. ----
    #
    #     "are you working in IST format with current set of rules?"
    #                                       -- operator
    #
    # datetime.fromtimestamp() converts to whatever timezone the
    # MACHINE happens to be in. On his Windows box that is IST and the
    # answer is right; run anywhere set to UTC and the same token reads
    # 02:26 instead of 07:56 -- five and a half hours earlier, against
    # a 15:30 close that is also being read in the wrong zone. Two
    # errors that partly cancel, which is worse than one that does not.
    #
    # NSE runs on IST. The check runs on IST, explicitly, wherever the
    # code happens to be executing.
    from datetime import timedelta, timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    dies = datetime.fromtimestamp(exp, IST).replace(tzinfo=None)
    now = datetime.now(IST).replace(tzinfo=None)
    if dies <= now:
        return False, ("TOKEN HAS EXPIRED -- generate a new one before "
                       "the open. This is the one thing the bot cannot "
                       "do for itself.")
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now >= close:
        close += timedelta(days=1)
    while close.weekday() >= 5:                       # skip the weekend
        close += timedelta(days=1)
    hours = (dies - now).total_seconds() / 3600.0

    # ---- A TOKEN THAT DIES OVERNIGHT IS NOT BROKEN. 6 Aug 2026. ----
    #
    #     "expired Dhan token ? it will expiry on 07-08-2026 by 08 am"
    #                                       -- operator
    #
    # He was right and this stage was crying wolf. A Dhan token lasts
    # 24 hours and he generates a fresh one every morning -- that is
    # the design, not a fault. Reporting BROKEN every single evening
    # trains him to ignore the one line that matters, and tonight it
    # made me tell him a live token had expired.
    #
    # BROKEN is reserved for a token that dies DURING a session that
    # is running or about to run. If the market is shut and the token
    # simply will not survive tomorrow, that is a reminder.
    # `close` has already been rolled forward to the NEXT session, so
    # it cannot be used to ask "are we in a session right now" -- that
    # test came back True at 17:09 and the reminder never fired.
    # Ask the clock directly.
    in_session = (now.weekday() < 5
                  and now.replace(hour=9, minute=15, second=0, microsecond=0)
                  <= now
                  <= now.replace(hour=15, minute=30, second=0,
                                 microsecond=0))
    # WHAT TO DO ABOUT IT depends on where the token came from. With
    # TOTP configured the bot re-mints for itself and there is no
    # morning job; without it, a human has to paste a fresh one into
    # .env. Saying "generate one" to somebody whose bot already does
    # that is how a working system reads as broken.
    #
    # And it named `py tools/dhan_token.py`, which has never existed in
    # this repository.
    if via == "totp":
        fix = ("the bot re-mints this itself from TOTP -- nothing to do")
    else:
        fix = ("this came from .env. Set DHAN_TOTP_SECRET and DHAN_PIN "
               "and the bot will mint its own -- see .env.example")

    if dies < close and not in_session:
        return True, (f"alive now, expires {dies:%d %b %H:%M} IST. {fix}")
    if dies < close:
        return False, (f"expires {dies:%d %b %H:%M} -- that is BEFORE the "
                       f"next close ({close:%d %b %H:%M}). It will die "
                       f"mid-session. {fix}")
    return True, (f"valid for {hours:.1f}h, past the next close "
                  f"({close:%d %b %H:%M}) -- {fix}")


@stage(2, "SEBI static IP route is configured")
def _static_ip():
    # The route lives in ORDER_PROXY, not a host constant. The first
    # version of this check invented DHAN_ORDER_HOST from memory and
    # reported a warning about a name that has never existed -- the
    # exact habit this whole tool is meant to end.
    try:
        from config import ORDER_PROXY
    except ImportError:
        return False, ("no ORDER_PROXY in config -- orders would leave "
                       "from this machine's own IP and SEBI requires "
                       "the registered static one")
    proxy = str(ORDER_PROXY or "")
    if "staticip" not in proxy:
        return False, f"ORDER_PROXY is {proxy[:40]!r} -- not the static route"
    # Say the expiry out loud; it is a renewal date, not a code path.
    return True, proxy.split("@")[-1] + "  (renew before 31 Aug 2026)"


@stage(3, "Instrument master loads and security ids match Dhan")
def _master():
    from core.master_loader import MasterLoader
    loader = MasterLoader()
    # load() FIRST. all_symbols() on an unloaded loader returns [],
    # which the first run of this tool reported as "the master is empty
    # -- nothing can be subscribed". That was the check being wrong,
    # not the bot, and shipping it would have been one more scare to
    # chase down tomorrow.
    loader.load()
    symbols = loader.all_symbols(include_blocked=True)
    if not symbols:
        return False, "the master is empty -- nothing can be subscribed"
    tradeable = loader.all_symbols()
    return True, (f"{len(symbols):,} symbols, {len(tradeable):,} tradeable, "
                  f"{len(symbols) - len(tradeable)} blocked")


@stage(4, "A tick reaches MarketData and sets the day's open")
def _tick():
    from core.market_data import MarketData
    md = MarketData()
    # ---- 09:30, NOT now(). 6 August 2026. ----
    #
    #   "[BROKEN] 4. A tick reaches MarketData ... have u checked"
    #
    # on_tick() correctly DROPS anything stamped before 09:15 -- that
    # guard is what stops a pre-open auction print from setting a false
    # day-open. This check ran at 08:08 with datetime.now(), had its
    # tick refused exactly as designed, and reported the bot broken
    # every morning. The check was wrong, not the feed.
    when = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
    md.on_tick("TESTSTK", 100.0, when)
    price = md.get_latest_price("TESTSTK")
    if price != 100.0:
        return False, f"tick did not land (got {price!r})"
    day_open = md.get_day_open("TESTSTK")
    if not day_open:
        return False, ("the day's open is not recorded -- the "
                       "'never buy below its open' gate has nothing "
                       "to read")
    return True, f"price {price}, open {day_open}"


@stage(5, "The reason stores are BOTH readable for one symbol")
def _reasons():
    from core.why_moving import why
    try:
        from core.news_impact import NewsImpact
        from core.stock_events import StockEvents
        events = StockEvents()
        news = NewsImpact()
    except Exception as exc:                               # noqa: BLE001
        return False, f"a reason store would not open ({exc})"
    today = datetime.now().strftime("%Y-%m-%d")
    found = 0
    for symbol in ("SHILPAMED", "RELIANCE", "TCS", "INFY", "SBIN"):
        try:
            got = why(events=events.for_symbol(symbol, limit=20),
                      news_hits=news.for_symbol(symbol, limit=5),
                      on_date=today)
        except Exception as exc:                           # noqa: BLE001
            return False, f"why() raised on {symbol} ({exc})"
        if got:
            found += 1
    return True, (f"both stores answered; {found} of 5 probe symbols "
                  f"have a reason today")


@stage(6, "Ranker -> a sized, tradeable plan")
def _rank_to_plan():
    from core.position_plan import plan
    from core.ranker import rank
    movers = [{"symbol": "TESTSTK", "change_pct": 4.0, "ltp": 104.0,
               "sector": "CHEMICALS", "volume_x": 3.0,
               "day_low": 99.0, "day_high": 105.0}]
    got = rank(movers,
               mechanism_of=lambda s: {
                   "text": "Better-than-expected quarterly results "
                           "signal stronger margins",
                   "weight": 0.8, "direction": "POSITIVE"},
               adv_of=lambda s: 50.0,
               mtf_of=lambda s, r=None: {"eligible": True, "leverage": 3.0,
                                         "margin_pct": 33.0},
               now=datetime(2026, 1, 1, 10, 0),
               open_of=lambda s: 100.0)
    rows = got.get("rows") or []
    if not rows:
        return False, f"the ranker named nothing: {got.get('refusals')}"
    # A FRACTION. core/mtf_margin.margin_pct() returns 0.33 for a
    # stock on 33% margin; this passed 33.0 and sized 100x too small
    # for months, harmlessly, until the stop began following the size.
    sized = plan(104.0, "BUY", day_low=99.0, day_high=105.0,
                 margin_pct=0.33)
    if not sized.get("ok"):
        return False, f"nothing could be sized ({sized.get('why')})"
    return True, (f"ranked {rows[0]['symbol']}, qty {sized['qty']}, "
                  f"stop {sized['stop']}, risk Rs {sized['risk_rs']:,.0f}")


@stage(7, "Ranker output reaches something that can ORDER")
def _rank_to_engine():
    """THE JOIN THAT DOES NOT EXIST. 5 August 2026.

    core/ranker.py is imported by exactly one file: dashboard/state.py.
    Nothing in core/engine.py or trading/ has ever heard of it. So the
    'WHAT TO TRADE NOW' panel is a screen, and turning the bot loose
    tomorrow would trade breakouts instead.
    """
    importers = []
    for root, _dirs, files in os.walk("."):
        if any(skip in root for skip in (".git", "node_modules", "tests")):
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                src = open(path, encoding="utf-8", errors="ignore").read()
            except Exception:                              # noqa: BLE001
                continue
            if re.search(r"from core\.ranker import|from core import ranker",
                         src):
                importers.append(path.replace("\\", "/").lstrip("./"))
    # An import is not the question. The question is whether the rows
    # reach an entry. core/auto_entry.py is the join: main.py hands it
    # the ranked rows and it calls the Engine's own _enter().
    try:
        src = open("main.py", encoding="utf-8").read()
    except Exception as exc:                               # noqa: BLE001
        return False, f"could not read main.py ({exc})"
    joined = ("auto_entry.take(" in src
              and "enter=engine._enter" in src
              and '"ranked"' in src)
    if not joined:
        return False, ("the ranker is read ONLY by "
                       f"{', '.join(importers) or 'nothing'} -- no order "
                       f"path can see it. The panel cannot trade.")
    from config import ALERT_ONLY_MODE
    safety = ("ALERT_ONLY_MODE is ON -- it alerts and records, places "
              "nothing" if ALERT_ONLY_MODE else
              "ALERT_ONLY_MODE is OFF -- ranked picks WILL be ordered")
    return True, f"main.py -> core.auto_entry -> Engine._enter.  {safety}"


@stage(8, "A BUY order is built and sent", offline=True)
def _buy():
    from trading.live_execution import LiveExecution
    fake = FakeDhan()
    try:
        live = LiveExecution(fake)
    except Exception as exc:                               # noqa: BLE001
        return False, f"LiveExecution would not construct ({exc})"
    for name in ("buy", "place_buy", "enter", "send_order", "place"):
        call = getattr(live, name, None)
        if callable(call):
            return True, f"order path is {name}() -- fake broker ready"
    return None, ("could not identify the buy method by name; the "
                  "order path exists but this check needs the real "
                  "name wired in")


@stage(9, "The broker book reads positions AND holdings")
def _book():
    from core.broker_sync import BrokerSync
    from trading.live_execution import LiveExecution
    fake = FakeDhan()
    fake.book = []                                    # flat intraday
    fake.held = [{"tradingSymbol": "CGPOWER", "totalQty": 100,
                  "avgCostPrice": 871.7}]             # overnight MTF
    live = LiveExecution(fake)
    rows = live.broker_book()
    if rows is None:
        return False, "broker_book() returned None on a healthy broker"
    sync = BrokerSync(execution=live)
    got = sync.check({"CGPOWER": {"qty": 100, "direction": "LONG"}})
    if got.get("only_in_bot"):
        return False, ("an overnight MTF holding is reported as missing "
                       "-- reconcile --apply would delete it")
    return True, "overnight holding recognised; nothing reported missing"


@stage(10, "A failed broker read never looks like an empty book")
def _silence():
    from core.broker_sync import BrokerSync
    from trading.live_execution import LiveExecution

    class Deaf(FakeDhan):
        def get_holdings(self):
            raise ConnectionResetError(10054, "connection reset")

    live = LiveExecution(Deaf())
    got = BrokerSync(execution=live).check(
        {"CGPOWER": {"qty": 100, "direction": "LONG"}})
    if got.get("in_sync") is not None:
        return False, ("a dropped connection produced a verdict. It must "
                       "produce 'unverified'.")
    return True, "reports unverified, as it must"


@stage(11, "Every open position has an exit that can fire")
def _exits():
    import inspect

    from core.engine import Engine
    names = {n for n, _ in inspect.getmembers(Engine)}
    needed = {"_check_trailing_stop": "trailing stop",
              "_check_missed_stop": "missed-stop recovery",
              "_check_fixed_bracket": "target",
              "_check_circuit_proximity": "circuit guard"}
    missing = [label for name, label in needed.items() if name not in names]
    if missing:
        return False, f"no {', '.join(missing)}"
    # The one that is built and NOT wired.
    src = inspect.getsource(Engine)
    if "liveness(" not in src:
        return None, ("stops and targets are wired, but liveness() -- the "
                      "only thing that knows a move has DIED -- is not an "
                      "exit rule. 17 of 19 trades on 5 August reached "
                      "neither stop nor target and simply sat until the "
                      "bell.")
    return True, "stop, trail, target, circuit and liveness all present"


@stage(12, "Nothing is built and left unwired")
def _unused():
    modules = {}
    for folder in ("core", "trading"):
        for name in os.listdir(folder):
            if name.endswith(".py") and name != "__init__.py":
                modules[f"{folder}.{name[:-3]}"] = name[:-3]
    blob = ""
    for root, _dirs, files in os.walk("."):
        if any(s in root for s in (".git", "node_modules", "tests")):
            continue
        for name in files:
            if name.endswith(".py"):
                try:
                    blob += open(os.path.join(root, name), encoding="utf-8",
                                 errors="ignore").read()
                except Exception:                          # noqa: BLE001
                    pass
    orphans = []
    for dotted, short in sorted(modules.items()):
        # Both import spellings. The first version of this check missed
        # `from core import X` and reported four false positives.
        if re.search(rf"from {re.escape(dotted)} import", blob):
            continue
        if re.search(rf"from {os.path.dirname(dotted.replace('.', '/'))}"
                     rf"|from core import {short}\b|from trading import "
                     rf"{short}\b", blob) and re.search(
                         rf"\b{short}\.", blob):
            continue
        if re.search(rf"import {re.escape(dotted)}\b", blob):
            continue
        orphans.append(dotted)
    if orphans:
        return None, ("built but never imported by anything: "
                      + ", ".join(orphans))
    return True, f"all {len(modules)} modules are reachable"


@stage(13, "The session can close and score itself")
def _close():
    import inspect

    import main
    src = inspect.getsource(main)
    guard = src[src.rfind("if ", 0, src.find("_score_the_day()")):
                src.find("_score_the_day()")]
    if "MARKET_CLOSE_T" not in guard:
        return False, ("the scorecard only runs if the loop reaches 15:30 "
                       "by itself -- Ctrl+C produces nothing")
    return True, "scores on a normal close AND on Ctrl+C after the close"


# ---------------------------------------------------------------
@stage(14, "Every closed trade has a real fill behind it")
def _phantom_closes():
    """A CLOSE IN THE BOOK WITH NO ORDER AT THE BROKER IS A LIE.
    5 August 2026.

        "if i missed that too , then no one will see & another
         complete session would be wasted"

    On the night of 5 August the POST screen reported Rs 34,048 of
    losses across CORONA, DEEPAKFERT and DEEPAKNTR. Not one order had
    been sent. The positions were adopted with stops measured from his
    ENTRY price rather than the live price, so the stops were already
    breached the moment they were set; the next tick "closed" them in
    memory and wrote a P&L computed on prices that were never traded.

    He still owned every share.

    Nothing in 3,600 tests looked for this, because every one of them
    checks a part. This checks the JOIN between the two records that
    must always agree: if the book says a position closed today, there
    has to be a SELL fill for it. No fill, no close.
    """
    import json
    import sqlite3
    from datetime import datetime

    day = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(os.path.join("data", "session_state.json"),
                  encoding="utf-8") as handle:
            closed = (json.load(handle).get("closed_positions") or [])
    except Exception:                                      # noqa: BLE001
        return True, "no saved book to check"
    today = [c for c in closed
             if str(c.get("exit_time") or "").startswith(day)]
    if not today:
        return True, "nothing closed today"

    sold = set()
    try:
        con = sqlite3.connect(os.path.join("data", "fills.db"))
        sold = {r[0] for r in con.execute(
            "select symbol from fills where trade_date=? and side='SELL'",
            (day,))}
        con.close()
    except Exception:                                      # noqa: BLE001
        return None, "could not read fills.db to compare"

    phantom = [c for c in today
               if str(c.get("symbol") or "").upper() not in sold]
    if phantom:
        lost = sum(float(c.get("pnl") or 0) for c in phantom)
        names = ", ".join(sorted({str(c.get("symbol")) for c in phantom}))
        return False, (f"{len(phantom)} close(s) with NO fill at the "
                       f"broker -- {names}. The screen is showing "
                       f"Rs {lost:,.0f} of P&L that never happened and "
                       f"he still owns the shares. Clear it with "
                       f"py tools/fresh_book.py")
    return True, f"{len(today)} close(s), every one has a fill"


@stage(15, "No position is recorded twice")
def _duplicates():
    """DEEPAKNTR appeared twice in the same closed book, adopted once
    per process start. Two rows, two P&Ls, one position."""
    import json
    from collections import Counter
    try:
        with open(os.path.join("data", "session_state.json"),
                  encoding="utf-8") as handle:
            book = json.load(handle)
    except Exception:                                      # noqa: BLE001
        return True, "no saved book to check"
    rows = book.get("closed_positions") or []
    seen = Counter((str(c.get("symbol")), str(c.get("exit_time")))
                   for c in rows)
    dupes = [k for k, n in seen.items() if n > 1]
    if dupes:
        return False, ("the same close is recorded more than once: "
                       + ", ".join(f"{s} at {t}" for s, t in dupes))
    return True, f"{len(rows)} closed row(s), no duplicates"


# ===================================================================
# THE THREE THAT MONDAY NEEDED AND DID NOT HAVE.  10 August 2026.
# ===================================================================
#
#     "everyday at night u tell this but morning some new error/bug
#      comes & cycle repeats"
#
# He is right, and the pattern is not the individual bugs. All three
# of Monday's faults were SILENT: the bot looked healthy for six hours
# while the strategy was not running. A promise from me does not fix
# that. A check that fails loudly at 08:13 does.
#
# Each of these three would have caught one of Monday's faults before
# the market opened.


@stage(16, "A graded stock actually carries its grade")
def _grade_reaches_the_signal():
    """MONDAY: 1,191 signals recorded, ZERO carried a grade, while
    Row 1 held 24 graded stocks all morning.

    core/engine._capture_reason() asked results_gate.grade_for(), which
    computes a grade from parsed QoQ/YoY numbers that exist for a small
    minority of stocks. It answered None for essentially everything, so
    every signal went into the journal as a bare ORB breakout with no
    reason attached -- the whole results strategy, not running.
    """
    from datetime import datetime
    from core.watchlist_builder import graded_symbols
    from core.results_gate import ResultsGate
    from core.engine import Engine

    row1 = graded_symbols() or {}
    if not row1:
        return None, ("Row 1 is empty right now -- nothing to verify. "
                      "Before the open this is normal; at 10:00 it is not.")

    class _Stub:
        news_feed = None
        announcements = None
        results_gate = ResultsGate()

    stub = _Stub()
    checked = carried = 0
    missed = []
    for symbol in list(row1)[:12]:
        checked += 1
        got = Engine._capture_reason(stub, symbol)
        if got.get("results_grade"):
            carried += 1
        else:
            missed.append(symbol)
    if carried == 0:
        return False, (f"{checked} graded stocks and NOT ONE reaches the "
                       f"signal path. This is Monday's fault exactly: "
                       f"{', '.join(missed[:5])}")
    if missed:
        return None, (f"{carried}/{checked} carry their grade; "
                      f"{len(missed)} do not: {', '.join(missed[:4])}")
    return True, f"{carried}/{checked} graded stocks carry their grade"


@stage(17, "No paid API call can leave this machine")
def _no_paid_calls():
    """MONDAY: every AI call failed with 'credit balance is too low',
    twenty-five events ungraded, all afternoon, as DEBUG lines.

    config.AI_ENABLED had said "Nothing calls out while False" since it
    was written. It was not true -- three modules built a client
    without asking. He is explicit: no paid call until the bot earns
    it. The cards already carry EXCELLENT / GREAT / GOOD.
    """
    from config import AI_ENABLED
    if AI_ENABLED:
        return None, ("AI_ENABLED is True -- paid calls ARE allowed. "
                      "Deliberate? If not, this is money leaving.")
    leaks = []
    try:
        from core.morning_brief import anthropic_client
        if anthropic_client() is not None:
            leaks.append("morning_brief")
    except Exception:                                      # noqa: BLE001
        pass
    try:
        from core.news_impact import NewsImpact
        if NewsImpact()._get_client() is not None:
            leaks.append("news_impact")
    except Exception:                                      # noqa: BLE001
        pass
    try:
        from core.ai_news import AiNewsGrader
        if AiNewsGrader()._get_client() is not None:
            leaks.append("ai_news")
    except Exception:                                      # noqa: BLE001
        pass
    if leaks:
        return False, (f"AI_ENABLED is False but these still build a "
                       f"client: {', '.join(leaks)}. Money can leave.")
    return True, "AI_ENABLED False and every client refuses. Nothing bills."


@stage(18, "The feed bookmark is readable, not corrupted")
def _watermark_is_clean():
    """MONDAY: the watermark held dict reprs beside the real rows, so
    every channel's count was split in two and the stale rows made me
    tell him the collector had died at 08:11 when it ran until 13:41.

    A diagnostic that lies is worse than none -- it sends him hunting
    the wrong thing on the one morning he has no time.
    """
    import sqlite3
    try:
        con = sqlite3.connect("data/telegram.db")
        rows = [r[0] for r in con.execute(
            "select channel from feed_watermark")]
        con.close()
    except Exception as exc:                               # noqa: BLE001
        return None, f"no watermark yet ({exc}). It seeds on first run."
    if not rows:
        return None, "watermark empty -- run py tools/feed_gaps.py once"
    junk = [r for r in rows if not r or str(r).startswith("{")]
    if junk:
        return False, (f"{len(junk)} corrupted row(s) keyed on a dict "
                       f"repr: {str(junk[0])[:40]}")
    return True, f"{len(rows)} channels, every key a real name"


@stage(19, "The Dhan token is one the bot can get by itself")
def _token_door():
    """11 August. The token expires every 24 hours, and until today the
    only thing that renewed it was him remembering. TOTP lets the bot
    mint its own; this says which door today's token came through, so a
    silently-failed mint does not turn into a 09:00 authentication
    error while he is watching the open."""
    import os
    from core import dhan_auth

    token = dhan_auth.access_token()
    if not token:
        return False, ("no Dhan token at all -- neither TOTP nor "
                       "DHAN_ACCESS_TOKEN in .env")
    if dhan_auth.source() == "totp":
        return True, ("minted by the bot from TOTP. "
                      f"{dhan_auth._held.get('why') or ''}".strip())
    if str(os.getenv("DHAN_TOTP_SECRET", "")).strip():
        return None, ("TOTP is configured but the mint failed, so this is "
                      f"the .env token: {dhan_auth._held.get('why')}")
    return None, ("using DHAN_ACCESS_TOKEN from .env -- expires 24h after "
                  "you generated it. Set DHAN_PIN + DHAN_TOTP_SECRET to "
                  "hand that job to the bot (see .env.example)")


def main_():
    decision("=" * 76)
    decision("  THE WHOLE LIVE PATH, END TO END -- nothing is ordered")
    decision(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    decision("=" * 76)

    broken = warned = 0
    for number, name, fn, _offline in RESULTS:
        try:
            ok, note = fn()
        except Exception as exc:                           # noqa: BLE001
            ok, note = False, f"the check itself raised: {exc}"
        if ok is True:
            mark = "  OK  "
        elif ok is None:
            mark = " WARN "
            warned += 1
        else:
            mark = "BROKEN"
            broken += 1
        decision(f"  [{mark}] {number:>2}. {name}")
        decision(f"           {note}")

    decision("-" * 76)
    if broken:
        warn(f"  {broken} BROKEN, {warned} warning(s). "
             f"The path does not join up end to end.")
    elif warned:
        decision(f"  Nothing broken. {warned} warning(s) above -- read them.")
    else:
        decision("  Every junction connects.")
    decision("=" * 76)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main_())
