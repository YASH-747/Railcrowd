#!/usr/bin/env python3
"""
RailCrowd — real-time crowding & disruption intelligence for Indian Railways.

Backend API + static frontend server.

Performance: the trains/stations dataset is loaded ONCE into memory at startup
(static). The dynamic parts (popular trains, news, dashboard) are written to
snapshot JSON files by a background thread every few minutes; API endpoints read
the snapshots instantly and recompute on demand only if a snapshot is missing or
stale. Optional live integrations (NTES / IRCTC / RailAPI / OpenWeather) are
enabled only when present in `.env` — otherwise public data + model are used.

Run:  python3 app.py   (serves on 0.0.0.0:5000)
"""
import json
import math
import os
import re
import threading
import time

from flask import Flask, jsonify, request, send_from_directory, Response

from crowding import CrowdingEngine, utc_now
from news import NewsCrawler
from reports import ReportStore, REPORT_TYPES, TYPE_LABEL
from integrations import Integrations, load_env

load_env()  # read .env if present (live API keys/base URLs)

# ---- robust resource resolution (works locally AND on Vercel serverless,
#      where the bundle layout / working directory can differ) ---------------
HERE = os.path.dirname(os.path.abspath(__file__))  # .../backend


def _find_root():
    cands = []
    cands.append(os.path.dirname(HERE))                       # project root (railcrowd)
    cands.append(os.getcwd())                                 # wherever it's run from
    cands.append("/var/task")                                 # Vercel function root
    cands.append(os.path.dirname(os.path.dirname(HERE)))      # one level above backend
    for c in cands:
        if c and os.path.exists(os.path.join(c, "data", "dataset.json")):
            return c
    return cands[0]


ROOT = _find_root()
DATA = os.path.join(ROOT, "data")
SNAPDIR = os.path.join(DATA, "snapshots")
FRONTEND = os.path.join(ROOT, "frontend")
SNAP_TTL = 360  # seconds a snapshot is considered fresh

# Read the SPA once into memory so the homepage never depends on the
# filesystem layout at request time (fixes the Vercel "Not Found" 404).
INDEX_HTML = ""


def _load_index_html():
    cands = [os.path.join(FRONTEND, "index.html"),
             os.path.join(os.getcwd(), "frontend", "index.html"),
             os.path.join(os.path.dirname(HERE), "frontend", "index.html")]
    for p in cands:
        try:
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    return f.read()
        except Exception:
            continue
    return "<h1>RailCrowd</h1><p>frontend/index.html was not bundled — check vercel.json/.vercelignore.</p>"


INDEX_HTML = _load_index_html()

app = Flask(__name__, static_folder=None)

# Vercel serverless: no background threads, no filesystem writes (read-only FS,
# stateless instances). Snapshot caching is disabled; endpoints compute on demand
# and community reports/votes persist via the storage backend (Vercel Postgres /
# Vercel KV). Local dev keeps JSON snapshots + background refresh.
IS_VERCEL = os.environ.get("VERCEL") == "1"

print("[RailCrowd] loading dataset …", flush=True)
with open(os.path.join(DATA, "dataset.json")) as f:
    DS = json.load(f)
TRAINS = DS["trains"]
STATIONS = DS["stations"]
print(f"[RailCrowd] {len(TRAINS)} trains, {len(STATIONS)} stations", flush=True)

engine = CrowdingEngine(TRAINS, STATIONS)
crawler = NewsCrawler(TRAINS, STATIONS)
reports = ReportStore(TRAINS, STATIONS)
integ = Integrations()
print(f"[RailCrowd] community storage: {reports.storage_kind} | "
      f"{'Vercel serverless mode' if IS_VERCEL else 'local dev mode'}", flush=True)

TRAIN_BY_NUM = {t["number"]: t for t in TRAINS}
STATION_BY_CODE = {c: s for c, s in STATIONS.items()}
STATION_NAMES = sorted((s["name"].lower(), c) for c, s in STATIONS.items())

FAV = ["12951", "12952", "12001", "12002", "12301", "12302", "12627", "12628",
       "12259", "12260", "12957", "12958", "22201", "22202", "12430", "12429",
       "20901", "20902", "22435", "22436", "20607", "20608", "12839", "12840",
       "12303", "12621", "12915", "22903", "12615", "12137", "19005", "19215"]


# ------------------------------------------------------------------ helpers
def _matches(text, q):
    return q in text


def search_stations(q, limit=12):
    q = q.strip().lower()
    if not q:
        return []
    out = []
    for name, code in STATION_NAMES:
        if name.startswith(q) or q in name:
            s = STATIONS[code]
            out.append({"code": code, "name": s["name"], "state": s["state"],
                        "lat": s["lat"], "lon": s["lon"], "category": s.get("category", "")})
            if len(out) >= limit:
                return out
    for code, s in STATIONS.items():
        if code.lower().startswith(q):
            out.append({"code": code, "name": s["name"], "state": s["state"],
                        "lat": s["lat"], "lon": s["lon"], "category": s.get("category", "")})
            if len(out) >= limit:
                return out
    return out


def search_trains(q, limit=30):
    q = q.strip().lower()
    if not q:
        return []
    out = []
    for t in TRAINS:
        if q in t["number"] or q in t["name"].lower():
            out.append(t)
            if len(out) >= limit:
                break
    return out


def trains_from(station_code, limit=12):
    hits = []
    for t in TRAINS:
        for s in (t.get("stops") or []):
            if s["code"] == station_code:
                hits.append({"train": t, "stop": s})
                break
    def key(h):
        mm = re.match(r"(\d{1,2}):(\d{2})",
                      h["stop"].get("dep") or h["stop"].get("arr") or h["stop"].get("time") or "")
        return int(mm.group(1)) * 60 + int(mm.group(2)) if mm else 99999
    hits.sort(key=key)
    return hits[:limit]


def live_signal(number, items=None):
    """Compute the live signal for a train, fusing model + news + community reports.

    Returns (train, signal, news_events, community_reports, community_boost, community_delay).
    """
    t = TRAIN_BY_NUM.get(str(number))
    if not t:
        return None
    now = utc_now()
    news_boost, news_delay, events = crawler.impact_for_train(number, items=items)
    rep_boost, rep_delay, rep_hits = reports.boost_for_train(t)
    sig = engine.signal(number, now,
                        news_boost=min(0.30, news_boost + rep_boost),
                        delay_news=news_delay + rep_delay)
    # optional authorised live status (NTES / RailAPI) overrides delay & position
    ext = integ.train_status(number)
    if ext:
        sig["external"] = ext
        if ext.get("delay_min") is not None:
            sig["delay"] = int(ext["delay_min"])
            sig["delay_cause"] = "Live provider feed"
        if ext.get("position"):
            sig["progress"]["live_position"] = ext["position"]
    return t, sig, events, rep_hits, rep_boost, rep_delay


# ------------------------------------------------------------------ snapshots
def _write_snapshot(name, payload):
    if IS_VERCEL:
        return  # read-only filesystem on Vercel — compute on demand instead
    os.makedirs(SNAPDIR, exist_ok=True)
    tmp = os.path.join(SNAPDIR, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(SNAPDIR, name))


def _read_snapshot(name, ttl=SNAP_TTL):
    if IS_VERCEL:
        return None
    path = os.path.join(SNAPDIR, name)
    if os.path.exists(path):
        try:
            if time.time() - os.path.getmtime(path) < ttl:
                with open(path) as f:
                    return json.load(f)
        except Exception:
            pass
    return None


def compute_popular(items):
    now = utc_now()
    out = []
    for n in FAV:
        t = TRAIN_BY_NUM.get(n)
        if not t:
            continue
        res = live_signal(n, items=items)
        if not res:
            continue
        t2, sig, _ev, _rep, _rb, _rd = res
        out.append({
            "number": t2["number"], "name": t2["name"], "type": t2["type"],
            "type_label": sig["type_label"],
            "from_name": t2["from_name"], "to_name": t2["to_name"],
            "dep": t2.get("dep"), "arr": t2.get("arr"),
            "occupancy": sig["overall"]["occupancy"], "level": sig["overall"]["level"],
            "delay": sig["delay"], "eta": (sig.get("progress") or {}).get("eta"),
        })
    return out


def refresh_snapshots():
    while True:
        try:
            items = crawler.get_news(limit=60)
            popular = compute_popular(items)
            dash = {
                "now": utc_now().isoformat(),
                "stats": {"trains": len(TRAINS), "stations": len(STATIONS),
                          "news_fresh": bool(crawler.cache["items"])},
                "integrations": integ.active(),
            }
            _write_snapshot("popular.json", popular)
            _write_snapshot("news.json", {"items": items, "live": bool(crawler.cache["items"]),
                                          "fetched_at": utc_now().isoformat()})
            _write_snapshot("dashboard.json", dash)
            print("[RailCrowd] snapshots refreshed", flush=True)
        except Exception as e:  # noqa
            print("[RailCrowd] snapshot refresh error:", e, flush=True)
        time.sleep(240)


_snap_started = threading.Event()


def ensure_snapshots():
    if IS_VERCEL or _snap_started.is_set():
        return
    _snap_started.set()
    t = threading.Thread(target=refresh_snapshots, daemon=True)
    t.start()


# ------------------------------------------------------------------ routes
@app.route("/api/health")
def health():
    return jsonify({"ok": True, "trains": len(TRAINS), "stations": len(STATIONS),
                    "now": utc_now().isoformat(), "integrations": integ.active(),
                    "storage": reports.storage_kind, "vercel": IS_VERCEL,
                    "frontend": len(INDEX_HTML) > 0,
                    "root": ROOT,
                    "request_path": request.path,
                    "script_root": request.script_root})


@app.route("/api/stations/search")
def api_station_search():
    return jsonify(search_stations(request.args.get("q", ""), limit=14))


@app.route("/api/stations/nearby")
def api_station_nearby():
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat/lon required"}), 400
    out = []
    for code, s in STATIONS.items():
        d = math.hypot((s["lon"] - lon) * math.cos(math.radians(23)), s["lat"] - lat) * 111.0
        out.append((d, code))
    out.sort(key=lambda x: x[0])
    return jsonify([{"code": code, "name": STATIONS[code]["name"],
                     "state": STATIONS[code]["state"], "km": round(d, 1)}
                    for d, code in out[:8]])


@app.route("/api/station/<code>")
def api_station(code):
    code = code.upper()
    s = STATIONS.get(code)
    if not s:
        return jsonify({"error": "station not found"}), 404
    deps = trains_from(code, limit=40)
    now = utc_now()
    departures = []
    for h in deps:
        t, stop = h["train"], h["stop"]
        sig = engine.signal(t["number"], now)
        departures.append({
            "number": t["number"], "name": t["name"], "type": t["type"],
            "to_name": t["to_name"], "time": stop.get("dep") or stop.get("arr") or stop.get("time"),
            "occupancy": sig["overall"]["occupancy"], "level": sig["overall"]["level"],
            "delay": sig["delay"],
        })
    weather = integ.weather(s["lat"], s["lon"]) if integ.owm_key else None
    return jsonify({"station": {"code": code, "name": s["name"], "state": s["state"],
                                "zone": s["zone"], "lat": s["lat"], "lon": s["lon"],
                                "category": s.get("category", "")},
                    "departures": departures,
                    "weather": weather,
                    "reports": reports.list(station=code, limit=20)})


@app.route("/api/trains/search")
def api_train_search():
    q = request.args.get("q", "")
    res = []
    for t in search_trains(q, limit=30):
        res.append({"number": t["number"], "name": t["name"], "type": t["type"],
                    "from_name": t["from_name"], "to_name": t["to_name"],
                    "dep": t.get("dep"), "arr": t.get("arr")})
    return jsonify(res)


@app.route("/api/train/<number>")
def api_train(number):
    t = TRAIN_BY_NUM.get(str(number))
    if not t:
        return jsonify({"error": "train not found"}), 404
    res = live_signal(number)
    if not res:
        return jsonify({"error": "train not found"}), 404
    t2, sig, events, rep_hits, rep_boost, rep_delay = res
    return jsonify({"train": t2, "live": sig, "events": events,
                    "reports": rep_hits,
                    "community": {"boost": rep_boost, "delay": rep_delay,
                                  "count": len(rep_hits)},
                    "provider": (sig.get("external") or {}).get("provider", "model")})


@app.route("/api/train/<number>/live")
def api_train_live(number):
    res = live_signal(number)
    if not res:
        return jsonify({"error": "train not found"}), 404
    return jsonify(res[1])


@app.route("/api/popular")
def api_popular():
    if request.args.get("refresh") == "1":
        ensure_snapshots()
        return jsonify(compute_popular(crawler.get_news(limit=60)))
    snap = _read_snapshot("popular.json")
    if snap is not None:
        return jsonify(snap)
    ensure_snapshots()
    return jsonify(compute_popular(crawler.get_news(limit=60)))


@app.route("/api/news")
def api_news():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 40))
    snap = _read_snapshot("news.json")
    if snap is not None:
        items, live, fetched = snap["items"], snap["live"], snap["fetched_at"]
    else:
        ensure_snapshots()
        items = crawler.get_news(limit=max(limit, 60))
        live = bool(crawler.cache["items"])
        fetched = utc_now().isoformat()
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["title"].lower()
                 or ql in i["category"].lower()
                 or any(ql in t["name"].lower() for t in i.get("trains", []))]
    return jsonify({"items": items[:limit], "live": live, "fetched_at": fetched})


@app.route("/api/dashboard")
def api_dashboard():
    snap = _read_snapshot("dashboard.json")
    if snap is not None:
        return jsonify(snap)
    ensure_snapshots()
    return jsonify({
        "now": utc_now().isoformat(),
        "stats": {"trains": len(TRAINS), "stations": len(STATIONS),
                  "news_fresh": bool(crawler.cache["items"])},
        "integrations": integ.active(),
    })


# ------------------------------------------------------------------ community reports
@app.route("/api/reports/types")
def api_report_types():
    return jsonify(REPORT_TYPES)


@app.route("/api/reports", methods=["GET", "POST"])
def api_reports():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        rep, err = reports.add(body.get("type"), body.get("train"),
                               body.get("station"), body.get("message"))
        if err:
            return jsonify({"error": err}), 400
        return jsonify(rep), 201
    return jsonify(reports.list(train=request.args.get("train"),
                                station=request.args.get("station"),
                                limit=int(request.args.get("limit", 50))))


@app.route("/api/reports/<rid>/vote", methods=["POST"])
def api_report_vote(rid):
    v = reports.vote(rid)
    if v is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"votes": v})


# ------------------------------------------------------------------ static
def _index_response():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/")
def index():
    return _index_response()


@app.route("/<path:p>")
def static_files(p):
    # API misses should 404 as JSON, not fall back to the SPA
    if p.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    full = os.path.join(FRONTEND, p)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND, p)
    return _index_response()  # SPA fallback (client-side routing)


# Vercel safety net: if the rewrite ever delivers the path "/api/index",
# still serve the app instead of a 404.
@app.route("/api/index")
def index_alias():
    return _index_response()


@app.route("/api/index/<path:p>")
def static_alias(p):
    return static_files(p)


if __name__ == "__main__":
    ensure_snapshots()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
