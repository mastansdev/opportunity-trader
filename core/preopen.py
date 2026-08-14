"""
==========================================================
The pre-open session -- 09:00 to 09:08, previously invisible
==========================================================

    "the bot is completely blind 09:00-09:15"
                                    -- established 29 July 2026

Item 16 on the operator's own Daily Market Preparation chart is
"PRE-MARKET SESSION 9:00 AM -- Gap %, Volume, Top Gainers/Losers,
Block Trades, Auction Volume". The bot collected none of it.

WHAT NSE ACTUALLY RUNS
----------------------
09:00-09:08  orders collected, no matching
09:08-09:12  matching, and the IEP is fixed
09:15        normal trading opens AT that price

The IEP -- Indicative Equilibrium Price -- is where the stock will
open. It is published before the bell. So at 09:12 the opening gap for
every stock is a known fact, not a forecast.

WHAT THIS COLLECTS
------------------
    IEP              the price it will open at
    gap %            IEP against yesterday's close -- NSE's own pChange
    pre-open volume  how much actually matched
    buy vs sell qty  unmatched orders left on each side

That last pair is the one nobody looks at. A stock opening +4% on 2,000
matched shares with almost no orders behind it is a different animal
from one opening +4% on 400,000 shares with heavy unfilled buying. Both
show "+4%" everywhere else.

WHAT IT DOES NOT DO
-------------------
It does not rank, score, recommend or trade. It reports what NSE
published. Whether a gap is worth trading is a separate question that
needs evidence this bot does not have yet.

NEVER RAISES. A stock NSE does not return is MISSING, never guessed --
same rule as core/premarket.py and core/nse_quotes.py.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import threading
from datetime import datetime

from core.logger import decision, diagnostic, warn

STORE_PATH = os.path.join("data", "preopen.json")

# NSE's own pre-open endpoint. key=ALL returns every stock in the
# session; the same page the operator's chart calls "Pre-Market
# Session". Needs the cookie handshake in core/nse_quotes.py.
PREOPEN_URL = ("https://www.nseindia.com/api/market-data-pre-open?key=ALL")


def _num(value):
    """A float, or None. Zero counts as real for quantities but not for
    prices -- a zero price means 'not set', a zero quantity means
    'nothing there', and those are different facts."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_preopen_payload(payload):
    """NSE's pre-open JSON -> {SYMBOL: row}. Never raises.

    NSE nests this two levels deep and repeats some fields in both
    halves. The names below are NSE's own, kept visible so anyone can
    check them against the site:

        metadata.symbol            the stock
        metadata.previousClose     yesterday's close
        detail.preOpenMarket.IEP   where it will open
        metadata.pChange           NSE's OWN gap %
        ...finalQuantity           matched quantity
        ...totalBuyQuantity        unmatched buy orders left
        ...totalSellQuantity       unmatched sell orders left

    pChange is read, never recomputed -- the operator's standing rule
    is that percentages follow NSE rather than our arithmetic.
    """
    out = {}
    try:
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        for entry in (payload or {}).get("data") or []:
            meta = entry.get("metadata") or {}
            symbol = (meta.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            book = ((entry.get("detail") or {})
                    .get("preOpenMarket") or {})

            iep = _num(book.get("IEP")) or _num(meta.get("lastPrice"))
            if not iep or iep <= 0:
                # No equilibrium price means this stock did not trade in
                # the pre-open at all. That is a real, useful fact --
                # recorded as MISSING, never as zero.
                continue

            buy_qty = _num(book.get("totalBuyQuantity"))
            sell_qty = _num(book.get("totalSellQuantity"))
            imbalance = None
            if buy_qty is not None and sell_qty is not None \
                    and (buy_qty + sell_qty) > 0:
                # -1.0 = all unmatched orders are sells, +1.0 = all buys.
                imbalance = round(
                    (buy_qty - sell_qty) / (buy_qty + sell_qty), 3)

            out[symbol] = {
                "symbol": symbol,
                "iep": iep,
                "prev_close": _num(meta.get("previousClose")),
                "gap_pct": _num(meta.get("pChange")),
                "matched_qty": _num(book.get("finalQuantity")),
                "turnover": _num(book.get("totalTurnover")),
                "buy_qty": buy_qty,
                "sell_qty": sell_qty,
                "imbalance": imbalance,
                "updated": book.get("lastUpdateTime"),
            }
    except Exception:                                      # noqa: BLE001
        return out
    return out


class PreOpen:
    """What NSE published between 09:00 and 09:12, kept for the day."""

    def __init__(self, fetcher=None, store_path=STORE_PATH):
        self._fetcher = fetcher
        self.store_path = store_path
        self._lock = threading.Lock()
        self._mtime = None
        self._data = self._load()

    # ------------------------------------------------------------

    def _stamp(self):
        """A cheap fingerprint of the file on disk.

        (mtime_ns, size), NOT getmtime(). getmtime() returns float
        SECONDS, so a file rewritten inside one timestamp tick looks
        unchanged and the reload silently does not happen. The test suite
        caught exactly that -- the reload test passed alone and failed in
        the full run, because the full run wrote both versions of the
        file within the same second.

        That is not a test artifact. tools/preopen_gaps.py finishing in
        the same tick that the session started would have hit it in
        production, on the one morning of the year it mattered.
        """
        try:
            st = os.stat(self.store_path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _load(self):
        self._mtime = self._stamp()
        try:
            with open(self.store_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _maybe_reload(self):
        """Re-read the file if something else has written it since.

        WHY THIS HAS TO EXIST -- a contradiction that made this panel
        impossible to populate, found live on 30 July 2026.

        main.py builds this as PreOpen(fetcher=None), commented "reads
        what the 09:12 run stored". But main.py must be RUNNING before
        the 09:15 open, and NSE's pre-open book does not exist until
        09:12. _load() ran once in __init__, so a session started at
        08:59 held an empty file and served it all day. The operator ran
        tools/preopen_gaps.py at 09:09, it collected 2,007 stocks
        correctly, wrote data/preopen.json -- and the dashboard still
        showed nothing, because the object in memory had already decided.

        There was no sequence that worked. Start main.py late and you
        miss the open; start it on time and you never see the book.

        So the file is now the source of truth and this checks its
        mtime on every read. The 09:12 tool run reaches the screen
        within one dashboard refresh. Cheap: one stat() per refresh,
        and only re-parses when the timestamp actually moved.
        """
        stamp = self._stamp()
        if stamp is None or stamp == self._mtime:
            return
        fresh = self._load()
        if fresh:
            self._data = fresh
            decision(f"[PREOPEN] Re-read {self.store_path} -- "
                     f"{len(fresh.get('stocks') or {})} stocks, "
                     f"collected {fresh.get('collected_at') or '?'}.")

    def _save(self, data):
        """Write the book to disk, and SAY SO if it could not be written.

        This was `except OSError: pass` -- the highest-consequence silent
        write in the project. NSE's pre-open book exists for twelve
        minutes a day and cannot be re-fetched afterwards. A full disk, a
        locked file or a bad path lost it for the whole day and printed
        nothing at all: the collection log said "2,007 stocks read", so
        every line on screen claimed success.

        It matters more since the mtime reload landed, because the FILE is
        now the source of truth the dashboard reads. A failed save is no
        longer just a lost archive, it is a blank panel with a healthy
        log above it -- which is precisely the shape of the Telegram bug
        that hid 80 discarded messages a poll for months.
        """
        try:
            directory = os.path.dirname(self.store_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
        except OSError as exc:
            warn(f"[PREOPEN] COULD NOT SAVE {self.store_path}: {exc}. The "
                 f"pre-open book was collected but is NOT stored -- it "
                 f"cannot be re-fetched after 09:12, so today's book is "
                 f"lost unless this is fixed now.")
            return False
        self._archive(data)
        return True

    def _archive(self, data):
        """Keep a dated copy, so the book can be SCORED later.

        ---- WHY THIS DID NOT EXIST, AND SHOULD HAVE. 3 August 2026. ----

            "MUTHOOTFIN gapped -7.81% with 2.7x more buyers queued -
             fell like hell too"        -- operator

        He was checking a claim I had made about the order-book
        imbalance. I could not check it back, because this file is
        OVERWRITTEN every morning: one day exists at a time, and every
        previous pre-open book in the project's life has been deleted by
        the next one.

        So an interpretation was put in front of him -- buyers queued
        under a gap down reads as support -- that had never been tested
        against a single outcome and could not be. The same mistake as
        the two news readers before the tape settled MDR: a direction
        asserted with nothing scoring it.

        A dated copy costs about 600KB a day. Twenty sessions is enough
        to ask whether a queue predicts anything at all, and the answer
        may well be no -- NSE publishes the WHOLE book including limit
        orders far from the indicative price, so bargain bids stacked
        under a falling stock inflate buy_qty without anyone paying up.

        Never raises. A failed archive must not endanger the live save,
        which has already happened by the time this runs.
        """
        try:
            day = str(data.get("date") or "").strip() \
                or datetime.now().strftime("%Y-%m-%d")
            folder = os.path.join(os.path.dirname(self.store_path) or ".",
                                  "preopen_history")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{day}.json")
            if os.path.exists(path):
                return False          # already kept today's
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            diagnostic(f"[PREOPEN] Archived {day} for later scoring.")
            return True
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[PREOPEN] Could not archive: {exc}")
            return False

    # ------------------------------------------------------------

    def refresh(self):
        """Read the pre-open book. Returns how many stocks were
        collected. Never raises.

        A failed read keeps whatever was already held rather than
        blanking it -- the pre-open only happens once, and losing it to
        one bad request would mean losing it for the day.
        """
        if self._fetcher is None:
            warn("[PREOPEN] No fetcher wired -- nothing collected.")
            return 0
        try:
            rows = parse_preopen_payload(self._fetcher(PREOPEN_URL))
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[PREOPEN] Fetch failed ({exc}).")
            rows = {}

        if not rows:
            warn("[PREOPEN] Nothing collected. Keeping whatever was "
                 "already held -- the pre-open happens only once.")
            return 0

        with self._lock:
            self._data = {
                "stocks": rows,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "collected_at": datetime.now().strftime("%H:%M:%S"),
            }
        self._save(self._data)
        decision(f"[PREOPEN] {len(rows)} stocks read from NSE's pre-open "
                 f"session -- opening prices are known before the bell.")
        return len(rows)

    # ------------------------------------------------------------

    def get(self, symbol):
        with self._lock:
            stocks = (self._data.get("stocks") or {})
        return stocks.get((symbol or "").strip().upper())

    def gaps(self, symbols=None, minimum_pct=0.0, top=None):
        """Stocks in the pre-open book, biggest gap first.

        `symbols` restricts the answer to the bot's own universe --
        NSE's pre-open covers roughly 2,000 names and most of them are
        not tradeable here.

        Returns (up, down, unknown).

        ---- NOTHING IS THROWN AWAY ANY MORE. 1 August 2026. ----

            "Incase the stock is not in our universe last day & bot
             cannot calculate the gap% ... keep the all details as it
             is & print GAP% from dhan or NSE run (if possible) or
             keep - but never throw away any symbol that gets in
             either direction."

        Three defaults were each quietly discarding rows:

            minimum_pct=1.0   a stock opening +0.8% on 40x the normal
                              pre-open volume never appeared
            top=25            the 26th biggest gap of the day did not
                              exist as far as the panel was concerned
            gap is None       dropped entirely -- and NSE omits
                              pChange exactly when it is most
                              interesting, on a stock with no prior
                              close, which is to say a fresh listing

        So the floor is now zero, there is no cap unless one is asked
        for, and a row whose gap NSE did not publish comes back in its
        own `unknown` list with every other field intact. The panel
        prints "-" in the gap column for those and shows the IEP, the
        matched quantity and the book imbalance as normal -- all of
        which are real, published numbers that do not depend on
        yesterday's close existing.
        """
        with self._lock:
            stocks = dict(self._data.get("stocks") or {})
        wanted = None
        if symbols is not None:
            wanted = {s.strip().upper() for s in symbols}

        up, down, unknown = [], [], []
        for symbol, row in stocks.items():
            if wanted is not None and symbol not in wanted:
                continue
            gap = row.get("gap_pct")
            if gap is None:
                unknown.append(row)
            elif gap >= minimum_pct and gap > 0:
                up.append(row)
            elif gap <= -minimum_pct and gap < 0:
                down.append(row)
            else:
                # Exactly flat. Real, and it belongs with the ones
                # whose direction is not a gap either.
                unknown.append(row)

        up.sort(key=lambda r: -r["gap_pct"])
        down.sort(key=lambda r: r["gap_pct"])
        # Biggest book first, so a flat stock with real interest behind
        # it sits above a flat stock nobody wants.
        unknown.sort(key=lambda r: -(r.get("matched_qty") or 0))
        if top:
            return up[:top], down[:top], unknown[:top]
        return up, down, unknown

    def snapshot(self, symbols=None):
        """What the dashboard renders.

        Checks the file first -- see _maybe_reload() for the sequencing
        contradiction that made this necessary.
        """
        with self._lock:
            self._maybe_reload()
            data = dict(self._data)
        up, down, unknown = self.gaps(symbols=symbols)
        return {
            "available": bool(data.get("stocks")),
            "date": data.get("date"),
            "collected_at": data.get("collected_at"),
            "count": len(data.get("stocks") or {}),
            "gap_up": up,
            "gap_down": down,
            # Flat, or a gap NSE did not publish. Sent so the panel can
            # show them; never silently dropped.
            "gap_unknown": unknown,
            "shown": len(up) + len(down) + len(unknown),
        }
