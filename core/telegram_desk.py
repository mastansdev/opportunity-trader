"""
==========================================================
The Telegram desk -- alerts out, commands in
==========================================================

    "our bot needs telegram command center with alerting user about the
     opportunities & commands to buy,sell,exitall options & everything
     thats matter for user"      -- operator, 17 August 2026

He is at a desk job and the market is open while he is not watching a
browser. This is the bot on his phone.

WHY THE BOT API AND NOT TELETHON
--------------------------------
core/telegram_client.py already reads nine channels over Telethon,
authenticated as HIM. It stays exactly as it is and is not touched
here. Driving orders from that session would mean the credential that
reads his personal Telegram also places trades, and a single leak
would cost both.

A BotFather token is a separate, revocable credential that can be
locked to one chat id. If it leaks he revokes it and his account is
untouched.

IT IS A SECOND FRONT DOOR, NOT A SECOND ORDER PATH
--------------------------------------------------
Every command here ends at trading/trade_controller.py -- the same
object dashboard/server.py calls, the same request_buy /
request_exit / request_exit_all the BUY button uses. Nothing in this
file talks to Dhan, builds an order, or knows what an order looks
like. ALERT_ONLY_MODE, the daily loss cap, the entry gates and the
square-off guard all still apply, because the decision is still made
where it always was.

That matters: a chat app that reimplemented the order path would be a
second set of rules to keep in step, and they would drift.

THREE THINGS THAT COULD GO BADLY, AND WHAT STOPS THEM
-----------------------------------------------------
1. SOMEBODY ELSE FINDS THE BOT. Telegram bots are discoverable by
   handle. Every command is refused unless it comes from
   TELEGRAM_CHAT_ID -- and a refusal is REPORTED to him, so an
   attempt is visible rather than silent.

2. A FAT FINGER ON A PHONE. He chose a confirm step, so BUY, SELL and
   EXITALL are quoted back with what they will do and wait for YES.
   CONFIRM_SECONDS later the pending command expires by itself: a YES
   typed into a stale conversation must never fire an order.

3. THE DESK ITSELF FAILING. Every network call is wrapped and every
   handler returns a sentence rather than raising. A chat integration
   must not be able to stop the trading loop -- it is the least
   important thing in this process.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

from core.logger import decision, diagnostic, warn

API = "https://api.telegram.org/bot{token}/{method}"

# How long a quoted BUY / SELL / EXITALL waits for YES. Short on
# purpose: a confirmation is only meaningful while he still remembers
# what he asked for.
CONFIRM_SECONDS = 60

# getUpdates long-poll. Telegram holds the connection open until
# something arrives, so this is not a busy loop -- one request every
# 25 seconds when the market is quiet.
POLL_SECONDS = 25

# ---- THE PHONE IS NOT THE LOG. 18 August 2026. ----
#
# The Engine's alert notes ran 200-360 A DAY from 31 July to 12 August
# -- 311 on the 11th alone. That is the correct volume for a log file
# and it is an unusable volume for a phone: an alert he swipes away
# unread is worse than no alert, because he stops looking at the ones
# that matter.
#
# So this is a hard daily ceiling, not a preference. When it is hit he
# is told once that it was hit and where the rest are, which is the
# one thing a silent cap must never do -- go silent without saying so.
PUSH_MAX_PER_DAY = 25

# A sizing refusal ("the stop is 140 away, a single share risks more
# than the Rs 1,500 budget") is a REASON THE BOT DID NOTHING. It
# belongs on the board's refusal list, not on his phone -- he asked to
# be told what to buy, and a stream of near-misses buries that.
PUSH_SKIP_KINDS = ("stop-too-wide",)

_HELP = """*Opportunity Trader*

`STATUS`      bot on/off, positions, day P&L
`POSITIONS`   what is open, with stops
`PNL`         today, closed only
`TOP`         what the bot likes right now
`ALERTS`      every alert raised today
`FUNDS`       MTF buying power left
`WHY SYM`     which gate refused it, live
`OPP`         what each opportunity family is worth

`BUY SYM [qty]`   quoted, needs YES
`SELL SYM`        quoted, needs YES
`EXITALL`         quoted, needs YES

`ON` / `OFF`  arm or disarm new entries
`HELP`        this"""


def _token():
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _chat_id():
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip()


def available():
    """Both halves configured? Never raises, never logs the token."""
    return bool(_token() and _chat_id())


def _call(method, **params):
    """One Bot API call. Returns the result dict or None. Never raises.

    Never logs `params` -- a send carries his position sizes and a
    getUpdates reply carries whatever he typed.
    """
    token = _token()
    if not token:
        return None
    try:
        url = API.format(token=token, method=method)
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(url, data=data, timeout=POLL_SECONDS + 10) as r:
            got = json.loads(r.read())
        if not got.get("ok"):
            diagnostic(f"[TG] {method} refused: {got.get('description')}")
            return None
        return got.get("result")
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[TG] {method} failed: {type(exc).__name__}")
        return None


def send(text, chat_id=None):
    """Push a message to him. True if it went. Never raises."""
    target = chat_id or _chat_id()
    if not target or not text:
        return False
    return _call("sendMessage", chat_id=target, text=str(text)[:4000],
                 parse_mode="Markdown",
                 disable_web_page_preview="true") is not None


class TelegramDesk:
    """Alerts out, commands in. One per process.

    `controller` is trading/trade_controller.py's TradeController --
    the same instance the dashboard holds. `state` is the
    DashboardState, read for STATUS and POSITIONS so the phone and the
    screen can never disagree about what is open.
    """

    def __init__(self, controller=None, state=None, engine=None,
                 master_loader=None):
        self.controller = controller
        self.state = state
        self.engine = engine
        self.master_loader = master_loader
        self._offset = None
        self._pending = None          # (verb, symbol, qty, expires_at)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Daily push ceiling -- see PUSH_MAX_PER_DAY. Keyed by date so
        # a bot left running over midnight starts the new day at zero.
        self._push_day = None
        self._pushed = 0

    # ---------------- outbound ----------------

    def alert(self, text):
        """An unsolicited message -- an opportunity, a fill, a stop."""
        return send(text)

    def opportunity(self, symbol, why, price=None, plan=None):
        """The message he actually wants at 09:40.

        Everything here is already decided by the bot; this only
        formats it. No number is computed in this file.
        """
        bits = [f"*{symbol}*"]
        if price:
            bits.append(f"at {price}")
        text = " ".join(bits) + "\n" + (why or "")
        if plan and plan.get("ok"):
            text += (f"\n`qty {plan.get('qty')}  stop {plan.get('stop')}  "
                     f"target {plan.get('target')}`")
        text += f"\n\n`BUY {symbol}` to take it"
        return send(text)

    # ---- THE LAST MILE. 18 August 2026. ----
    #
    #     "why i didn't get any alerts to buy stocks in telegram ?
    #      i want to see the bot alerts me by stock name & reason to
    #      buy"
    #
    # The alerts were being MADE. core/engine.py._manual_alert has
    # written one for every pick since 31 July -- 2,652 of them -- and
    # each went to the log and the board and stopped there. Nothing
    # joined that funnel to this file, so a working sender and a
    # working alert never met.
    #
    # push() is that join, and it is deliberately the dumbest code in
    # this file: it decides WHETHER to send, and wraps an envelope
    # round what the Engine already wrote. It computes no price, no
    # quantity, no stop and no reason. The sentence on his phone is
    # the sentence on the board, character for character -- a second
    # copy that could drift from the first is exactly how a dashboard
    # and an alert end up disagreeing about the same trade.

    #: Header and the useful verb, per alert kind. An unrecognised
    #: kind is still SENT: a note the Engine thought worth writing is
    #: never dropped here merely because this table has not heard of
    #: it yet.
    HEADS = {
        "ranked-buy": ("OPPORTUNITY", "BUY"),
        "TRAIL": ("YOUR POSITION", "SELL"),
        "HELD": ("YOUR POSITION", "SELL"),
        "NEWS": ("NEWS ON A HOLDING", "SELL"),
    }

    def push(self, note):
        """Forward one Engine alert note to his phone. Never raises.

        `note` is the dict the Engine already built and already
        showed: {"symbol", "kind", "message", "at"}.
        """
        try:
            if not isinstance(note, dict):
                return False
            kind = str(note.get("kind") or "")
            symbol = str(note.get("symbol") or "").upper()
            message = str(note.get("message") or "").strip()
            if not message or kind in PUSH_SKIP_KINDS:
                return False
            if not available():
                return False
            if not self._budget_allows():
                return False
            return bool(send(self._card(symbol, kind, message)))
        except Exception as exc:                            # noqa: BLE001
            diagnostic(f"[TG] push failed: {type(exc).__name__}")
            return False

    def _card(self, symbol, kind, message):
        """The envelope. What is inside it is untouched."""
        head, verb = self.HEADS.get(kind, (None, None))
        if head is None:
            head = ("OPPORTUNITY" if kind.startswith("alert-only")
                    else "ALERT")
            verb = "BUY" if head == "OPPORTUNITY" else "SELL"
        card = f"*{head} -- {symbol}*\n{message}"
        if symbol and symbol != "?":
            card += f"\n\n`{verb} {symbol}`   _(then_ `YES`_)_"
        return card

    def _budget_allows(self):
        """One counter, reset by date. It says so once when it stops.

        A cap that goes quiet without announcing itself is the same
        failure as no alert at all, dressed as a working one.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._push_day != today:
                self._push_day = today
                self._pushed = 0
            self._pushed += 1
            n = self._pushed
        if n <= PUSH_MAX_PER_DAY:
            return True
        if n == PUSH_MAX_PER_DAY + 1:
            # Outside the lock deliberately -- send() is a network call.
            send(f"_That is {PUSH_MAX_PER_DAY} alerts today, the daily "
                 f"cap. Anything further is on the board and in the "
                 f"log -- nothing is hidden from the bot itself._")
        return False

    # ---------------- inbound ----------------

    def _authorised(self, chat_id):
        """One chat, and a refusal he can see.

        A Telegram bot is discoverable by handle, so a stranger CAN
        message it. Silently ignoring them would hide that; he is told
        instead, once per sender, and they get nothing back.
        """
        allowed = _chat_id()
        if str(chat_id) == str(allowed):
            return True
        warn(f"[TG] Command from an unauthorised chat ({chat_id}) -- "
             f"ignored. Only {allowed} may command this bot.")
        return False

    def handle(self, text, chat_id):
        """One message in, one reply out. NEVER raises.

        Returns the reply string so this is testable without a network.
        """
        try:
            if not self._authorised(chat_id):
                return None
            words = (text or "").strip().split()
            if not words:
                return None
            verb = words[0].upper().lstrip("/")
            arg = words[1].upper() if len(words) > 1 else ""
            qty = words[2] if len(words) > 2 else None

            if verb in ("YES", "Y", "CONFIRM"):
                return self._confirm()
            if verb in ("NO", "N", "CANCEL"):
                with self._lock:
                    self._pending = None
                return "Cancelled."
            if verb in ("HELP", "START", "?"):
                return _HELP
            if verb == "STATUS":
                return self._status()
            if verb in ("POSITIONS", "POS"):
                return self._positions()
            if verb in ("TOP", "PICKS"):
                return self._top()
            if verb in ("ALERTS", "ALERT"):
                return self._alerts()
            if verb in ("FUNDS", "MARGIN", "CAPITAL"):
                return self._funds()
            if verb == "PNL":
                return self._pnl()
            if verb == "WHY":
                return self._why(arg)
            # _HELP has advertised OPP since this file was written and
            # handle() has never had a branch for it -- so it answered
            # "Unknown command `OPP`" to a command its own help text
            # told him to send. Found 18 Aug while wiring push().
            if verb in ("OPP", "OPPORTUNITY"):
                return self._opportunities()
            if verb in ("ON", "OFF"):
                return self._arm(verb == "ON")
            if verb in ("BUY", "SELL", "EXITALL"):
                return self._quote(verb, arg, qty)
            return f"Unknown command `{verb}`. Send `HELP`."
        except Exception as exc:                            # noqa: BLE001
            warn(f"[TG] handler failed: {type(exc).__name__}: {exc}")
            return "That failed on my side. Nothing was sent."

    # ---------------- the confirm step ----------------

    def _ltp(self, symbol):
        """Last price for a symbol, from the board's own snapshot.

        No price is computed here and no feed is read -- this only
        finds the number the board is already showing.
        """
        snap = self._snapshot()
        pools = [(snap.get("ranked") or {}).get("rows") or [],
                 snap.get("movers") or [],
                 (snap.get("shortlist") or {}).get("rows") or []]
        for pool in pools:
            for row in pool:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").upper() != symbol:
                    continue
                for key in ("ltp", "price", "cmp", "last_price"):
                    try:
                        got = float(row.get(key))
                    except (TypeError, ValueError):
                        continue
                    if got > 0:
                        return got
        held = (snap.get("open_positions") or {}).get(symbol) or {}
        for key in ("ltp", "current_price", "entry_price"):
            try:
                got = float(held.get(key))
            except (TypeError, ValueError):
                continue
            if got > 0:
                return got
        return None

    def _mtf_check(self, symbol):
        """Can he buy this ON MARGIN at Dhan? (verdict, sentence).

        ==========================================================
            "BY SEEING THAT ALERT I'LL GIVE COMMAND BUY X SHARES IN
             MTF (INCASE NON-MTF - NO BUY)"
                                -- operator, 18 August 2026
        ==========================================================

        THREE ANSWERS, NOT TWO. True, False, and None for "could not
        be asked" -- paper mode, no margin book, no live price yet.
        None is NOT eligibility: it is reported in the quote in those
        words, so he decides with the gap visible. The standing rule
        on this project is NEVER ASSUME, and an unasked question read
        as a pass is precisely that.

        The question is asked by dashboard/state.py's resolver, which
        asks core/mtf_margin.py, which asks DHAN. Nothing here keeps a
        list of MTF scrips: a second copy would go stale the first
        time Dhan changed the list, and it would go stale silently.
        """
        resolver = (getattr(self.state, "mtf_for", None)
                    or getattr(self.state, "_mtf_for", None))
        if resolver is None:
            return None, "MTF not checked (no board attached)"
        price = self._ltp(symbol)
        if not price:
            return None, "MTF not checked (no live price on the board yet)"
        try:
            got = resolver(symbol, {"ltp": price})
        except Exception as exc:                            # noqa: BLE001
            diagnostic(f"[TG] MTF check failed: {type(exc).__name__}")
            return None, "MTF not checked (the margin call failed)"
        if got is None:
            return None, "MTF not checked (broker not connected)"
        if not got.get("eligible"):
            return False, "Dhan does not margin this scrip -- cash only"
        lev = got.get("leverage")
        return True, (f"MTF {lev}x" if lev else "MTF eligible")

    def _quote(self, verb, symbol, qty):
        """Say what will happen and wait. Places nothing."""
        if verb != "EXITALL" and not symbol:
            return f"`{verb} SYMBOL` -- which stock?"
        mtf_note = ""
        if verb == "BUY" and symbol and self.master_loader is not None:
            try:
                known = set(self.master_loader.all_symbols())
                if symbol not in known:
                    return (f"*{symbol}* is not in the tradeable universe. "
                            f"Nothing sent.")
            except Exception:                               # noqa: BLE001
                pass
        if verb == "BUY" and symbol:
            # HIS RULE, ENFORCED BEFORE THE QUOTE IS OFFERED. Refusing
            # here rather than at the confirm step means a cash-only
            # name never gets a YES to type against it.
            allowed, note = self._mtf_check(symbol)
            if allowed is False:
                return (f"*{symbol}* -- NO BUY.\n{note}.\n\n"
                        f"_Your rule, 18 Aug: if it is not MTF, it is "
                        f"not bought._")
            mtf_note = f"\n_{note}._"
        want = None
        if qty:
            try:
                want = int(str(qty).strip())
            except ValueError:
                return f"`{qty}` is not a quantity."

        with self._lock:
            self._pending = (verb, symbol, want,
                             time.time() + CONFIRM_SECONDS)

        note = self._reach()
        if verb == "EXITALL":
            return (f"*EXIT EVERYTHING*\nClose every open position at "
                    f"market.{note}\n\nReply `YES` within "
                    f"{CONFIRM_SECONDS}s.")
        size = f" x{want}" if want else " (bot default size)"
        return (f"*{verb} {symbol}*{size}{mtf_note}{note}\n\nReply `YES` "
                f"within {CONFIRM_SECONDS}s.")

    @staticmethod
    def _reach():
        """Does a confirmed command actually reach Dhan? Say so exactly.

        ---- THE FIRST VERSION OF THIS LINE WAS WRONG. 17 Aug 2026 ----

        It read config.ALERT_ONLY_MODE and told him "ALERT ONLY is ON
        -- this will be recorded, not sent to Dhan". That is not what
        ALERT_ONLY_MODE does, and a confirmation prompt that is wrong
        about safety is worse than no prompt at all.

        ALERT_ONLY_MODE governs THE BOT'S OWN entries. It is checked in
        core/engine.py's breakout path and NOT in the manual path -- a
        BUY he asks for goes through whether the bot is armed or not,
        deliberately, because it is his trade and not the bot's. The
        dashboard BUY button has always behaved this way.

        What decides whether an order reaches Dhan is TRADING_MODE,
        read by trading/execution.py: LIVE wires LiveExecution,
        anything else wires PaperExecution. So with TRADING_MODE=LIVE
        and ALERT_ONLY_MODE=True the old message would have said "not
        sent to Dhan" WHILE PLACING A REAL ORDER.

        Read at call time, never cached: he can edit .env between
        sessions and a stale answer here is the same bug again.
        """
        try:
            from config import TRADING_MODE
            live = str(TRADING_MODE).upper() == "LIVE"
        except Exception:                                   # noqa: BLE001
            return ("\n_Could not read TRADING_MODE -- assume this is "
                    "REAL until you have checked._")
        if live:
            return ("\n*LIVE -- this places a REAL order at Dhan.*"
                    "\n_A market order cannot be cancelled once it fills._")
        return ("\n_PAPER mode -- this is recorded and does not reach "
                "Dhan._")

    def _confirm(self):
        """Fire the pending command, if it has not expired."""
        with self._lock:
            pending = self._pending
            self._pending = None
        if not pending:
            return "Nothing to confirm."
        verb, symbol, qty, expires = pending
        if time.time() > expires:
            # A YES typed into a stale conversation must never trade.
            return (f"That `{verb}` expired after {CONFIRM_SECONDS}s. "
                    f"Send it again.")
        if self.controller is None:
            return "No trade controller wired. Nothing sent."

        # THE SAME METHODS THE DASHBOARD BUTTON CALLS. Nothing here
        # builds an order or talks to Dhan.
        if verb == "BUY":
            self.controller.request_buy(symbol, qty=qty)
            self.controller.note_action(True, f"BUY {symbol} -- telegram")
            return f"BUY *{symbol}* requested."
        if verb == "SELL":
            self.controller.request_exit(symbol, qty=qty)
            self.controller.note_action(True, f"SELL {symbol} -- telegram")
            return f"SELL *{symbol}* requested."
        self.controller.request_exit_all()
        self.controller.note_action(True, "EXIT ALL -- telegram")
        return "EXIT ALL requested."

    # ---------------- read-only answers ----------------

    def _snapshot(self):
        try:
            return self.state.get_snapshot() or {}
        except Exception:                                   # noqa: BLE001
            return {}

    def _status(self):
        snap = self._snapshot()
        bot = snap.get("bot_trading") or {}
        on = bot.get("on")
        held = snap.get("open_positions") or {}
        closed = snap.get("closed_positions") or []
        net = sum(float(c.get("pnl") or 0) for c in closed)
        return (f"*{'BOT TRADING' if on else 'BOT OBSERVING'}*\n"
                f"open: {len(held)}   closed today: {len(closed)}\n"
                f"day P&L: Rs {net:,.0f}\n"
                f"as of {snap.get('as_of') or '?'}")

    def _positions(self):
        snap = self._snapshot()
        held = snap.get("open_positions") or {}
        if not held:
            return "Nothing open."
        lines = ["*Open*"]
        for sym, p in list(held.items())[:20]:
            lines.append(f"`{sym:<12} {p.get('qty','?')} @ "
                         f"{p.get('entry_price','?')}  stop "
                         f"{p.get('stop','-')}`")
        return "\n".join(lines)

    def _pnl(self):
        snap = self._snapshot()
        closed = snap.get("closed_positions") or []
        if not closed:
            return "Nothing closed today."
        net = sum(float(c.get("pnl") or 0) for c in closed)
        won = sum(1 for c in closed if float(c.get("pnl") or 0) > 0)
        lines = [f"*Rs {net:,.0f}*  ({len(closed)} trades, {won} won)"]
        for c in closed[:12]:
            lines.append(f"`{str(c.get('symbol'))[:12]:<12} "
                         f"{float(c.get('pnl') or 0):>9,.0f}  "
                         f"{str(c.get('exit_reason') or '')[:16]}`")
        return "\n".join(lines)

    def _top(self):
        """What the bot likes RIGHT NOW, ranked.

        An alert only fires the moment a pick appears. This is the
        same list on demand, so he is not limited to whatever arrived
        while he happened to be looking at his phone.
        """
        rows = ((self._snapshot().get("ranked") or {}).get("rows") or [])
        if not rows:
            return "Nothing on the board -- no pick has passed the gates."
        lines = ["*What the bot likes now*"]
        for row in rows[:8]:
            why = str(row.get("why") or row.get("mechanism") or "")[:90]
            lines.append(f"`{str(row.get('symbol'))[:12]:<12} "
                         f"{row.get('ltp', '?')}`\n{why}")
        return "\n".join(lines)

    def _alerts(self):
        """Every alert raised today, newest first.

        Including the ones the daily push cap held back -- the cap
        limits what is PUSHED, never what he can ask for.
        """
        rows = self._snapshot().get("alerts") or []
        if not rows:
            return "No alerts raised today."
        lines = [f"*{len(rows)} alerts today*"]
        for row in rows[:15]:
            if not isinstance(row, dict):
                continue
            lines.append(f"`{row.get('at', '')}` "
                         f"*{row.get('symbol', '?')}*  "
                         f"{str(row.get('message') or '')[:110]}")
        return "\n".join(lines)

    def _funds(self):
        """What is left to deploy, and how much is already at work.

            "bot must self learn & evaluate the funds usage based on
             stock underlying strength"    -- operator, 18 August 2026

        The evaluating is not done here and is not done yet. This
        reports what trading/portfolio.py already computes, so the
        number he plans against is the number the sizing uses.
        """
        cap = self._snapshot().get("capital") or {}
        if not cap:
            return "Capital not readable -- the broker may not be connected."

        def _rs(key):
            try:
                return f"Rs {float(cap.get(key)):,.0f}"
            except (TypeError, ValueError):
                return "?"

        return (f"*Funds*\n"
                f"`buying power   {_rs('available_buying_power'):>14}`\n"
                f"`deployed       {_rs('deployed_capital'):>14}`\n"
                f"`margin used    {_rs('used_margin'):>14}`\n"
                f"`realised today {_rs('realized_pnl'):>14}`")

    def _why(self, symbol):
        """Which gate refused it -- the same answer /api/why gives."""
        if not symbol:
            return "`WHY SYMBOL` -- which stock?"
        snap = self._snapshot()
        ranked = snap.get("ranked") or {}
        row = next((r for r in (ranked.get("rows") or [])
                    if str(r.get("symbol", "")).upper() == symbol), None)
        if row:
            return (f"*{symbol}* is on the board.\n"
                    f"{row.get('mechanism') or ''}")
        refused = next((r for r in (ranked.get("refused_rows") or [])
                        if str(r.get("symbol", "")).upper() == symbol), None)
        if refused:
            why = (refused.get("blocked_reason")
                   or (refused.get("blocking") or [None])[0]
                   or "refused, reason not recorded")
            return f"*{symbol}* refused:\n{why}"
        return (f"*{symbol}* did not reach the ranker today -- it did not "
                f"move enough to be looked at, or no tick arrived.")

    def _opportunities(self):
        """What each opportunity family has actually been worth.

        core/opportunity.py measured it against trade_memory and the
        price history; this only carries the answer. Nothing is
        recomputed and no family is ranked here.
        """
        try:
            from core import opportunity
            return f"*Opportunity families*{chr(10)}{opportunity.verdict()}"
        except Exception as exc:                            # noqa: BLE001
            return f"Could not read the opportunity memory ({exc})."

    def _arm(self, on):
        if self.engine is None:
            return "No engine wired."
        try:
            self.engine.alert_only = not on
            state = "TRADING" if on else "OBSERVING"
            decision(f"[TG] Bot set to {state} from Telegram.")
            return f"Bot is now *{state}*."
        except Exception as exc:                            # noqa: BLE001
            return f"Could not change it: {exc}"

    # ---------------- the poll loop ----------------

    def poll_once(self):
        """One getUpdates round. Returns how many messages it handled."""
        params = {"timeout": POLL_SECONDS}
        if self._offset is not None:
            params["offset"] = self._offset
        updates = _call("getUpdates", **params)
        if not updates:
            return 0
        done = 0
        for update in updates:
            self._offset = update.get("update_id", 0) + 1
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue
            chat = (message.get("chat") or {}).get("id")
            reply = self.handle(message.get("text"), chat)
            if reply:
                send(reply, chat_id=chat)
                done += 1
        return done

    def start(self):
        """Run the poll loop on a daemon thread. Safe to call twice."""
        if not available():
            diagnostic("[TG] Not configured -- no desk. Set "
                       "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
            return False
        if self._thread is not None and self._thread.is_alive():
            return True

        def _run():
            decision("[TG] Telegram desk is up. Send HELP to it.")
            while not self._stop.is_set():
                try:
                    self.poll_once()
                except Exception as exc:                    # noqa: BLE001
                    warn(f"[TG] poll failed: {type(exc).__name__}")
                    self._stop.wait(10)

        self._thread = threading.Thread(target=_run, name="telegram-desk",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
