// Node smoke test for the map code embedded in index.html
const fs = require("fs");
let src = fs.readFileSync("/tmp/app_full.js", "utf8");
src = src.replace(/route\(\);\s*$/, "");

const test = `
;__T = (()=>{
  console.log("INDIA_OUTLINE rings:", INDIA_OUTLINE.length);
  console.log("INDIA_STATES:", INDIA_STATES.length, "|", INDIA_STATES.map(s=>s.n).slice(0,8).join(", "));
  console.log("INDIA_BOUNDS:", JSON.stringify(INDIA_BOUNDS));
  const ds = JSON.parse(require("fs").readFileSync("/home/user/railcrowd/data/dataset.json","utf8"));
  const t = ds.trains.find(x=>x.number==="19005");
  console.log("train:", t.number, t.name, "| stops:", t.stops.length, "| route pts:", t.route.length);
  const rr = t.route;
  const P = makeProj(boundsOf([rr]));
  console.log("route-focus proj first pt:", P.Px(rr[0][1]).toFixed(1), P.Py(rr[0][0]).toFixed(1));
  const d = ringPath(INDIA_OUTLINE, P);
  console.log("outline path len:", d.length, "head:", d.slice(0,48));
  const PI = makeProj(INDIA_BOUNDS);
  console.log("india proj: Kashmir(37N) y =", PI.Py(37.0).toFixed(1), "/ MAPH", MAPH, "| Kanyakumari(8N) y =", PI.Py(8.0).toFixed(1));
  for(const s of INDIA_STATES){ ringPath(s.r, PI); }
  console.log("all state paths OK");
  const b = boundsOf([rr]);
  const w=(b.maxLon-b.minLon)*Math.cos((b.minLat+b.maxLat)/2*Math.PI/180);
  console.log("route span:", (b.maxLat-b.minLat).toFixed(2)+" lat x "+(b.maxLon-b.minLon).toFixed(2)+" lon -> focus scale", Math.min(1000*0.82/w, 660*0.82/(b.maxLat-b.minLat)).toFixed(1));
  const box = { innerHTML:"" };
  global.$ = ()=>box;
  global.esc = window.esc || ((s)=>String(s??""));
  drawMap(t, {fraction:0.4}, t.stops, "route");
  console.log("drawMap route-mode svg len:", box.innerHTML.length);
  drawMap(t, {fraction:0.4}, t.stops, "india");
  console.log("drawMap india-mode svg len:", box.innerHTML.length);
  const m = box.innerHTML.match(/<polyline class="route" points="([^"]*)"/);
  console.log("route polyline pts sample:", m? m[1].slice(0,50) : "NONE");
  return "OK";
})();
console.log("RESULT:", __T);
`;
src += test;

global.window = { addEventListener: ()=>{} };
global.document = { querySelectorAll: ()=>[], addEventListener: ()=>{}, getElementById: ()=>({}) };
global.location = { hash: "" };
global.fetch = ()=>{ throw new Error("no fetch"); };
eval(src);
