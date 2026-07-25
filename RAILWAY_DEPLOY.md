# Running the News Engine 24/7 on Railway

This guide gets the news engine (`run_news_engine.py`) running in the cloud
so it captures news around the clock — overnight, weekends, holidays — even
when your PC is off. The trading bot on your PC then reads that same news
from Railway's database.

## What you're setting up

```
   Railway (cloud, always on)                 Your PC
  ┌──────────────────────────┐          ┌────────────────────────┐
  │  news-engine worker       │  writes  │  main.py (brain bot)    │
  │  run_news_engine.py       │────┐     │  dashboard              │
  │  polls RSS + NSE/BSE 24/7 │    │     │        │ reads          │
  └──────────────────────────┘    ▼     └────────┼───────────────┘
                          ┌─────────────────┐    │
                          │ Railway Postgres │◄───┘
                          │  (the shared DB) │
                          └─────────────────┘
```

One database, two readers/writers. The engine writes; the brain bot and
dashboard read. Nobody steps on anyone — the engine is the only writer.

---

## Part A — Deploy the news engine to Railway

**1. Push this project to GitHub** (Railway deploys from a Git repo).
Create a private repo and push the `Opportunity Trader` folder to it. Make
sure `run_news_engine.py`, `requirements.txt`, `Procfile`, `railway.json`,
and the `news_bot/`, `core/`, `data/master_stocks.csv` files are all
committed. (`.env` should NOT be committed — secrets go in Railway's UI.)

**2. Create a Railway project.** Go to railway.app, sign in, click
**New Project → Deploy from GitHub repo**, and pick the repo. Railway
auto-detects Python (via `requirements.txt`) and uses `railway.json`'s
start command: `python run_news_engine.py`.

**3. Add a Postgres database.** In the project, click **New → Database →
Add PostgreSQL**. Railway creates it and automatically injects a
`DATABASE_URL` variable into your services. The news engine reads that
variable on startup — no code change needed.

**4. Set the engine's environment variables.** Open the news-engine
service → **Variables**. Confirm `DATABASE_URL` is there (Railway adds it).
Then add:
   - `NEWS_CLASSIFIER_MODE = auto` (already the default; free keyword now)
   - `ANTHROPIC_API_KEY = ...` — ONLY when you're ready to pay for Haiku.
     Leave it unset for now; the free keyword classifier runs automatically.

**5. Deploy and watch the logs.** Railway builds and starts the worker.
Open the service's **Logs**. Within a minute you should see:
```
[NEWS_ENGINE] Starting 24/7 news engine. Store: .../railway. Poll every 45s...
[NEWS_ENGINE] cycle 1: N ingested, M matched, X HIGH, Y MID. Store now holds ...
```
If ingested stays 0, the sources may be blocking Railway's IP (NSE/BSE
sometimes block datacenter IPs — the RSS sources are the reliable ones).
The engine keeps running and retrying regardless; it never crashes on a
bad source.

The engine is now live 24/7. `restartPolicyType: ALWAYS` (in `railway.json`)
means Railway restarts it automatically if it ever exits.

---

## Part B — Point your PC's trading bot at the same database

The brain bot needs to READ the cloud database instead of a local file.

**1. Copy the database URL.** In Railway, open the **Postgres** service →
**Variables** (or **Connect**) → copy the `DATABASE_URL` value. It looks
like `postgresql://user:pass@host.railway.app:5432/railway`.

**2. Put it in your local `.env`.** On your PC, in `D:\Opportunity Trader\.env`,
add the line (paste the real value):
```
DATABASE_URL=postgresql://user:pass@host.railway.app:5432/railway
```
`postgres://` and `postgresql://` are both accepted.

**3. Confirm the external-engine switch is on.** In `news_bot/config.py`,
`NEWS_ENGINE_EXTERNAL = True` (the default). This tells `main.py` NOT to
poll news itself — the Railway engine is the sole writer; your bot only
reads. (Set it to `False` only if you ever want to run news locally with no
Railway worker.)

**4. Run the bot as usual.** `main.py` will now read HIGH-priority news from
the cloud store and the dashboard's News Impact panel fills from it. On
startup you'll see: `[NEWS_BOT] External engine mode -- reading the shared
store...`.

---

## Costs & the free month

Railway's trial/free credit covers roughly a month of a small worker plus a
small Postgres. When it runs low, Railway warns you. Options at that point:
keep it on a paid plan (cheap for this size), or switch
`NEWS_ENGINE_EXTERNAL = False` and run the news engine locally again (the
code is identical — it just falls back to the local SQLite file when
`DATABASE_URL` is unset).

## Housekeeping

The store keeps every stored item forever (that's the per-stock "brain").
If a free-tier Postgres ever nears its size cap, you can trim old rows:
`NewsStore().prune_older_than(days=30)` — it's never called automatically,
so nothing is deleted unless you ask.

## Quick local test (before Railway)

You can run the exact same engine locally against a SQLite file first:
```
python run_news_engine.py
```
Leave `DATABASE_URL` unset — it writes to `data/news.db`. Ctrl-C to stop.
Watch the same `[NEWS_ENGINE] cycle N:` lines. This is the identical code
Railway runs, so if it works here it works there.
