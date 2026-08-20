#!/usr/bin/env python3
"""
Build a compact, curated dataset for RailCrowd from public Indian Railways data.

Sources (public / open):
  - trains.json   : GeoJSON of ~5200 Indian Railways trains (number, name, type,
                    from/to, departure/arrival, distance, class flags, route
                    geometry)  -- IndianRailwayOpenReference (public dataset)
  - stations.json : GeoJSON of stations (code, name, state, zone, coordinates)
  - stations_raw  : station master list incl. station category (NSG1..HG3)

Output:
  dataset.json = {
    stations : { CODE: {name, state, zone, lat, lon, category} },
    trains   : [ {number, name, type, zone, from_code, from_name, to_code,
                  to_name, dep, arr, distance, duration_m, classes,
                  route: [[lat,lon],...], stops: [{code,name,lat,lon,time,dist}] } ]
  }
"""
import json, math, re
from collections import defaultdict

import numpy as np
from scipy.spatial import cKDTree

DATA = "/home/user/railcrowd/data"

# ---------------------------------------------------------------- stations
with open(f"{DATA}/stations.json") as f:
    stj = json.load(f)

stations = {}
for feat in stj["features"]:
    p = feat["properties"]
    g = feat.get("geometry")
    if not g or not p.get("code") or not p.get("name"):
        continue
    code = p["code"].strip()
    name = p["name"].strip()
    if code.startswith(("XX", "YY")) or name.startswith(("XX", "YY")):
        continue
    stations[code] = {
        "name": name,
        "state": p.get("state") or "",
        "zone": p.get("zone") or "",
        "lon": g["coordinates"][0],
        "lat": g["coordinates"][1],
        "category": "",
    }

# merge category from the master list
try:
    with open(f"{DATA}/stations_raw.txt") as f:
        raw = json.load(f)
    for r in raw:
        code = (r.get("Station Code") or "").strip()
        if code in stations:
            stations[code]["category"] = (r.get("Station Category") or "").strip()
            stations[code]["division"] = (r.get("Division") or "").strip()
except Exception as e:  # noqa
    print("category merge skipped:", e)

# ---------------------------------------------------------------- kd-tree for snapping
codes = list(stations.keys())
MID_LAT = np.radians(23.0)
lons = np.array([stations[c]["lon"] for c in codes], dtype=float)
lats = np.array([stations[c]["lat"] for c in codes], dtype=float)
X = np.stack([lons * math.cos(MID_LAT), lats], axis=1)  # approx equirectangular
tree = cKDTree(X)


def nearest_station(lon, lat, max_km=45.0):
    q = np.array([lon * math.cos(MID_LAT), lat])
    d, i = tree.query(q, k=1)
    km = d * 111.0
    if km > max_km:
        return None
    return codes[i]


def haversine_km(a, b):
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


CLASS_MAP = [
    ("sleeper", "SL"),
    ("third_ac", "3A"),
    ("second_ac", "2A"),
    ("first_ac", "1A"),
    ("chair_car", "CC"),
]
PREMIUM_TYPES = {"Raj", "Shtb", "Drnt", "SKr", "JShtb", "GR", "VB"}


def fmt_t(t):
    if not t:
        return ""
    t = str(t)
    m = re.match(r"(\d{1,2}):(\d{2})", t)
    if m:
        return f"{int(m.group(1)) % 24:02d}:{m.group(2)}"
    return t[:5]


def to_minutes(t):
    m = re.match(r"(\d{1,2}):(\d{2})", str(t or ""))
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


with open(f"{DATA}/trains.json") as f:
    trj = json.load(f)

trains = []
skipped = 0
for feat in trj["features"]:
    p = feat["properties"]
    g = feat.get("geometry")
    if not g or not g.get("coordinates"):
        skipped += 1
        continue
    coords = g["coordinates"]  # [lon, lat]
    if len(coords) < 2:
        skipped += 1
        continue

    number = str(p.get("number") or "").strip()
    if not number:
        skipped += 1
        continue

    classes = [label for flag, label in CLASS_MAP if p.get(flag)]
    if not classes:
        classes = ["2S"] if p.get("type") in ("Pass", "MEMU", "DEMU", "Hyd") else ["SL", "3A"]

    dep_m = to_minutes(p.get("departure"))
    arr_m = to_minutes(p.get("arrival"))
    duration = int(p.get("duration_m") or 0) or None
    if duration is None and dep_m is not None and arr_m is not None:
        duration = (arr_m - dep_m) % (24 * 60)

    # ---- snap route to stations
    snap_indices = []
    snap_stations = []
    for j, (lon, lat) in enumerate(coords):
        code = nearest_station(lon, lat)
        if code:
            snap_indices.append(j)
            snap_stations.append(code)

    # dedupe consecutive
    seen = set()
    stops_ordered = []
    for code in snap_stations:
        if not stops_ordered or code != stops_ordered[-1]:
            stops_ordered.append(code)

    from_code = str(p.get("from_station_code") or "").strip()
    to_code = str(p.get("to_station_code") or "").strip()

    # force endpoints
    if stops_ordered and from_code and stops_ordered[0] != from_code:
        if from_code in stations:
            stops_ordered = [from_code] + stops_ordered
    if stops_ordered and to_code and stops_ordered[-1] != to_code:
        if to_code in stations:
            stops_ordered.append(to_code)

    # ---- cumulative distance along polyline
    cum = [0.0]
    for a, b in zip(coords, coords[1:]):
        cum.append(cum[-1] + haversine_km(a, b))
    total_km = cum[-1] or 1.0

    # ---- interpolate time for each stop (find nearest polyline point per stop)
    # map each snapped stop back to a route fraction
    stops = []
    for code in stops_ordered[:28]:
        st = stations.get(code)
        if not st:
            continue
        # find route fraction: use the nearest route point to this station
        lon, lat = st["lon"], st["lat"]
        best_j, best_d = 0, 1e18
        for j, (clon, clat) in enumerate(coords):
            d = (clon - lon) ** 2 + (clat - lat) ** 2
            if d < best_d:
                best_d, best_j = d, j
        frac = cum[best_j] / total_km
        if duration and dep_m is not None:
            t = (dep_m + frac * duration) % (24 * 60)
            tstr = f"{int(t // 60) % 24:02d}:{int(t % 60):02d}"
        else:
            tstr = ""
        stops.append({
            "code": code,
            "name": st["name"],
            "lat": round(st["lat"], 4),
            "lon": round(st["lon"], 4),
            "time": tstr,
            "dist": int(frac * int(p.get("distance") or 0)),
        })

    # decimate route polyline for compactness
    step = max(1, len(coords) // 36)
    route = [[round(c[1], 4), round(c[0], 4)] for c in coords[::step]]  # [lat, lon]
    if route[-1] != [round(coords[-1][1], 4), round(coords[-1][0], 4)]:
        route.append([round(coords[-1][1], 4), round(coords[-1][0], 4)])

    trains.append({
        "number": number,
        "name": (p.get("name") or "").strip().title(),
        "type": p.get("type") or "",
        "zone": p.get("zone") or "",
        "from_code": from_code,
        "from_name": (p.get("from_station_name") or "").strip().title(),
        "to_code": to_code,
        "to_name": (p.get("to_station_name") or "").strip().title(),
        "dep": fmt_t(p.get("departure")),
        "arr": fmt_t(p.get("arrival")),
        "distance": int(p.get("distance") or 0),
        "duration_m": duration,
        "classes": classes,
        "route": route,
        "stops": stops,
    })

# sort by number
trains.sort(key=lambda t: t["number"])

out = {"stations": stations, "trains": trains}
with open(f"{DATA}/dataset.json", "w") as f:
    json.dump(out, f, separators=(",", ":"))

n_stops = sum(len(t["stops"]) for t in trains)
print(f"stations: {len(stations)}")
print(f"trains:   {len(trains)} (skipped {skipped})")
print(f"avg stops/train: {n_stops / max(1, len(trains)):.1f}")

# sanity: some famous trains present?
def show(num):
    for t in trains:
        if t["number"] == num:
            print("FOUND", t["number"], t["name"], t["from_name"], "->", t["to_name"],
                  "| classes", t["classes"], "| stops", len(t["stops"]), "| route pts", len(t["route"]))
            return
    print("MISSING", num)

for n in ["12951", "12952", "12001", "12259", "12627", "12301", "22901", "20901", "12430"]:
    show(n)
# search vande bharat / tejas / garib rath
kw = re.compile(r"VANDE|TEJAS|GARIB RATH|HUMSAFAR|ANTYODAYA", re.I)
prem = [t for t in trains if kw.search(t["name"]) or t["type"] in PREMIUM_TYPES]
print("premium-ish trains:", len(prem))
for t in prem[:25]:
    print("  ", t["number"], t["name"][:40], "|", t["type"])
