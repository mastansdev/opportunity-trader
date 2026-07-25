"""
==========================================================
Opportunity Trader -- Standalone 24/7 News Dashboard
==========================================================

An always-on web view of the news store -- its OWN page, on its
OWN port, in its OWN process. Unlike the trading dashboard (which
lives inside main.py and only runs during market hours), this one
runs day or night, so you can watch the 24/7 news engine and the
per-stock "brain" any time.

It is READ-ONLY: it only ever reads the shared store
(news_bot/news_store.py). It never trades, never writes, never
touches the broker. Point it at the same store the news engine
writes to (local SQLite by default, or Railway Postgres via
DATABASE_URL) and it just shows what's there.

Run:
    python news_dashboard.py
Then open  http://127.0.0.1:8050  (port = config.NEWS_DASHBOARD_PORT).

Pages / API:
    GET /                      the HTML page
    GET /api/news              header stats + HIGH board + recent feed
    GET /api/stock/{symbol}    that stock's full stored news history

Author : H&M Opportunity Trader
==========================================================
"""

import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from news_bot.config import (
    NEWS_ACTIONABLE_WINDOW_HOURS,
    NEWS_DASHBOARD_HOST,
    NEWS_DASHBOARD_PORT,
    NEWS_DASHBOARD_REFRESH_SECONDS,
)
from news_bot.news_store import default_store, resolve_database_url


def _feed_row(rec):
    """Trim a stored row down to what the page needs, and mark whether
    it's a HIGH item (the only tier that can gate a trade)."""
    return {
        "symbol": rec.get("symbol"),
        "priority": rec.get("priority"),
        "direction": rec.get("direction"),
        "confidence": rec.get("confidence"),
        "materiality": rec.get("materiality"),
        "reason": rec.get("reason"),
        "title": rec.get("title"),
        "link": rec.get("link"),
        "source": rec.get("source"),
        "classifier": rec.get("classifier", "haiku"),
        "time": rec.get("time"),
    }


def build_app(store=None, window_hours=None):
    """Pure construction (no server) so tests can drive it with
    FastAPI's TestClient against a temp store."""
    store = store or default_store()
    window = window_hours if window_hours is not None else NEWS_ACTIONABLE_WINDOW_HOURS

    app = FastAPI(title="Opportunity Trader -- News Intelligence")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(_PAGE_HTML, headers={"Cache-Control": "no-store"})

    @app.get("/api/news")
    def api_news():
        stats = store.stats(window_hours=window)
        high_board = [
            _feed_row(item)
            for item in sorted(
                store.all_high_symbols(window_hours=window).values(),
                key=lambda r: r.get("time", ""),
                reverse=True,
            )
        ]
        feed = [_feed_row(r) for r in store.recent(window_hours=window)]
        return JSONResponse({
            "stats": stats,
            "window_hours": window,
            "high_board": high_board,
            "feed": feed,
        })

    @app.get("/api/stock/{symbol}")
    def api_stock(symbol: str):
        symbol = symbol.strip().upper()
        history = [_feed_row(r) for r in store.for_symbol(symbol, limit=200)]
        return JSONResponse({"symbol": symbol, "count": len(history),
                             "history": history})

    return app


def run():
    import uvicorn
    from core.logger import decision

    url = resolve_database_url()
    safe_url = url.split("@")[-1] if "@" in url else url
    store = default_store()
    decision(
        f"[NEWS_DASHBOARD] Reading store: {safe_url} "
        f"({store.count()} rows). Open http://{NEWS_DASHBOARD_HOST}:"
        f"{NEWS_DASHBOARD_PORT}"
    )
    app = build_app(store)
    uvicorn.run(
        app, host=NEWS_DASHBOARD_HOST, port=NEWS_DASHBOARD_PORT,
        log_level="warning",
    )


# ==============================================================
# The page -- one self-contained file (HTML + CSS + JS, no CDN).
# {{REFRESH_MS}} is filled once at import time below.
# ==============================================================

_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>News Intelligence -- Opportunity Trader</title>
<style>
  :root{
    --bg:#0b0e14; --panel:#141a24; --panel2:#1b2330; --border:#26303f;
    --text:#e6edf3; --dim:#8b98a9; --green:#3fb950; --red:#f85149;
    --amber:#d29922; --blue:#4b9fff; --hi:#f85149;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    font-size:14px;}
  header{padding:14px 20px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;}
  header h1{font-size:16px;margin:0;letter-spacing:.3px}
  header h1 .live{color:var(--green);font-size:11px;margin-left:8px;
    border:1px solid var(--green);border-radius:10px;padding:1px 7px;}
  .updated{color:var(--dim);font-size:11px}
  .statbar{display:flex;gap:18px;padding:10px 20px;border-bottom:1px solid var(--border);
    flex-wrap:wrap;font-size:12px;color:var(--dim)}
  .statbar b{color:var(--text);font-size:15px}
  .wrap{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 20px;}
  @media(max-width:900px){.wrap{grid-template-columns:1fr}}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;
    padding:14px;min-height:120px}
  .panel h2{font-size:13px;margin:0 0 10px;color:var(--dim);text-transform:uppercase;
    letter-spacing:.5px;font-weight:600}
  .item{padding:8px 10px;border-radius:7px;background:var(--panel2);margin-bottom:7px;}
  .item.high{border-left:3px solid var(--hi)}
  .ih{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:3px}
  .ihl{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
  .sym{font-weight:700}
  .bull{color:var(--green)} .bear{color:var(--red)} .neut{color:var(--dim)}
  .title{color:var(--text);font-size:12px}
  .reason{color:var(--dim);font-size:11px;margin-top:2px}
  .time{color:var(--dim);font-size:10px;white-space:nowrap}
  .badge{font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;text-transform:uppercase}
  .b-high{background:rgba(248,81,73,.16);color:var(--red)}
  .b-mid{background:var(--panel);color:var(--dim);border:1px solid var(--border)}
  .b-kw{background:rgba(210,153,34,.16);color:var(--amber)}
  .b-ai{background:rgba(75,159,255,.16);color:var(--blue)}
  .empty{color:var(--dim);font-size:12px;padding:10px 0}
  .lookup{padding:0 20px 20px}
  .lookup .panel{min-height:80px}
  .searchrow{display:flex;gap:8px;margin-bottom:10px}
  .searchrow input{flex:1;background:var(--panel2);border:1px solid var(--border);
    color:var(--text);border-radius:7px;padding:9px 11px;font-size:13px;outline:none}
  .searchrow button{background:var(--blue);color:#fff;border:none;border-radius:7px;
    padding:9px 16px;font-weight:600;cursor:pointer;font-size:13px}
  .searchrow button:hover{filter:brightness(1.1)}
  a{color:var(--blue);text-decoration:none}
  a:hover{text-decoration:underline}
  .hint{color:var(--dim);font-size:11px}
</style>
</head>
<body>
<header>
  <h1>News Intelligence <span class="live">24/7 LIVE</span></h1>
  <span class="updated" id="updated">connecting...</span>
</header>

<div class="statbar" id="statbar"></div>

<div class="wrap">
  <div class="panel">
    <h2>HIGH-priority board -- actionable now</h2>
    <div id="highBoard"><div class="empty">Loading...</div></div>
  </div>
  <div class="panel">
    <h2>Live feed -- HIGH &amp; MID</h2>
    <div id="feed"><div class="empty">Loading...</div></div>
  </div>
</div>

<div class="lookup">
  <div class="panel">
    <h2>Per-stock brain -- full stored history</h2>
    <div class="searchrow">
      <input id="sym" placeholder="Type a symbol e.g. RELIANCE, TCS, INFY and press Enter"/>
      <button onclick="lookup()">Look up</button>
    </div>
    <div class="hint" id="stockHint">Every news item ever stored for that stock, newest first.</div>
    <div id="stockHist"></div>
  </div>
</div>

<script>
const REFRESH_MS = {{REFRESH_MS}};

function dirClass(d){ return d==='bullish'?'bull':d==='bearish'?'bear':'neut'; }
function esc(s){ const e=document.createElement('div'); e.textContent=(s==null?'':String(s)); return e.innerHTML; }
function tfmt(t){ return esc((t||'').replace('T',' ').slice(0,19)); }

function itemHtml(n){
  const cl = n.classifier==='keyword'
    ? '<span class="badge b-kw" title="Free keyword classifier">Keyword</span>'
    : '<span class="badge b-ai" title="Paid Haiku classifier">AI</span>';
  const pr = n.priority==='HIGH'
    ? '<span class="badge b-high">High</span>'
    : '<span class="badge b-mid">Mid</span>';
  return `<div class="item ${n.priority==='HIGH'?'high':''}">
    <div class="ih">
      <span class="ihl">
        <span class="sym">${esc(n.symbol)}</span>
        <span class="${dirClass(n.direction)}">${esc(n.direction||'-')} (${n.confidence==null?'-':n.confidence}%)</span>
        ${pr}${cl}
      </span>
      <span class="time">${tfmt(n.time)}</span>
    </div>
    <div class="title">${esc(n.title||n.reason||'')}</div>
    ${n.reason && n.title ? `<div class="reason">${esc(n.reason)}</div>`:''}
  </div>`;
}

async function refresh(){
  try{
    const r = await fetch('/api/news'); const d = await r.json();
    const s = d.stats||{};
    document.getElementById('statbar').innerHTML =
      `<span><b>${s.total_all_time??0}</b> total stored</span>
       <span><b>${s.high??0}</b> HIGH (last ${s.window_hours??72}h)</span>
       <span><b>${s.mid??0}</b> MID (last ${s.window_hours??72}h)</span>
       <span><b>${s.distinct_symbols??0}</b> stocks with news</span>`;
    const hb = d.high_board||[];
    document.getElementById('highBoard').innerHTML = hb.length
      ? hb.map(itemHtml).join('') : '<div class="empty">No actionable HIGH news right now.</div>';
    const feed = d.feed||[];
    document.getElementById('feed').innerHTML = feed.length
      ? feed.map(itemHtml).join('') : '<div class="empty">No news in the window yet.</div>';
    document.getElementById('updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  }catch(e){
    document.getElementById('updated').textContent = 'Connection error -- retrying...';
  }
}

async function lookup(){
  const sym = document.getElementById('sym').value.trim().toUpperCase();
  if(!sym) return;
  document.getElementById('stockHint').textContent = 'Loading ' + sym + '...';
  try{
    const r = await fetch('/api/stock/' + encodeURIComponent(sym));
    const d = await r.json();
    document.getElementById('stockHint').textContent =
      d.count ? `${d.count} stored item(s) for ${sym}, newest first.`
              : `No stored news for ${sym}.`;
    document.getElementById('stockHist').innerHTML =
      (d.history||[]).map(itemHtml).join('') || '<div class="empty">Nothing yet.</div>';
  }catch(e){
    document.getElementById('stockHint').textContent = 'Lookup failed -- try again.';
  }
}
document.getElementById('sym').addEventListener('keydown',e=>{ if(e.key==='Enter') lookup(); });

refresh();
setInterval(refresh, REFRESH_MS);
</script>
</body>
</html>"""

_PAGE_HTML = _PAGE_HTML.replace(
    "{{REFRESH_MS}}", str(int(NEWS_DASHBOARD_REFRESH_SECONDS * 1000))
)


if __name__ == "__main__":
    sys.exit(run())
