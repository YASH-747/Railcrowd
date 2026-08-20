#!/usr/bin/env python3
"""
Build a compact, embeddable vector India map (with full Kashmir) for the frontend.

Inputs:
  - india_composite.geojson : datameet composite country outline (Survey-of-India
                              boundary incl. full Jammu & Kashmir / Ladakh extent)
  - india_gh.geojson        : state boundaries (36 states incl. Telangana)

Output: india_map.js  (defines INDIA_OUTLINE and INDIA_STATES as JS consts)
Simplified with Douglas-Peucker; coordinates in [lat, lon] for direct SVG use.
"""
import json
import math

DATA = "/home/user/railcrowd/data"


def dp(points, eps):
    """Douglas-Peucker on a list of (x,y) tuples."""
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    # max perpendicular distance
    dx, dy = end[0] - start[0], end[1] - start[1]
    denom = (dx * dx + dy * dy) or 1.0
    max_d, max_i = 0.0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        d = abs(dy * x - dx * y + end[0] * start[1] - end[1] * start[0]) / math.sqrt(denom)
        if d > max_d:
            max_d, max_i = d, i
    if max_d > eps:
        left = dp(points[: max_i + 1], eps)
        right = dp(points[max_i:], eps)
        return left[:-1] + right
    return [start, end]


def simplify_ring(ring, eps):
    pts = [(p[0], p[1]) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]  # ring is closed; strip duplicate before DP
    out = dp(pts, eps)
    # close ring
    if not out or out[0] != out[-1]:
        out.append(out[0])
    return out


def ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def parse_mpoly(coords, eps):
    """coords: MultiPolygon coordinates list -> list of rings [ [lat,lon], ... ]"""
    rings = []
    for poly in coords:
        outer = simplify_ring(poly[0], eps)
        if ring_area(outer) > 0.01:
            rings.append([[round(lat, 4), round(lon, 4)] for lon, lat in outer])
    return rings


def parse_polygon(coords, eps):
    return parse_mpoly([coords], eps)


# ---------------------------------------------------------------- outline
with open(f"{DATA}/india_composite.geojson") as f:
    comp = json.load(f)
feat = comp["features"][0]
g = feat["geometry"]
outline_rings = parse_mpoly(g["coordinates"], 0.03)

# ---------------------------------------------------------------- states
with open(f"{DATA}/india_gh.geojson") as f:
    gh = json.load(f)
states = []
for f in gh["features"]:
    name = f["properties"].get("NAME_1") or "Unknown"
    geom = f["geometry"]
    coords = geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        rings = parse_mpoly(coords, 0.04)
    else:
        rings = parse_polygon(coords, 0.04)
    if rings:
        states.append({"n": name, "r": rings})

# count total points
tot_outline = sum(len(r) for r in outline_rings)
tot_states = sum(len(r) for s in states for r in s["r"])
print(f"outline rings={len(outline_rings)} pts={tot_outline}")
print(f"states={len(states)} pts={tot_states}")

# ---------------------------------------------------------------- emit JS
def ring_js(ring):
    return "[" + ",".join(f"[{a},{b}]" for a, b in ring) + "]"


js = ["// Auto-generated vector India map (full Kashmir) — do not edit by hand.",
      "const INDIA_OUTLINE = ["]
js += [("    " + ring_js(r) + ",") for r in outline_rings]
js.append("];")
js.append("const INDIA_STATES = [")
for s in states:
    js.append(f"  {{n:{json.dumps(s['n'])}, r:[")
    for r in s["r"]:
        js.append("    " + ring_js(r) + ",")
    js.append("  ]},")
js.append("];")
js.append("")

with open(f"{DATA}/india_map.js", "w") as f:
    f.write("\n".join(js))
print("wrote india_map.js", len("\n".join(js)) // 1024, "KB")
