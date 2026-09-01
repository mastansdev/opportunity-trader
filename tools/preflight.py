"""
==========================================================
PRE-FLIGHT -- run this at 08:45, before you start the bot
==========================================================

    py tools/preflight.py

Checks everything that can be checked WITHOUT the market being open. If
something is wrong, you find out at 08:45 when a restart costs nothing
-- instead of at 09:20, when it costs the session.

WHY THIS EXISTS
---------------
2026-07-28: the bot restarted three times inside 09:15-09:30. Every one
of those restarts put a multi-minute hole in the feed during the opening
range, 607 of 666 symbols were flagged unreliable, and the bot placed
zero automated trades. Worse, the log became unreadable -- three of that
day's audit findings turned out to be wrong because several processes
were writing to the same file.

The rule that came out of it: ONE start before 09:15, ZERO restarts.
This script is what makes that rule keepable.

It reads. It never writes, never places an order, never starts a feed.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, WARN, FAIL = "ok", "warn", "FAIL"
_results = []


def check(name, state, detail=""):
    _results.append((state, name, detail))
    mark = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}[state]
    print(f"[{mark}] {name}" + (f"\n         {detail}" if detail else ""))


def _trading_days_behind(latest, today):
    """Sessions missed between the newest stored bar and today.

    Weekends only -- holidays are not known here, so this can read one
    or two high on a holiday week. It errs toward TELLING you, which is
    the right direction for a freshness check.
    """
    missed = 0
    day = latest
    while day < today:
        day += timedelta(days=1)
        if day.weekday() < 5 and day < today:
            missed += 1
    return missed


def _check_daily_history(auto_fill=True):
    """How current is the 50-day history, and top it up if it is not."""
    try:
        import sqlite3
        db = os.path.join("data", "daily_candles.db")
        if not os.path.exists(db):
            check("daily history", WARN,
                  "data/daily_candles.db missing -- run "
                  "py tools/build_daily_history.py")
            return

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        latest = con.execute("select max(date) from daily_bars").fetchone()[0]
        con.close()
        if not latest:
            check("daily history", WARN, "no bars stored yet")
            return

        latest_date = datetime.strptime(latest, "%Y-%m-%d").date()
        today = datetime.now().date()
        behind = _trading_days_behind(latest_date, today)

        if behind <= 0:
            check("daily history", OK, f"current to {latest}")
            return

        if not auto_fill:
            check("daily history", WARN,
                  f"newest bar is {latest} -- about {behind} session(s) "
                  f"behind (--no-fetch given, not topping up)")
            return

        print(f"    fetching {behind} missing session(s) of NSE bhavcopy...")
        from tools.build_daily_history import build
        build(days=max(behind + 2, 5))

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        now_latest = con.execute("select max(date) from daily_bars").fetchone()[0]
        con.close()
        still = _trading_days_behind(
            datetime.strptime(now_latest, "%Y-%m-%d").date(), today)
        check("daily history", OK if still <= 0 else WARN,
              f"current to {now_latest}" if still <= 0 else
              f"newest bar is {now_latest} -- still about {still} "
              f"session(s) behind (holiday, or NSE has not published yet)")
    except Exception as exc:                               # noqa: BLE001
        # A freshness check must never stop the morning.
        check("daily history", WARN, f"could not check ({exc})")


SCRIP_PROOF = os.path.join("data", "scrip_verified.json")
SCRIP_MAX_AGE_DAYS = 7


def _check_security_ids(max_age_days=SCRIP_MAX_AGE_DAYS):
    """Are we buying the company we think we are buying?

    THE WORST FAILURE THIS BOT CAN HAVE. Every order is sent by
    SECURITY ID, not by symbol. If data/master_stocks.csv says KAYNES
    is 15083 and Dhan says 15083 is a different company, the bot
    decides on KAYNES, buys something else entirely, and every screen
    -- dashboard, logs, trade memory -- says KAYNES. In PAPER mode it
    is a wrong number in a database. With real money it is a position
    in a company nobody chose, sized on the wrong stock's ATR, with a
    stop computed from the wrong stock's price.

    Nothing checked this before a live session. tools/
    verify_master_database.py has existed and could be run by hand;
    "could be run by hand" is not a control when the consequence is
    this one.

    The proof is CACHED, because the scrip master is a large download
    and 08:45 is not the time for it. What is checked here every
    morning is that the proof exists, is recent, and passed. Re-verify
    with:

        py tools/verify_master_database.py

    LIVE mode with no proof is a FAIL, not a warning. That is the
    whole point of the check.
    """
    import json

    # 31 July 2026: THIS CHECK HAD NEVER ONCE BEEN ABLE TO FAIL.
    #
    # It read `from config import PAPER_TRADING`. There is no
    # PAPER_TRADING in config.py and there never has been -- the flag
    # is TRADING_MODE. The ImportError was swallowed by the bare except
    # below it, `live` stayed False, and every FAIL in this function
    # silently downgraded to a WARN.
    #
    # So the check documented above as "LIVE mode with no proof is a
    # FAIL, not a warning -- that is the whole point of the check" was
    # disarmed from the day it was written. On 30 July this file found
    # six wrong security ids, one of them CHOLAFIN pointing at 685
    # instead of 19257. On a LIVE morning it would have said WARN and
    # the operator would have started anyway.
    #
    # A guard that cannot fire is worse than no guard, because it is
    # believed. Read the real name, and let the failure be loud.
    live = False
    try:
        from config import TRADING_MODE
        live = str(TRADING_MODE).upper() == "LIVE"
    except ImportError as exc:                             # noqa: BLE001
        check("security IDs", FAIL,
              f"cannot read TRADING_MODE from config.py ({exc}) -- refusing "
              f"to guess which mode this session is in")
        return

    try:
        with open(SCRIP_PROOF, encoding="utf-8") as fh:
            proof = json.load(fh)
    except (OSError, ValueError):
        check("security IDs", FAIL if live else WARN,
              "NEVER VERIFIED against Dhan's scrip master -- the bot could "
              "be buying a different company than it decided on. Fix with: "
              "py tools/verify_master_database.py")
        return

    when = proof.get("verified_at") or ""
    mismatches = proof.get("mismatches") or []
    missing = proof.get("not_found") or []
    checked = proof.get("checked") or 0

    if mismatches:
        check("security IDs", FAIL,
              f"{len(mismatches)} symbol(s) point at the WRONG security id "
              f"-- e.g. {mismatches[0]}. DO NOT TRADE until "
              f"data/master_stocks.csv is corrected.")
        return

    age_days = None
    try:
        age_days = (datetime.now()
                    - datetime.strptime(when[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        pass

    if age_days is None:
        check("security IDs", WARN, f"proof file has no readable date ({when})")
    elif age_days > max_age_days:
        # Symbols get delisted and ids do occasionally change.
        check("security IDs", FAIL if live else WARN,
              f"last verified {age_days} days ago ({when}) -- re-run "
              f"py tools/verify_master_database.py")
    else:
        detail = f"{checked} checked, all match (verified {when[:10]})"
        if missing:
            detail += (f"; {len(missing)} not in Dhan's list at all "
                       f"-- e.g. {missing[:3]}")
        check("security IDs", WARN if missing else OK, detail)


def main():
    print("=" * 72)
    print(f"  PRE-FLIGHT  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 72 + "\n")

    # ---- the one that wasted a session ----
    flag = os.path.join("data", "entries_paused.flag")
    if os.path.exists(flag):
        check("pause flag", FAIL,
              f"{flag} EXISTS. The bot will start with entries PAUSED, "
              f"silently. Delete it.")
    else:
        check("pause flag", OK, "absent -- entries will be live")

    # ---- config ----
    try:
        import config
        mode = config.TRADING_MODE.upper()
        if mode == "LIVE":
            if not config.I_UNDERSTAND_THIS_PLACES_REAL_ORDERS:
                check("trading mode", FAIL,
                      "LIVE without the second switch -- the bot will refuse "
                      "to start")
            else:
                check("trading mode", WARN,
                      "LIVE. Orders placed today are REAL.")
            # WHO is allowed to spend the money. On 31 July this file
            # printed "Orders placed today are REAL" and said nothing
            # about either of these -- which reads as "the bot is
            # trading" when the plan was one order placed by hand.
            # ---- TWO MODES, SO TWO LINES. 31 August 2026. ----
            #
            # These two lines described a third mode that no longer
            # exists, and the first of them said something now flatly
            # untrue: "only orders YOU click are sent". Every order is
            # sent when the switch is ON. A preflight that reassures him
            # about a guard that was removed is worse than no preflight.
            check("switch", OK,
                  "starts OFF -- paper trades. Click ON for real money.")
            check("what changes when you click ON", OK,
                  "only where the order goes. Same stocks, same sizes, "
                  "same stops.")
            qty = getattr(config, "MANUAL_TEST_QTY", None)
            if qty:
                check("manual order size", WARN,
                      f"MANUAL_TEST_QTY = {qty} -- every BUY you click "
                      f"places {qty} share(s), NOT the risk-sized "
                      f"quantity. Correct for a first live test; set it "
                      f"to None the moment the test is over. A test size "
                      f"must never quietly become the size you trade.")
        else:
            check("trading mode", OK, f"{mode} -- no real money at risk")

        check("square-off at 15:15", OK,
              "OFF -- positions carry overnight (MTF)"
              if not config.FORCE_SQUARE_OFF_AT_CLOSE else
              "ON -- everything will be flattened at 15:15")
        check("market regime gate", OK,
              "OFF -- longs allowed on a red tape"
              if not config.ENABLE_MARKET_REGIME_GATE else
              "ON -- longs blocked when the tape is broadly red")
        # 2026-07-29: this said "2.5% from the peak, moves only on a
        # new high" -- which stopped being true the evening the trail
        # was removed. A pre-flight that describes yesterday's bot is
        # worse than one that says nothing, because it is read at 08:45
        # and believed.
        # ---- SHOW TODAY'S RULES, NOT JULY'S. 1 September 2026. ----
        #
        #     "why either bot or user needs to see the old methods under
        #      new working mechansim ... bot needs to show the current
        #      set of rules, thats plain simple right"
        #
        # This printed a WARNING every morning saying the trailing stop
        # "cost Rs 22,626 over 3 sessions". That measurement is real and
        # it is about a bot that no longer exists:
        #
        #   * 27-29 July, on the 35 STRUCTURAL breakout entries
        #   * that lane is switched off -- engine.breakout_armed is
        #     False and _try_structural_entry returns immediately
        #   * it was FIRST-COME: it bought whatever broke out first as
        #     ticks arrived, with no score and no comparison. The
        #     current path sorts by score and takes rank 1
        #   * no reason gate, different sizing, different exits
        #
        # So it warned about a rule, on a lane, that the bot does not
        # run, using a number measured before every part of the entry
        # changed. Three lines above, this file's own comment says a
        # pre-flight that describes yesterday's bot is worse than one
        # that says nothing, "because it is read at 08:45 and believed".
        #
        # It now lists the ways a position can actually end today, read
        # from the settings rather than recited. When the exits change
        # again, this line changes with them.
        # ---- AND I PUT THE WRONG STOP IN THIS LINE. 1 Sept 2026. ----
        #
        # The first version of this said "stop 0.8x ATR from entry",
        # read straight off ATR_STOP_MULTIPLIER. He read it and said
        # 0.8 was far too narrow and had been changed long ago.
        #
        # He was right. That branch is an `elif` under
        # VOLATILITY_SCALED_STOP, which is True, so it cannot be
        # reached -- its own comment says it was demoted because "0.8 x
        # a one-minute ATR sits under the 1% floor on every stock".
        #
        # The live stop is 2.0 x the stock's own DAILY ATR, floored and
        # capped. On real names: ASHOKA 5.53%, DIFFNKG 6.00% (capped).
        #
        # So the same mistake this whole check was written to fix --
        # printing a number that describes code the bot does not run --
        # went straight back in, in the fix. It is read off the live
        # branch now, in the same order the engine chooses it.
        exits = ["buying dries up (order flow)"]
        if config.ENABLE_BOT_TRAILING_STOP:
            exits.append(f"trailing stop {config.ATR_TRAIL_MULTIPLIER}x ATR")
        if config.FIXED_STOP_PCT:
            exits.append(f"stop {float(config.FIXED_STOP_PCT):.1f}% flat")
        elif config.VOLATILITY_SCALED_STOP:
            exits.append(f"stop {config.DAILY_ATR_STOP_MULT}x the stock's "
                         f"own DAILY ATR")
        else:
            exits.append(f"stop {config.HARD_STOP_FROM_ENTRY_PCT * 100:.1f}% "
                         f"from entry")
        if config.FORCE_SQUARE_OFF_AT_CLOSE:
            exits.append(f"square-off at {config.SQUARE_OFF_TIME}")
        check("how a position ends", OK, " / ".join(exits)
              + "  (no profit target on the bot's own entries)")
        check("partial exit", OK,
              "OFF" if not config.ENABLE_PARTIAL_EXIT else
              f"ON -- books {config.PARTIAL_EXIT_FRACTION * 100:.0f}% at "
              f"{config.PARTIAL_EXIT_ATR_MULTIPLE}x ATR")
        check("position sizing", OK,
              f"Rs {config.MTF_MARGIN_PER_POSITION_RS:,.0f} of margin per "
              f"position, share count from Dhan")
        check("volume gate", OK,
              f"breakout must trade {config.VOLUME_SURGE_MULT}x its own "
              f"average"
              + ("; unmeasurable volume is REFUSED"
                 if config.VOLUME_REQUIRED_FOR_ENTRY else
                 "; unmeasurable volume is allowed through"))
        check("slot rotation", OK,
              f"ON -- at most {config.ROTATION_MAX_PER_DAY} swaps a day, "
              f"your own positions never swapped"
              if config.ENABLE_SLOT_ROTATION else
              "OFF -- a full book simply refuses new breakouts")
        check("circuit rule", OK,
              "direction-aware -- a long near its UPPER circuit is held"
              if config.CIRCUIT_RULE_DIRECTION_AWARE else
              "blanket -- closes near EITHER limit, including winners")
        check("daily limits", OK,
              f"stop new entries at -Rs {config.DAILY_MAX_LOSS_RS:,.0f} "
              f"or +Rs {config.DAILY_PROFIT_TARGET_RS:,.0f} "
              f"(about {config.DAILY_MAX_LOSS_RS / (config.MTF_MARGIN_PER_POSITION_RS * 3.8 * config.HARD_STOP_FROM_ENTRY_PCT):.0f} "
              f"failed trades)")
        check("staleness", OK,
              f"per-symbol, {config.STALENESS_MULTIPLE:.0f}x each stock's "
              f"own normal gap")
    except Exception as exc:                               # noqa: BLE001
        check("config", FAIL, str(exc))
        return _summary()

    # ---- credentials ----
    for var in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"):
        check(var, OK if os.environ.get(var) else FAIL,
              "set" if os.environ.get(var) else "NOT SET -- the feed cannot "
              "connect")

    # ---- CAN IT ACTUALLY START? ----
    #
    # 31 July 2026, 09:00. This file had run at 08:45 and printed
    # "Ready. Start the bot BEFORE 09:15." Fifteen minutes later
    # main.py died on the first line of trading:
    #
    #   RuntimeError: TRADING_MODE is LIVE but no Dhan client was
    #   provided. Refusing to start.
    #
    # Everything above this point checks SWITCHES -- what config says,
    # what files exist, whether modules import. Not one line of it
    # asked the only question that mattered: does the order path
    # actually build in the mode this session will run in?
    #
    # It takes about a second, it touches no network, and it places
    # nothing. It is the cheapest check in this file and it is the one
    # whose absence cost the session.
    try:
        from core.engine import Engine
        client = None
        if mode == "LIVE":
            from dhanhq import DhanContext, dhanhq as DhanRestClient
            from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
            # Constructing the context and the REST client is offline --
            # no request leaves the machine until a method is called,
            # and none is called here.
            client = DhanRestClient(DhanContext(DHAN_CLIENT_ID,
                                                DHAN_ACCESS_TOKEN))
        probe = Engine(dhan_client=client)
        if probe.execution.mode != mode:
            check("order path", FAIL,
                  f"config says {mode} but the engine built a "
                  f"{probe.execution.mode} executor. Do not start.")
        elif mode == "LIVE":
            # A LIVE executor with no price feed refuses every order it
            # is given -- "no live price feed to check against". That
            # is correct behaviour and it looks exactly like a broken
            # broker, so say now that the real Engine gets one.
            check("order path", OK,
                  "builds LIVE, drift check wired, nothing sent")
        else:
            check("order path", OK, f"builds {probe.execution.mode} cleanly")
    except Exception as exc:                               # noqa: BLE001
        check("order path", FAIL,
              f"the engine CANNOT START in {mode}: {exc}")

    # ---- data files ----
    for path, label in ((os.path.join("data", "master_stocks.csv"),
                         "master stock database"),
                        (os.path.join("data", "trade_memory.db"),
                         "trade memory"),
                        (os.path.join("data", "quarterly_results.db"),
                         "quarterly results"),
                        (os.path.join("data", "results_calendar.db"),
                         "results calendar")):
        if os.path.exists(path):
            check(label, OK, f"{os.path.getsize(path) / 1024:,.0f} KB")
        else:
            check(label, WARN, f"{path} missing")

    _check_security_ids()

    # ---- who reports today ----
    try:
        import sqlite3
        today = datetime.now().date().isoformat()
        con = sqlite3.connect(
            f"file:{os.path.join('data', 'results_calendar.db')}?mode=ro",
            uri=True, timeout=5)
        n = con.execute("select count(distinct symbol) from results_events "
                        "where results_date=?", (today,)).fetchone()[0]
        check("companies reporting today", OK,
              f"{n} -- each is blocked until its numbers land, then allowed "
              f"only if STRONG or GOOD")
    except Exception as exc:                               # noqa: BLE001
        check("results calendar read", WARN, str(exc))

    # ---- modules import cleanly ----
    failed = []
    for module in ("core.engine", "core.breakout_feed", "core.results_gate",
                   "core.mtf_margin", "core.market_data", "core.trade_memory",
                   "trading.execution", "trading.charges", "trading.slippage",
                   "dashboard.state"):
        try:
            __import__(module)
        except Exception as exc:                           # noqa: BLE001
            failed.append(f"{module}: {exc}")
    check("modules import", OK if not failed else FAIL,
          "all clean" if not failed else "; ".join(failed))

    # ---- trade memory has the reason columns ----
    #
    # Read on a COPY, not the live file. Opening the real database even
    # read-only made SQLite reach for a journal and report "attempt to
    # write a readonly database" -- a false alarm on 2026-07-28 that I
    # first blamed on the sandbox and then on the operator's machine.
    # A pre-flight that cries wolf trains you to ignore it.
    try:
        import shutil
        import sqlite3
        import tempfile
        source = os.path.join("data", "trade_memory.db")
        if not os.path.exists(source):
            check("reason columns", WARN,
                  "no trade memory yet -- it is created on the first start")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                copy = os.path.join(tmp, "tm.db")
                shutil.copy2(source, copy)
                con = sqlite3.connect(copy, timeout=5)
                cols = {r[1] for r in
                        con.execute("PRAGMA table_info(trade_memory)")}
                con.close()
            missing = {"had_reason", "news_kind", "results_grade"} - cols
            check("reason columns", OK if not missing else WARN,
                  "present" if not missing else
                  f"missing {sorted(missing)} -- added automatically on the "
                  f"first start, so this clears itself")
    except Exception as exc:                               # noqa: BLE001
        check("reason columns", WARN, f"could not read ({exc})")

    # ---- daily history freshness, 2026-07-29 -------------------
    #
    # Found on 29 July: data/daily_candles.db and the bhavcopy folder
    # both stopped at 27 July -- two sessions behind, with nothing
    # anywhere that downloads them. tools/build_daily_history.py has
    # existed all along; nobody ran it.
    #
    # What it feeds: each stock's 50-day median volume, median turnover
    # and 50-day moving average -- the Shortlist's "normals", including
    # the MIN_TURNOVER filter that keeps illiquid names out.
    #
    # Two missing days out of fifty barely move a median, so the damage
    # today is small. The point is DRIFT: nothing was stopping it. A
    # month of this and the medians are genuinely wrong and the
    # thin-stock filter starts passing names it should refuse. Slow
    # leaks are the ones that run for six months unnoticed.
    #
    # 08:45 is the right moment to catch it -- yesterday's bhavcopy is
    # certainly published, and this already runs before every session.
    _check_daily_history(auto_fill="--no-fetch" not in sys.argv)

    # ---- log hygiene ----
    log_dir = "logs"
    if os.path.isdir(log_dir):
        biggest = max((os.path.getsize(os.path.join(log_dir, f))
                       for f in os.listdir(log_dir)
                       if f.endswith(".log")), default=0)
        check("log files", OK if biggest < 100 * 1024 * 1024 else WARN,
              f"largest is {biggest / 1024 / 1024:,.0f} MB "
              f"(rotates at 25 MB from this session on)")

    return _summary()


def _summary():
    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    print("\n" + "=" * 72)
    if fails:
        print(f"  {len(fails)} PROBLEM(S). Fix these BEFORE starting:\n")
        for _, name, detail in fails:
            print(f"    - {name}: {detail}")
        print("\n  Do not start the bot until these are clear. A restart at")
        print("  09:20 costs the whole session.")
    else:
        print("  Ready. Start the bot BEFORE 09:15, then hands off.")
        if warns:
            print(f"\n  {len(warns)} warning(s) -- none blocking:")
            for _, name, detail in warns:
                print(f"    - {name}: {detail}")
        print("\n  ONE start. ZERO restarts. If something looks wrong")
        print("  between 09:15 and 15:30, write it down -- do not restart.")
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
