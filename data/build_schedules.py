#!/usr/bin/env python3
"""
Rebuild ACCURATE train stops from the real schedule database.

Source: schedules.json (417k rows) — every station a train passes, with
arrival/departure/day. A train actually HALTS where dwell > 0 (arrival !=
departure) or at its origin/terminus. Express trains therefore yield their true
stopping stations (verified: 12301 → HWH, DHN, PNME, GAYA, MGS, ALD, CNB, NDLS).

For all-halting trains (passenger/MEMU) with no dwell recorded, we keep every
row. Stops are re-mapped to our station coordinates, distances are recomputed
by haversine, and each train's route polyline is rebuilt THROUGH its stops so
the map and the dots align exactly.

Output: dataset.json (stops replaced; trains absent from the schedule DB keep
their previous heuristic stops).
"""
import json
import math
import os
import re

DATA = "/home/user/railcrowd/data"
SCHED_URL = ("https://raw.githubusercontent.com/Spin1234/"
             "IndianRailwayOpenReference.github.io/main/schedules.json")
HALTING_TYPES = {"Pass", "MEMU", "DEMU", "Hyd", "Klkt"}


def hav(a, b):
    lon1, lat1 = math.radians(a["lon"]), math.radians(a["lat"])
    lon2, lat2 = math.radians(b["lon"]), math.radians(b["lat"])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def to_min(t):
    m = re.match(r"(\d{1,2}):(\d{2})", (t or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def fmt(t):
    m = to_min(t)
    return f"{m // 60:02d}:{m % 60:02d}" if m is not None else None


ds = json.load(open(f"{DATA}/dataset.json"))
stations = ds["stations"]
trains = ds["trains"]

if not os.path.exists(f"{DATA}/schedules.json"):
    print("[build_schedules] schedules.json not found — downloading source (~82 MB) …", flush=True)
    import urllib.request
    urllib.request.urlretrieve(SCHED_URL, f"{DATA}/schedules.json")
sched = json.load(open(f"{DATA}/schedules.json"))

# group schedule rows by train number
by_num = {}
for r in sched:
    n = r["train_number"]
    by_num.setdefault(n, []).append(r)

updated = 0
missing = 0
for t in trains:
    num = t["number"]
    rows = by_num.get(num)
    if not rows:
        missing += 1
        continue
    def row_min(r):
        v = to_min(r["departure"]) if r["departure"] not in (None, "None") else to_min(r["arrival"])
        return v if v is not None else 0
    rows = sorted(rows, key=lambda r: ((r.get("day") or 1), row_min(r)))
    # halt detection: dwell > 0, or origin/terminus
    def is_stop(r):
        if r["arrival"] in (None, "None") or r["departure"] in (None, "None"):
            return True
        return r["arrival"] != r["departure"]
    stops = [r for r in rows if is_stop(r)]
    if len(stops) < 3:
        stops = rows  # all-halting train (passenger-like)

    # map to coords + build stop list (dedup consecutive same code)
    out_stops = []
    prev = None
    prev_code = None
    dist_acc = 0.0
    for r in stops:
        code = r["station_code"]
        st = stations.get(code)
        if not st:
            continue
        if prev_code == code:
            continue
        if prev is not None:
            dist_acc += hav(prev, st)
        out_stops.append({
            "code": code, "name": st["name"],
            "lat": round(st["lat"], 4), "lon": round(st["lon"], 4),
            "arr": fmt(r["arrival"]), "dep": fmt(r["departure"]),
            "day": r.get("day") or 1,
            "time": fmt(r["departure"]) or fmt(r["arrival"]),  # canonical display time
            "dist": int(round(dist_acc)),
        })
        prev = st
        prev_code = code
    if len(out_stops) < 2:
        missing += 1
        continue

    t["stops"] = out_stops
    t["route"] = [[s["lat"], s["lon"]] for s in out_stops]
    first, last = out_stops[0], out_stops[-1]
    t["from_code"], t["from_name"] = first["code"], first["name"]
    t["to_code"], t["to_name"] = last["code"], last["name"]
    t["dep"] = first["dep"] or first["arr"]
    t["arr"] = last["arr"] or last["dep"]
    t["distance"] = int(round(dist_acc))
    # duration across days
    d0 = (first["day"] - 1) * 1440 + (to_min(first["dep"] or first["arr"]) or 0)
    d1 = (last["day"] - 1) * 1440 + (to_min(last["arr"] or last["dep"]) or 0)
    t["duration_m"] = max(1, d1 - d0)
    updated += 1

json.dump(ds, open(f"{DATA}/dataset.json", "w"), separators=(",", ":"))
print(f"trains updated with real schedule stops: {updated}")
print(f"trains without schedule data (kept heuristic/premium): {missing}")
print(f"total trains: {len(trains)}")

# spot checks
for n in ["12301", "12302", "12951", "19005", "20901", "12627", "22435"]:
    t = next((x for x in trains if x["number"] == n), None)
    if t:
        codes = [s["code"] for s in t["stops"]]
        print(f"  {n} {t['name'][:34]:36} dep {t['dep']} arr {t['arr']} stops[{len(codes)}]: {' → '.join(codes)}")
