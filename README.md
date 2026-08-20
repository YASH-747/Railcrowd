> # Click Here To Preview:- https://railcrowd.vercel.app/

# 🚆 RailCrowd — Real-Time Crowding & Disruption Intelligence for Indian Railways

> **Hackathon problem statement:** Commuters often board overcrowded buses or trains without knowing
> crowding levels beforehand. Create a solution that provides **real-time crowding information** —
> migrated to the **Indian Railways / IRCTC** context, enriched with **public APIs/datasets** and a
> **live news crawler** that predicts train-time changes.

RailCrowd answers one question before you step onto a platform:

> **"How crowded is my train right now — and is anything on the news going to delay it?"**

---

## ✨ What it does

| Feature | Detail |
|---|---|
| 🔎 **Train & station search** | 5,023 trains · 8,697 stations — by number, name or code |
| 🚦 **Live crowding levels** | Per train **and per class and per coach** (Low / Moderate / High / Critical) — labelled as a modelled estimate |
| 🕐 **Delay forecast + ETA** | Baseline + peak-hour + live-event model, next-stop ETA, 24-slot trend |
| 🗺 **Route map** | Real **vector India map (full Kashmir)** from Survey-of-India GeoJSON — **auto-zooms to each train's route** with live position, stops & a "Focus route / India view" toggle. **Stops are the real halts** from the public schedule DB (417k rows) and the route is drawn **through** them |
| 📰 **Live news crawler** | Multi-source (Google News · Bing News · The Hindu / TOI RSS, no API keys) → recency-filtered (`when:3d/7d`) → classified → **matched to trains/stations** → boosts crowding & delay |
| 🗣 **Community reports** | **No login** — anyone posts conditions (overcrowded platform, no space in train, rain on platform, coach issues…) per train/station, up-votes them, and they **feed the crowding model in real time** (votes amplify the effect) |
| 💾 **Database-backed votes** | Reports/votes persist in **Vercel Postgres or Vercel KV** on production — local JSON in dev — so a vote instantly changes the crowd rating for every visitor |
| ⚡ **Instant loading** | Trains dataset loaded once; popular/news/dashboard served from **snapshot JSON** (background refresh) + **localStorage cache** with lazy background update |
| 🔌 **Live API-ready (.env)** | Optional authorised feeds — NTES / IRCTC / RailAPI / OpenWeather — auto-detected from `.env`; falls back to public data when absent |
| 🔙 **Navigation** | Back buttons (header + detail pages) with a history stack |
| 📖 **Docs** | Full developer reference in [`DOCUMENTATION.md`](DOCUMENTATION.md) |
| 📍 **Station departures** | Upcoming trains from any station with crowding + delay at a glance |
| 🔬 **Explainable estimates** | Every number shows its **signal mix** (reservation inventory, crowdsourced pings, history, news) |

---

## 🧱 Architecture

```
┌─────────────────────────── data ───────────────────────────┐
│ stations (8,697) · trains (5,023) · route geometry          │  ← public datasets
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌──────────────────────── backend (Flask) ────────────────────┐
│ crowding.py  → deterministic fused crowding model            │
│ delay.py     → (inside crowding.py) delay + ETA + progress   │
│ news.py      → LIVE Google News RSS crawler + classifier     │
│ app.py       → REST API + static server                      │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌───────────────────────── frontend ──────────────────────────┐
│ Single-page app (vanilla JS, no build step)                  │
│ Home · Trains · Stations · Live News · Data & Method         │
└──────────────────────────────────────────────────────────────┘
```

### The crowding model (fused, explainable)

```
occupancy = f(
  45%  reservation inventory   (surrogate for IRCTC availability)
  25%  crowdsourced pings      (surrogate for passenger reports)
  20%  historical pattern      (train type · route · hour · day)
  10%  live events / news      (REAL — boosts when a disruption matches)
)
```

The model is **deterministic per (train, 10-minute bucket)** so it is stable across refreshes
and auditable, and it is designed so each surrogate can be **swapped 1:1** for an authorised
IRCTC / NTES feed.

### The news crawler (real)

- Crawls **Google News RSS** (`when:3d` / `when:7d` recency filters), **Bing News RSS** and
  **Times of India / The Hindu RSS** in parallel — **no API keys required**.
- Filters to railway-relevant stories, dedupes, and sorts **newest-first** with an age stamp
  ("2h ago"), a **fresh (<48h) flag**, and drops clearly-foreign rail news.
- Classifies each article by **category + impact** (high/medium/low).
- Extracts **train numbers & station names** and matches them against the dataset, so a train page
  shows *"this may affect your train"* and the model adds a crowding/delay boost.

---

## 🔌 Live API integrations (.env — optional)

RailCrowd is **fully functional with zero keys** (public data + model). If you have
authorised accounts, create `railcrowd/backend/.env` (copy `.env.example`) and set the ones
you own — **only configured providers are used; everything else falls back automatically.**

| Env var | What it enables | How to get it |
|---|---|---|
| `NTES_API_BASE` + `NTES_API_KEY` | Real live train status (delay, live position) | IRCTC / CRIS / RailTel **partner account** (NTES train-enquiry API) |
| `IRCTC_API_BASE` + `IRCTC_API_KEY` | Authorised IRCTC seat-availability / schedule | IRCTC **Partner/API-access program** (enterprise) |
| `RAILWAYAPI_BASE` + `RAILWAYAPI_KEY` | Commercial rail data (train status JSON) | RailAPI / RailYatri / ConfirmTkt / ixigo enterprise |
| `OPENWEATHER_API_KEY` | Live weather at stations (rain/flood context) | openweathermap.org → free tier |
| `GOOGLE_MAPS_API_KEY` | Station geocoding / static maps (reserved) | Google Cloud Console |

`GET /api/health` reports which integrations are active; the UI shows a
"NTES live" vs "RailCrowd model" badge accordingly.

---

## 🗣 Community reports (public — no login)

- `POST /api/reports` — submit `{type, train?, station?, message}` (validated: train/station must exist).
- `GET /api/reports?train=&station=` — feed; `POST /api/reports/<id>/vote` — up-vote.
- Reports live in `data/reports.json` locally, or in **Vercel Postgres / Vercel KV** on production
  (`storage.py` picks automatically). Recent reports (≤12h, time-decayed) **visibly change the
  train's crowding % and delay**, and **every up-vote amplifies the impact** (+8%/vote, capped) —
  the train page shows a "Community impact" note so users see their vote take effect in real time.

---

## ▲ Deploy to Vercel

1. Install Node.js, then on Windows run **`vercel.bat`** (double-click) — it installs the Vercel
   CLI, logs in, links the project and deploys. (Manual: `vercel login && vercel link && vercel --prod`.)
2. **Attach a database** (so votes persist & affect crowd ratings in real time):
   - **Vercel Postgres** — dashboard → Storage → Postgres → link to this project. RailCrowd
     auto-creates the `reports` table. Env vars `POSTGRES_URL` etc. are auto-injected.
   - **Vercel KV** — dashboard → Storage → KV → link to this project (`KV_REST_API_URL`/`KV_REST_API_TOKEN`).
3. Optional live data: set `OPENWEATHER_API_KEY`, `NTES_API_BASE/KEY`, etc. via `vercel env add`.

Files: [`vercel.json`](vercel.json) (rewrites), [`api/index.py`](api/index.py) (WSGI entry),
[`vercel.bat`](vercel.bat) (one-click Windows deploy), [`.vercelignore`](.vercelignore) (keeps the
bundle small — heavy build-only files are excluded). On Vercel the app runs serverless:
snapshot files/background threads are disabled automatically and everything is computed on demand.
The SPA is served from memory with an SPA fallback, so the homepage never 404s.

**"Not Found" after deploying?** Check `https://YOUR-APP.vercel.app/api/health`:
- `frontend: true` → homepage works; if it's `false`, the `frontend/` folder wasn't uploaded
  (project root is wrong — it must be the `railcrowd/` folder containing `vercel.json`).
**"Unexpected token '<' … is not valid JSON"** (API returning HTML): fixed by the
`PathNormalizer` in `api/index.py` + the `/:path* → /api/index/:path*` rewrite — redeploy with
`vercel --prod --force` and `/api/health` should return JSON.
- `storage: postgres` (or `kv`) → votes persist in real time; `storage: local` means the database
  isn't linked yet (reports can't be saved on Vercel's read-only filesystem).
Then redeploy with `vercel --prod --force`.

---

## 🚀 Run it

```bash
pip install flask numpy scipy
cd railcrowd/backend
PORT=5000 python3 app.py
# open http://localhost:5000
```

> The data build scripts are in `railcrowd/data/` (`build_dataset.py`, `add_premium.py`) if you
> want to re-derive `dataset.json` from the source datasets.

---

## 🔌 API

| Endpoint | Description |
|---|---|
| `GET /api/health` | status + counts |
| `GET /api/train/<number>` | full schedule, live crowding, delay, matched news |
| `GET /api/train/<number>/live` | live status only |
| `GET /api/station/<code>` | station info + upcoming departures |
| `GET /api/trains/search?q=` · `/api/stations/search?q=` | search |
| `GET /api/stations/nearby?lat=&lon=` | geolocated stations |
| `GET /api/popular` | dashboard snapshot of popular trains (served from snapshot JSON) |
| `GET /api/news?limit=` | classified live news feed |
| `GET /api/reports` · `POST /api/reports` | community reports |
| `POST /api/reports/<id>/vote` | up-vote a report |

---

## 📚 Data sources (all public)

- **Indian Railways station master** — 8,697 stations with codes, zones, divisions, categories, geo (public dataset).
- **Indian Railways train schedules** — 5,023 trains with type, classes, distances, route geometry (public dataset, *IndianRailwayOpenReference*), audited to remove defunct "Special" services.
- **India vector boundaries** — Survey-of-India country outline (full Kashmir) + state boundaries from public GeoJSON (datameet / geohacker), simplified for the frontend.
- **Live news** — Google News RSS (`when:3d/7d`), Bing News RSS, Times of India & The Hindu RSS.

## ⚠️ Honesty & limitations

Indian Railways / **IRCTC does not expose a public real-time occupancy API**, and NTES live train
status is not freely available without registration. RailCrowd therefore:

1. uses **real** public datasets for stations & schedules,
2. uses a **real** live news crawler for disruptions,
3. **models** crowding/delay as a clearly-labelled, explainable estimate.

Every screen separates *real* vs *modelled* signals so the prototype is honest about what would be
swapped for production feeds.

### Production roadmap (what would make it fully live)

- **NTES** live train lat/long + delay (official).
- **Authorised IRCTC availability** → true per-class occupancy proxy.
- **Station footfall sensors** (Wi-Fi/CCTV people-counting) and **axle weight sensors**.
- **Crowdsourced "this coach is packed"** reports with decay & verification.
- Platform displays, WhatsApp bot, IRCTC app integration.

---

*Built as a hackathon prototype. Not affiliated with Indian Railways or IRCTC.*
