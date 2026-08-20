#!/usr/bin/env python3
"""Splice the generated vector India map + new auto-focus renderer into index.html."""
import re

FRONT = "/home/user/railcrowd/frontend/index.html"
MAPJS = "/home/user/railcrowd/data/india_map.js"

html = open(FRONT).read()
mapjs = open(MAPJS).read().rstrip("\n")

# ---------------------------------------------------------------- 1) CSS
old_css = """  .mapbox{background:#0b1322;border:1px solid var(--border);border-radius:var(--radius);padding:10px}
  .mapbox svg{width:100%;height:auto;display:block}
  .india{fill:#15233d;stroke:#2c3f63;stroke-width:1}
  .route{fill:none;stroke:var(--accent);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round;opacity:.9}
  .stop{fill:var(--sky);stroke:#0b1322;stroke-width:1}"""
new_css = """  .mapwrap{position:relative}
  .mapbox{background:#0b1322;border:1px solid var(--border);border-radius:var(--radius);padding:10px}
  .mapbox svg{width:100%;height:auto;display:block}
  .mapctrl{position:absolute;top:14px;right:14px;display:flex;gap:6px;z-index:5}
  .mc{background:rgba(13,20,36,.88);border:1px solid var(--border);color:var(--muted);font-size:11.5px;font-weight:700;padding:6px 11px;border-radius:8px;cursor:pointer;backdrop-filter:blur(4px)}
  .mc:hover{color:var(--text)}
  .mc.on{background:var(--accent);color:#1a1206;border-color:var(--accent)}
  .state{fill:#0f1a2e;stroke:#223653;stroke-width:0.7;stroke-linejoin:round}
  .outline{fill:none;stroke:#48648f;stroke-width:1.7;stroke-linejoin:round}
  .route{fill:none;stroke:var(--accent);stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round;opacity:.95}
  .route-glow{fill:none;stroke:rgba(255,122,24,.22);stroke-width:8;stroke-linejoin:round;stroke-linecap:round}
  .stop{fill:var(--sky);stroke:#0b1322;stroke-width:1.2}
  .cur-ring{fill:none;stroke:var(--accent);stroke-width:2}"""
assert old_css in html, "css block not found"
html = html.replace(old_css, new_css, 1)

# ---------------------------------------------------------------- 2) India data block
start_marker = "/* ============================== India outline (simplified) ============ */"
end_marker = "/* ============================== helpers =============================== */"
i0 = html.index(start_marker)
i1 = html.index(end_marker)

block = """/* ============================== Vector India map (full Kashmir) ====== */
""" + mapjs + """

const MAPW = 1000, MAPH = 660;
let mapMode = "route";
let mapState = null;

function boundsOf(rings){
  let minLat=1e9, maxLat=-1e9, minLon=1e9, maxLon=-1e9;
  for(const r of rings){ for(let i=0;i<r.length;i++){ const la=r[i][0], lo=r[i][1];
    if(la<minLat)minLat=la; if(la>maxLat)maxLat=la;
    if(lo<minLon)minLon=lo; if(lo>maxLon)maxLon=lo; } }
  return {minLat, maxLat, minLon, maxLon};
}
const INDIA_BOUNDS = boundsOf(INDIA_OUTLINE);

function makeProj(b){
  const midLat=(b.minLat+b.maxLat)/2, cos=Math.max(0.3, Math.cos(midLat*Math.PI/180));
  const w=Math.max((b.maxLon-b.minLon)*cos, 0.12), h=Math.max(b.maxLat-b.minLat, 0.12);
  const scale=Math.min(MAPW*0.82/w, MAPH*0.82/h);
  const cx=(b.minLon+b.maxLon)/2, cy=(b.minLat+b.maxLat)/2;
  return {
    Px: lo => (lo-cx)*cos*scale + MAPW/2,
    Py: la => (cy-la)*scale + MAPH/2,
  };
}
function ringPath(rings, P){
  let d="";
  for(const r of rings){
    let s="";
    for(let i=0;i<r.length;i++) s += (i?",":"") + P.Px(r[i][1]).toFixed(1)+","+P.Py(r[i][0]).toFixed(1);
    d += "M"+s+"Z";
  }
  return d;
}

"""
html = html[:i0] + block + html[i1:]

# ---------------------------------------------------------------- 3) drawMap rewrite
dm_start = "/* ============================== MAP =================================== */"
dm_end = "function drawSpark(series){"
i0 = html.index(dm_start)
i1 = html.index(dm_end)

new_drawmap = """/* ============================== MAP =================================== */
function drawMap(t, pr, stops, mode){
  const box = $("mapbox"); if(!box) return;
  mapState = {t, pr, stops};
  if(mode) mapMode = mode;
  const route = (t.route && t.route.length>1)? t.route : stops.map(s=>[s.lat,s.lon]);
  const b = mapMode==="india" ? INDIA_BOUNDS : boundsOf([route]);
  const P = makeProj(b);
  const statePaths = INDIA_STATES.map(s=>`<path class="state" d="${ringPath(s.r,P)}"/>`).join("");
  const outlinePath = `<path class="outline" d="${ringPath(INDIA_OUTLINE,P)}"/>`;
  const routePts = route.map(p=>`${P.Px(p[1]).toFixed(1)},${P.Py(p[0]).toFixed(1)}`).join(" ");
  let cur = "";
  if(pr.fraction!=null && route.length>1){
    const f = Math.max(0, Math.min(1, pr.fraction));
    const i = Math.floor(f*(route.length-1));
    const j = Math.min(route.length-1, i+1);
    const la = route[i][0]+(route[j][0]-route[i][0])*(f*(route.length-1)-i);
    const lo = route[i][1]+(route[j][1]-route[i][1])*(f*(route.length-1)-i);
    cur = `<g><circle class="cur-ring" cx="${P.Px(lo).toFixed(1)}" cy="${P.Py(la).toFixed(1)}" r="9">
      <animate attributeName="r" values="5;14;5" dur="2.4s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.9;0.1;0.9" dur="2.4s" repeatCount="indefinite"/></circle>
      <circle class="cur" cx="${P.Px(lo).toFixed(1)}" cy="${P.Py(la).toFixed(1)}" r="5"/></g>`;
  }
  const shown = stops.length>30? stops.filter((_,i)=> i%2===0 || i===stops.length-1) : stops;
  const dots = shown.map(s=>{
    const e = s.code===t.from_code||s.code===t.to_code;
    return `<circle class="stop ${e?'end':''}" cx="${P.Px(s.lon).toFixed(1)}" cy="${P.Py(s.lat).toFixed(1)}" r="${e?4.5:2.8}"/>`;
  }).join("");
  const labels = [stops[0], stops[stops.length-1]].filter(Boolean).map(s=>
    `<text class="maplabel" x="${P.Px(s.lon).toFixed(1)}" y="${(P.Py(s.lat)-9).toFixed(1)}">${esc(s.name.split(" ").slice(0,2).join(" "))}</text>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${MAPW} ${MAPH}" xmlns="http://www.w3.org/2000/svg">
    ${statePaths}
    ${outlinePath}
    ${routePts?`<polyline class="route-glow" points="${routePts}"/><polyline class="route" points="${routePts}"/>`:""}
    ${dots} ${labels} ${cur}
  </svg>`;
  document.querySelectorAll(".mc").forEach(btn=> btn.classList.toggle("on", btn.dataset.m===mapMode));
}
function setMapMode(m){ if(mapState) drawMap(mapState.t, mapState.pr, mapState.stops, m); }

"""
html = html[:i0] + new_drawmap + html[i1:]

# ---------------------------------------------------------------- 4) map card HTML
old_card = """    <div class="mapbox" id="mapbox"></div>"""
new_card = """    <div class="mapwrap">
      <div class="mapctrl">
        <button class="mc on" data-m="route" onclick="setMapMode('route')">Focus route</button>
        <button class="mc" data-m="india" onclick="setMapMode('india')">India view</button>
      </div>
      <div class="mapbox" id="mapbox"></div>
    </div>"""
assert old_card in html, "map card not found"
html = html.replace(old_card, new_card, 1)

# caption
old_cap = '<div class="cap">India outline + train route · circles are calling stations</div>'
new_cap = '<div class="cap">Vector India map (full Kashmir) · auto-zoomed to this train\'s route · circles = calling stations</div>'
assert old_cap in html, "caption not found"
html = html.replace(old_cap, new_cap, 1)

# drawMap call -> reset to route focus on each train open
old_call = "drawMap(t, pr, stops);"
assert old_call in html, "drawMap call not found"
html = html.replace(old_call, "drawMap(t, pr, stops, \"route\");", 1)

open(FRONT, "w").write(html)
print("spliced OK — new size", len(html)//1024, "KB")
