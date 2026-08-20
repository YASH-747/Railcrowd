# RailCrowd — Developer Documentation

> Complete technical reference for the RailCrowd codebase: architecture, every module,
> every function, the data pipeline, the API surface, and how to extend it.

- **Stack:** Python 3 + Flask (backend), vanilla JS single-page app (frontend), JSON files (data).
- **No build step.** No frontend framework. No database server (JSON + snapshots by design).
- **Graceful degradation:** every external dependency (live APIs, news RSS) has a
  local/public fallback, so the app always runs.
- **Dependencies:** see [`requirements.txt`](requirements.txt) (`flask`, `numpy`, `scipy`, `requests`).

---

## 1. Directory layout

```
railcrowd/
├── README.md                 # product overview (pitch)
├── DOCUMENTATION.md          # this file
├── backend/
│   ├── app.py                # Flask app: routes, snapshots, wiring (Vercel-aware)
│   ├── crowding.py           # occupancy + delay engine (the model)
│   ├── news.py               # multi-source news crawler + classifier
│   ├── reports.py            # community reports + vote-weighted boost
│   ├── storage.py            # persistence: local JSON / Vercel Postgres / Vercel KV
│   ├── integrations.py       # optional live APIs (NTES/IRCTC/RailAPI/OpenWeather)
│   ├── .env.example          # template for secrets (copy to .env)
│   └── .env                  # (you create this; NOT committed)
├── api/
│   └── index.py              # Vercel serverless WSGI entry point
├── vercel.json               # Vercel rewrites + function bundle config
├── vercel.bat                # one-click Windows deploy script
├── requirements.txt          # Python dependencies (pip install -r requirements.txt)
├── frontend/
│   └── index.html            # the entire SPA (CSS + JS inline)
└── data/
    ├── dataset.json          # 5,023 trains + 8,697 stations (compiled, audited)
    ├── reports.json          # community reports (created at runtime)
    ├── snapshots/            # popular.json / news.json / dashboard.json (runtime cache)
    ├── build_dataset.py      # compiles dataset.json from source GeoJSON
    ├── build_schedules.py    # REBUILDS accurate stops from schedules.json (real halts)
    ├── build_india_map.py    # compiles india_map.js from Survey-of-India GeoJSON
    ├── splice_map.py         # injects the vector map into index.html
    ├── india_map.js          # generated: INDIA_OUTLINE + INDIA_STATES
    ├── schedules.json        # 417k stop rows (every station passed, with times)
    ├── india_composite.geojson / india_gh.geojson / stations*.json / trains.json  # raw sources
    └── smoke_map.js          # Node smoke-test for the map renderer
```

---

## 2. How to run

```bash
pip install -r requirements.txt
cd railcrowd/backend
cp .env.example .env                    # optional — add keys for live data
PORT=5000 python3 app.py                # http://localhost:5000
```

The trains dataset (15 MB) is loaded **once** into memory at startup. A background thread
(`refresh_snapshots`) rewrites `data/snapshots/*.json` every 4 minutes so the busy endpoints
serve in ~10 ms. Individual train pages are computed on demand.

---

## 3. Environment variables (`.env`)

The file lives at `railcrowd/backend/.env`. **All values are optional** — missing ones disable
that integration. See `.env.example` for sign-up links.

| Variable | Module | Purpose |
|---|---|---|
| `NTES_API_BASE`, `NTES_API_KEY` | integrations | Live train running status (delay / position) |
| `IRCTC_API_BASE`, `IRCTC_API_KEY` | integrations | Authorised IRCTC seat availability / schedule |
| `RAILWAYAPI_BASE`, `RAILWAYAPI_KEY` | integrations | Commercial rail-data provider (train status) |
| `OPENWEATHER_API_KEY` | integrations | Live station weather (rain/flood) |
| `GOOGLE_MAPS_API_KEY` | integrations | Geocoding / static maps (reserved) |
| `PORT` | app | HTTP port (default 5000) |

`GET /api/health` returns `integrations` (list of active providers).

---

## 4. Backend reference

### 4.1 `app.py` — routes & wiring

Loads `dataset.json` once; instantiates `CrowdingEngine`, `NewsCrawler`, `ReportStore`,
`MediaStore`, `Integrations`.

| Function | Purpose |
|---|---|
| `search_stations(q, limit)` | Name/prefix then code search over 8,697 stations |
| `search_trains(q, limit)` | Number/name search over 5,207 trains |
| `trains_from(code, limit)` | Trains calling at a station, sorted by stop time |
| `live_signal(number, items)` | Fuses news boost + community boost into the engine signal; applies optional external (NTES/RailAPI) delay/position override |
| `_write_snapshot/_read_snapshot` | Atomic JSON snapshot write / TTL-read |
| `compute_popular(items)` | Recomputes the popular-trains list (favourites in `FAV`) |
| `refresh_snapshots()` | Background loop: news → popular → dashboard → write snapshots |
| `ensure_snapshots()` | Starts the background thread once (idempotent) |

**Routes**

| Route | Method | Description |
|---|---|---|
| `/api/health` | GET | Status, counts, active integrations |
| `/api/stations/search?q=` | GET | Station search |
| `/api/stations/nearby?lat=&lon=` | GET | Nearest stations (equirectangular approx) |
| `/api/station/<code>` | GET | Station info + departures + weather + reports |
| `/api/trains/search?q=` | GET | Train search |
| `/api/train/<number>` | GET | Full schedule + live signal + news events + reports + **community impact** |
| `/api/train/<number>/live` | GET | Live signal only |
| `/api/popular[?refresh=1]` | GET | Popular trains (snapshot; `refresh=1` forces recompute) |
| `/api/news?q=&limit=` | GET | Classified live news (snapshot) |
| `/api/dashboard` | GET | Dashboard stats (snapshot) |
| `/api/reports/types` | GET | Report type catalogue |
| `/api/reports` | GET/POST | List (filters `train`, `station`, `limit`) / create (JSON or multipart) |
| `/api/reports/<rid>/vote` | POST | Up-vote a report |

---

### 4.2 `crowding.py` — the occupancy & delay model

Deterministic per (train, 10-minute bucket) so results are stable across refreshes and auditable.

| Name | Purpose |
|---|---|
| `TYPE_PROFILE` | Base occupancy + spread per train type (Raj/Shtb/Pass/MEMU/VB/…) |
| `CLASS_META` | Per class: demand weight, coach count, seat capacity |
| `PEAKS` | Morning/evening peak-hour multipliers |
| `level_of(pct)` | 0.45/0.72/0.92 thresholds → Low/Moderate/High/Critical |
| `level_color(pct)` | Level → hex colour |
| `class CrowdingEngine` | Holds trains/stations; `signal()`, `delay()`, `progress()` |
| `CrowdingEngine._rng(train, when, *salt)` | Seeded RNG (stable per bucket) |
| `CrowdingEngine.time_factor/day_factor` | Hour-of-day / weekday demand multipliers |
| `CrowdingEngine.signal(number, when, news_boost, delay_news)` | Returns full live payload: overall + per-class occupancy, delay, trend, sources, route progress |
| `CrowdingEngine.delay(number, when, news_delay, rng)` | Baseline + chronic-route + peak + news; 24-slot trend |
| `CrowdingEngine.progress(train, when, delay)` | Route fraction, current/next stop, ETA; "Not yet departed" / "Running" / "Arrived" |

**Signal fusion** (shown to users): 45% reservation inventory (surrogate) · 25% crowdsourced
pings (surrogate) · 20% historical pattern · 10% live news/community (real).

---

### 4.3 `news.py` — the news crawler

| Name | Purpose |
|---|---|
| `G_QUERIES` / `B_QUERIES` | Google News (with `when:3d/7d`) & Bing query sets |
| `INDIA_FEEDS` | Times of India + The Hindu RSS (rail-filtered) |
| `CATEGORY_RULES` | Regex → (category, severity). Categories: Derailment, Cancellation, Delay, Strike, Weather, Festival rush, Security, New service |
| `classify(title, desc)` | Highest-severity matching rule wins; severity → impact (high/medium/low) |
| `parse_pub(s)` | RFC-822 → aware UTC datetime (multi-format) |
| `class NewsCrawler` | Fetching + caching |
| `NewsCrawler._fetch_google/_bing/_india_feeds` | Per-source fetchers (parallel via `ThreadPoolExecutor`) |
| `NewsCrawler._normalize(raw)` | Rail-relevance filter, foreign-news filter, dedupe, age/fresh flags, newest-first sort |
| `NewsCrawler.get_news(limit)` | 8-min cached, returns annotated items |
| `NewsCrawler.annotate(items)` | Adds category/impact/trains/stations |
| `NewsCrawler.match(item)` | Extracts 5-digit train numbers + station names |
| `NewsCrawler.impact_for_train(number, items)` | Precise (number / origin+destination) vs soft (single city) matching → boost + delay minutes + events |

---

### 4.4 `reports.py` — community reports

| Name | Purpose |
|---|---|
| `REPORT_TYPES` | (code, label, occupancy_boost, delay_minutes) — 8 types |
| `TYPE_LABEL/TYPE_BOOST/TYPE_DELAY` | Lookup dicts |
| `_vote_weight(votes)` | +8% impact per up-vote (capped at ~3×) — votes move the crowd rating |
| `_seed()` | 6 demo reports so the feed is never empty (local dev only) |
| `class ReportStore` | |
| `ReportStore.storage_kind` | "local" / "postgres" / "kv" (exposed in `/api/health`) |
| `ReportStore.list(train, station, limit)` | Filtered, newest-first |
| `ReportStore.recent_for_train(number, hours)` | Recent reports for a train |
| `ReportStore.boost_for_train(train)` | Time-decayed (≤12 h) **and vote-weighted** occupancy boost + delay minutes from a train's own reports **and** its route stations |
| `ReportStore.add(type, train, station, message)` | Validates type/train/station/message; returns `(report, error)` |
| `ReportStore.vote(rid, delta)` | Up-vote (≥0) — persists to the storage backend |

### 4.5 `storage.py` — pluggable persistence (Vercel DB)

| Name | Purpose |
|---|---|
| `StorageError` | Raised by backends on failure (caught → friendly error) |
| `LocalBackend` | `data/reports.json` (dev) — atomic replace writes |
| `KVBackend` | Vercel KV / Upstash REST (`KV_REST_API_URL` + `KV_REST_API_TOKEN`) — whole list under one JSON key |
| `PostgresBackend` | Vercel Postgres (`POSTGRES_URL`…) — `reports` table auto-created, `psycopg2` |
| `get_backend()` | Chooses Postgres → KV → local, based on env vars |

Backends share the interface `list_all()` / `insert(report)` / `update_votes(rid, votes)`. On Vercel,
reports/votes must go through Postgres or KV because the filesystem is read-only; `storage.py`
handles that automatically, so a vote persists and **affects crowd ratings in real time** for all users.

### 4.6 `integrations.py` — optional live APIs

| Name | Purpose |
|---|---|
| `load_dotenv(path)` | Minimal `.env` parser (existing env vars win) |
| `load_env()` | Loads `backend/.env` + repo-root `.env` |
| `get(name, default)` | Env accessor |
| `class Integrations` | |
| `Integrations.active()` | List of configured providers (shown in health/dashboard) |
| `Integrations.train_status(number)` | NTES → RailAPI order; returns None if unconfigured |
| `Integrations._parse_status(data, provider)` | Normalises provider JSON (tolerant of field names) |
| `Integrations.seat_availability(...)` | Authorised IRCTC availability (None if unconfigured) |
| `Integrations.weather(lat, lon)` | OpenWeather current conditions |

## 5. Frontend reference (`frontend/index.html`)

One file: inline CSS + JS. No external resources (works offline in sandboxed previews).

**State & helpers**

| Name | Purpose |
|---|---|
| `esc(s)` | HTML-escape |
| `api(p)` | `fetch` + JSON, throws on non-2xx |
| `pct(x)`, `levelBadge(level, extra)`, `obar(pct)`, `typeTag(t)` | Rendering helpers |
| `INDIA_OUTLINE` / `INDIA_STATES` / `INDIA_BOUNDS` | Vector map data (generated) |
| `MAPW/MAPH`, `boundsOf(rings)`, `makeProj(b)`, `ringPath(rings, P)` | Map projection (equirectangular, auto-fit) |
| `ageLabel(m)` / `ageAgo(iso)` | "2h ago" formatting |

**Routing & caching**

| Name | Purpose |
|---|---|
| `BACKSTACK`, `LASTHASH` | History stack for the back button |
| `goBack()` | Pops the stack (header ← button + inline links) |
| `route()` | Hash router; toggles back button; dispatches to `render*` |
| `cacheGet/cacheSet` | localStorage cache helpers |
| `renderHome()` | **Instant** render from `rc_home_v1` cache, then lazy `loadHome()` background refresh → `paintHome(data, live)` |
| `bindSearch()` | Typeahead (station + train) |

**Pages**

| Function | Purpose |
|---|---|
| `renderTrain(number)` | Live status, class/coach heatmap, route map, schedule, signal mix, news, community reports, report form |
| `renderStation(code)` | Departures board, weather badge, reports + form |
| `renderTrainSearch()` / `renderStationSearch()` | Search pages |
| `renderNews()` | Multi-source feed with category + fresh-48h filters |
| `renderCommunity()` | Full community feed + report form |
| `renderData()` | Architecture / method / sources page |

**Map**

| Name | Purpose |
|---|---|
| `drawMap(t, pr, stops, mode)` | Renders SVG; `mode` = `"route"` (auto-zoom to route bbox) or `"india"` (whole country). Pulsing marker at `pr.fraction` |
| `setMapMode(m)` | Toggle between Focus route / India view |
| `drawSpark(series)` | Delay-trend sparkline |

**Community reports (client)**

| Name | Purpose |
|---|---|
| `renderReportList(reports, emptyMsg)` | Feed items (text reports + votes) |
| `reportFormHTML(defTrain, defStation)` | Type select + train/station inputs + message + file picker |
| `previewFiles()` / `rmFile(i)` | Client-side thumbnail previews via `URL.createObjectURL` |
| `submitReport(defTrain, defStation)` | JSON (text-only) or multipart `FormData` (with files) POST, then `route()` |
| `voteReport(id, btn)` | One-tap up-vote (button locks after voting) |

---

## 6. Data pipeline

1. **`build_dataset.py`** — reads `stations.json` + `trains.json` (GeoJSON, public sources),
   builds an equirectangular `cKDTree` over station coords, snaps every train's route polyline to
   real stations, reconstructs per-stop times by linear interpolation, decimates route geometry,
   and writes `dataset.json` (stations dict + trains list).
2. **`build_schedules.py`** — **replaces heuristic stops with REAL stops** from `schedules.json`
   (auto-downloaded if missing; ~82 MB, build-time only — the running app only needs `dataset.json`)
   (417k rows = every station a train passes, with arrival/departure/day). A train halts where
   `arrival != departure` (dwell) or at its origin/terminus; passenger/MEMU fall back to all rows.
   Stops are remapped to station coordinates, distances recomputed by haversine, and each train's
   route polyline is rebuilt **through its stops** so map + dots align. Verified: 12301 →
   HWH·DHN·PNME·GAYA·MGS·ALD·CNB·NDLS.
3. **`build_india_map.py`** — Douglas-Peucker simplification of the Survey-of-India country
   outline (`india_composite.geojson`) + state boundaries (`india_gh.geojson`) → `india_map.js`.
4. **`splice_map.py`** — injects `india_map.js` + the auto-focus map renderer into `index.html`.
5. **`smoke_map.js`** — Node smoke-test for the map code (no browser needed).

> **Data audit:** the compiled `dataset.json` excludes (a) hand-added reference schedules and
> (b) all 0-prefixed "Special" trains (temporary/defunct services that no longer appear in the
> official *Where is my Train* app), leaving 5,023 trains. The remaining list is a public
> timetable snapshot — verify any single train against NTES before relying on it.

Regenerate everything with:
```bash
cd railcrowd/data
python3 build_dataset.py && python3 build_schedules.py
python3 build_india_map.py && python3 splice_map.py
```

---

## 7. API examples

```bash
curl localhost:5000/api/train/12951                      # full live status
curl "localhost:5000/api/stations/search?q=mumbai"       # station search
curl "localhost:5000/api/trains/search?q=vande"          # train search
curl localhost:5000/api/news?limit=20                    # live news feed
curl localhost:5000/api/reports?station=BCT              # community reports

# create a text report
curl -X POST localhost:5000/api/reports \
  -H "Content-Type: application/json" \
  -d '{"type":"overcrowded_platform","station":"BCT","message":"Platform 3 packed"}'

# create a report with a photo
curl -X POST localhost:5000/api/reports \
  -F type=rain_platform -F station=ADI \
  -F message="Heavy rain on platform 6" \
  -F file=@photo.jpg

# up-vote
curl -X POST localhost:5000/api/reports/<id>/vote
```

---

## 8. Design decisions & how to extend

- **Why JSON files, not a DB?** Local dev keeps zero-setup JSON (atomic `os.replace`). On Vercel,
  `storage.py` transparently switches to Vercel Postgres / Vercel KV so reports & votes persist
  across serverless instances and affect crowd ratings in real time.
- **Why deterministic "synthetic" crowding?** IRCTC/NTES do not expose public real-time occupancy.
  The model is stable across refreshes (seeded per time bucket) and every number carries a
  labelled signal mix so it is honest and auditable.
- **Adding a provider:** implement a fetcher in `integrations.py`, call it in
  `app.py::live_signal`, and document the env var in `.env.example`.
- **Adding a news source:** add a `_fetch_*` method + a query list in `news.py`, register it in
  `_fetch_all()`.
- **Adding a report type:** extend `REPORT_TYPES` in `reports.py` (label + boost + delay) — the
  frontend reads `/api/reports/types` and renders automatically.

## 9. Vercel deployment

- **Entry point** — `api/index.py` imports the Flask `app`; `vercel.json` rewrites every path to it.
- **Serverless mode** — `app.py` detects `VERCEL=1`: background snapshot thread + snapshot file
  writes are disabled (read-only FS, stateless instances); `/api/popular`, `/api/news`,
  `/api/dashboard` compute on demand.
- **Database** — set `POSTGRES_URL` (Vercel Postgres, table auto-created) or `KV_REST_API_URL` +
  `KV_REST_API_TOKEN` (Vercel KV). `storage.get_backend()` picks it up; `/api/health` reports
  `storage: postgres|kv|local`. Votes then persist and affect crowd ratings in real time.
- **Windows one-click** — run `vercel.bat` (installs CLI, logs in, links, prints DB setup steps,
  pushes `backend/.env` secrets, deploys with `vercel --prod`).
- **Bundle** — `vercel.json` `functions.api/index.py.includeFiles` ships `backend/**`,
  `data/dataset.json`, `frontend/**`; `requirements.txt` is installed automatically.

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: flask` | Re-run `pip install -r requirements.txt` (sandbox packages don't persist between sessions) |
| Vercel shows "Not Found" (Werkzeug 404) | The Flask app ran but couldn't serve `frontend/index.html`. Check `https://YOUR-APP.vercel.app/api/health` → `frontend` must be `true`. If `false`, the project root is wrong (must be the `railcrowd/` folder with `vercel.json`) or `frontend/**` wasn't uploaded — fix and redeploy with `vercel --prod --force` |
| Frontend shows "Unexpected token '<' … is not valid JSON" | Vercel rewrote every request to `/api/index`, so Flask served the SPA HTML for API paths. Fixed by the `PathNormalizer` in `api/index.py` + the `/:path* → /api/index/:path*` rewrite — redeploy with `vercel --prod --force`. Verify `/api/health` returns JSON and `request_path: "/api/health"` |
| News shows old/offline sample | No network to the RSS feeds, or cached >8 min — retry; fallback is intentional |
| Train page says "RailCrowd model" | Expected — no `.env` provider configured; add NTES/IRCTC keys to get "live" badge |
| Home feels slow on very first load | First visit has no cache; subsequent visits are instant (localStorage + snapshots) |
