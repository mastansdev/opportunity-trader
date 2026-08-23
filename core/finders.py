"""Independent finders, one brain that chooses between them.

==========================================================
    "we will build all in different finders i.e = Opportunities from
     NEWS, RESULTS, EVENTS, structural moving stocks like all as a
     unique finders that report to trade brain engine which will sort
     the stocks & select best of best"
                                -- operator, 22 August 2026

    "as a human i'm doing all of them & time delayed = stock movement
     over & thats where the bot trading came into force"
==========================================================

That second line is the whole justification. He already makes these
judgements; the bot exists because he cannot make them across 1,300
names before the move is finished.

WHY THIS EXISTS RATHER THAN ONE BIGGER RANKER

The bot already had two lanes and three reason stores, and everything
funnelled into a single score. Measured on 22 August over 15 sessions,
that score ordered its own shortlist WORSE THAN RANDOM:

    highest volume x   +Rs 565/trade   62.2% up
    first to fire      -Rs  36         44.4%
    HIGHEST SCORE      -Rs  68         42.2%
    random draw        -Rs 226

A single invented number, averaging signals of different kinds with
weights nobody measured, cannot rank them. The fix is not a better
formula -- it is knowing WHERE each candidate came from, so each
source can be measured on what its own picks actually did.

Every candidate carries `finder`. That one field is what makes the
whole thing learnable: after N sessions the brain can back the finders
that have paid and starve the ones that have not, from evidence rather
than from a weight somebody typed.

THE BRAIN DOES NOT INVENT A SCORE

It orders by VOLUME AGAINST THE STOCK'S OWN NORMAL, because that is
money the exchange counted and it is the only ordering that measured
positive. Anything self-assigned breaks ties and never decides -- the
rule the operator set on 22 August:

    "these scores, grades were self assigned & neither stocks nor NSE
     works as per our scoring right?"

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import diagnostic, warn

# What a finder must fill in. `finder` and `symbol` are required; the
# rest are what the brain sorts and what the journal measures later.
FIELDS = ("symbol", "finder", "reason", "at", "volume_x", "price",
          "evidence")


def candidate(symbol, finder, reason=None, at=None, volume_x=None,
              price=None, **evidence):
    """One opportunity, from one finder, in the shape the brain reads."""
    return {
        "symbol": str(symbol or "").upper().strip(),
        "finder": str(finder or "").strip() or "unknown",
        "reason": str(reason).strip() if reason else None,
        "at": at,
        "volume_x": _num(volume_x),
        "price": _num(price),
        "evidence": {k: v for k, v in evidence.items() if v is not None},
    }


def _num(value):
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return None if got != got else got          # NaN -> None


class Finder:
    """A source of opportunities. Subclasses implement find().

    A finder answers ONE question well and says nothing about any
    other. It never places an order, never reads another finder's
    output, and never decides how many seats it deserves -- that is
    the brain's job, and keeping it there is what lets each finder be
    measured on its own record.
    """

    name = "finder"

    def find(self, now=None):
        """Candidates this finder is seeing right now. Never raises."""
        raise NotImplementedError

    def safe_find(self, now=None):
        """find(), with a broken finder unable to stop the others."""
        try:
            got = self.find(now=now) or []
        except Exception as exc:                            # noqa: BLE001
            warn(f"[FINDER] {self.name} failed ({type(exc).__name__}: "
                 f"{exc}). The others are unaffected.")
            return []
        out = []
        for row in got:
            if isinstance(row, dict) and row.get("symbol"):
                row.setdefault("finder", self.name)
                out.append(row)
        return out


def _describe(row):
    """One candidate as a line he can read on the log."""
    vol = row.get("volume_x")
    found = "+".join(row.get("finders") or [row.get("finder") or "?"])
    size = "no volume reading" if vol is None else f"{vol:.1f}x"
    return f"{row.get('symbol')}({found}, {size})"


class TradeBrain:
    """Collects from every finder and chooses which to back.

    ---- HOW IT CHOOSES, AND WHY IT IS NOT A SCORE ----

    By volume against the stock's own normal, highest first. That is
    the only ordering measured positive (+Rs 565/trade against -Rs 226
    for a random draw, and -Rs 823 for the same rule inverted -- a
    mirror that clean is signal, not a lucky cut).

    A candidate with no volume reading sorts LAST, never first. One the
    ranker could not measure is the least evidenced, not the most.

    ---- WHEN TWO FINDERS NAME THE SAME STOCK ----

    They agree, and that is worth something. The candidate is kept once,
    carrying every finder that named it, so `finders` can be measured
    later as its own signal. It does NOT get a bonus today -- nothing
    has measured what agreement is worth, and inventing a weight for it
    is the exact mistake this module exists to stop making.
    """

    def __init__(self, finders=None, seats=3):
        self.finders = list(finders or [])
        self.seats = int(seats)

    def gather(self, now=None):
        """Every candidate from every finder, deduped by symbol."""
        merged = {}
        for finder in self.finders:
            for row in finder.safe_find(now=now):
                sym = row["symbol"]
                have = merged.get(sym)
                if have is None:
                    row = dict(row)
                    row["finders"] = [row.get("finder")]
                    merged[sym] = row
                    continue
                # Two finders, one stock. Keep the richer reading and
                # remember that both named it.
                if row.get("finder") not in have["finders"]:
                    have["finders"].append(row.get("finder"))
                if have.get("volume_x") is None:
                    have["volume_x"] = row.get("volume_x")
                if not have.get("reason") and row.get("reason"):
                    have["reason"] = row.get("reason")
                    have["finder"] = row.get("finder")
                have.setdefault("evidence", {}).update(row.get("evidence") or {})
        return list(merged.values())

    @staticmethod
    def order(rows):
        """Best first. Volume decides; nothing self-assigned does."""
        return sorted(
            [r for r in (rows or []) if isinstance(r, dict)],
            key=lambda r: (-(r.get("volume_x") if r.get("volume_x")
                             is not None else -1.0),
                           str(r.get("symbol") or "")))

    def pick(self, now=None, seats=None):
        """The stocks to back, best first, at most `seats` of them."""
        rows = self.order(self.gather(now=now))
        take = self.seats if seats is None else int(seats)
        chosen = rows[:max(take, 0)]
        if chosen:
            diagnostic("[BRAIN] " + ", ".join(_describe(r) for r in chosen))
        return chosen

    def report(self, now=None):
        """What each finder contributed. For the journal, and for him."""
        rows = self.gather(now=now)
        counts = {}
        for r in rows:
            for f in (r.get("finders") or []):
                counts[f] = counts.get(f, 0) + 1
        return {"candidates": len(rows), "by_finder": counts,
                "picked": [r["symbol"] for r in self.order(rows)[:self.seats]]}
