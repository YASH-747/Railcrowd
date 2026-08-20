#!/usr/bin/env python3
"""Remove the media (photo/video) and seat-chart features from index.html."""
import sys

P = "/home/user/railcrowd/frontend/index.html"
html = open(P).read()
orig = html


def rep(old, new, n=1):
    global html
    c = html.count(old)
    if c != n:
        print(f"FAIL ({c}x, want {n}): {old[:70]!r}")
        sys.exit(1)
    html = html.replace(old, new, 1)


# ---------------------------------------------------------------- CSS: seat chart
rep("""  .seatbtn{background:var(--panel2);border:1px solid var(--border);color:var(--sky);font-size:12px;font-weight:700;
    padding:6px 11px;border-radius:8px;cursor:pointer;margin-top:12px}
  .seatbtn:hover{border-color:var(--sky)}
  .seatchart{margin-top:12px}
  .seat-status{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:800;padding:4px 10px;border-radius:8px;margin-bottom:10px}
  .ss-avail{color:var(--low);background:rgba(34,197,94,.12)}
  .ss-rac{color:var(--high);background:rgba(245,158,11,.12)}
  .ss-wl{color:var(--crit);background:rgba(239,68,68,.12)}
  .coachblock{border:1px solid var(--border);border-radius:10px;padding:10px;margin-bottom:10px}
  .coachblock .cb-h{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);margin-bottom:8px;flex-wrap:wrap}
  .coachblock .cb-h b{color:var(--text);font-size:13px}
  .seats{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:4px}
  .seats.cc-layout{grid-template-columns:repeat(5,minmax(0,1fr))}
  .seat{height:26px;border-radius:5px;display:grid;place-items:center;font-size:9.5px;font-weight:800;color:#0b1220;cursor:default;position:relative}
  .seat.vacant{background:#1f9d55;color:#063018}
  .seat.booked{background:#e5484d;color:#3d0a0c}
  .seat.rac{background:#f59e0b;color:#3a2500}
  .seat .st{position:absolute;top:0;right:3px;font-size:6.5px;opacity:.7}
  .legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:var(--muted);margin-bottom:10px}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}
""", "", 1)

# ---------------------------------------------------------------- CSS: media
rep("""  /* media in reports + uploads */
  .mstrip{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
  .mthumb{width:120px;height:90px;object-fit:cover;border-radius:10px;border:1px solid var(--border);background:#0b1322;display:block}
  video.mthumb{background:#000}
  .mfile{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted);border:1px solid var(--border);border-radius:8px;padding:6px 10px}
  .mfile:hover{color:var(--text)}
  .previewgrid{display:flex;flex-wrap:wrap;gap:8px;grid-column:1/-1;margin-top:4px}
  .previewgrid .mthumb{width:96px;height:72px}
  .previewgrid .pv{position:relative}
  .previewgrid .rm{position:absolute;top:4px;right:4px;background:rgba(10,15,30,.8);color:#fff;border:0;border-radius:6px;font-size:11px;cursor:pointer;padding:2px 6px}
  .filebtn{grid-column:1/-1;display:inline-flex;align-items:center;gap:8px;cursor:pointer;color:var(--muted);font-size:13px;font-weight:700;padding:10px 14px;border:1px dashed var(--border);border-radius:10px}
  .filebtn:hover{color:var(--text);border-color:var(--sky)}
  .filebtn input{display:none}
""", "", 1)

# ---------------------------------------------------------------- livecard seats-free
rep('        <span class="k">Seats free (est.)</span><span class="v">${live.classes.reduce((a,c)=>a+c.seats_available,0)}</span>\n', "", 1)

# ---------------------------------------------------------------- class section header
rep("""    <h2>Crowding by class &amp; seat charts</h2>
    <div class="cap" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">
      <span>Per-class occupancy · per-coach heat · IRCTC-style seat chart with seat numbers</span>
      <span style="margin-left:auto;display:flex;align-items:center;gap:6px">
        <label for="seat-date" style="color:var(--muted);font-size:12.5px">Travel date:</label>
        <input type="date" id="seat-date" style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:6px 8px;font-size:12.5px">
      </span>
    </div>""",
"""    <h2>Crowding by class</h2>
    <div class="cap">Per-class occupancy &amp; per-coach heat — modelled estimate (no live seat data is public)</div>""", 1)

# ---------------------------------------------------------------- class card footer
rep("""          <div class="sub" style="margin-top:8px">~${c.seats_available} seats free · ${c.coaches.length} coaches</div>
          <button class="seatbtn" data-code="${esc(c.code)}" onclick="toggleSeats(this,'${esc(number)}','${esc(c.code)}')">💺 Show seat chart</button>
          <div class="seatchart" id="seats-${esc(c.code)}" style="display:none"></div>""",
"""          <div class="sub" style="margin-top:8px">${c.coaches.length} coaches · per-coach heat above</div>""", 1)

# ---------------------------------------------------------------- travel-date init block
rep("""  // travel-date input for seat charts (default today, IRCTC-style +60 days)
  const sd = $("seat-date");
  if(sd){
    const now = new Date();
    sd.value = now.toISOString().slice(0,10);
    const max = new Date(Date.now()+60*86400000).toISOString().slice(0,10);
    sd.min = now.toISOString().slice(0,10);
    sd.max = max;
  }

""", "", 1)

# ---------------------------------------------------------------- SEAT CHART JS section
i0 = html.index("/* ============================== SEAT CHART ============================ */")
i1 = html.index("/* ============================== COMMUNITY REPORTS ===================== */")
html = html[:i0] + html[i1:]

# ---------------------------------------------------------------- renderMedia function
i0 = html.index("function renderMedia(items){")
i1 = html.index("function renderReportList(reports, emptyMsg){")
html = html[:i0] + html[i1:]

# ---------------------------------------------------------------- media line in report list
rep('      ${renderMedia(r.media)}\n', "", 1)

# ---------------------------------------------------------------- report form caption
rep('<div class="cap">Community-sourced, no login — text + photos/videos. Files go to Cloudflare R2 (or local storage) and feed the crowding model.</div>',
    '<div class="cap">Community-sourced, no login — describe what you saw; your report feeds the crowding model.</div>', 1)

# ---------------------------------------------------------------- file picker + preview
rep("""      <label class="filebtn">📷 Add photos / videos
        <input type="file" id="rpt-files" accept="image/*,video/*,audio/*" multiple onchange="previewFiles()">
      </label>
      <div class="previewgrid" id="rpt-preview"></div>
""", "", 1)

# ---------------------------------------------------------------- previewFiles + rmFile
i0 = html.index("function previewFiles(){")
i1 = html.index("async function submitReport(defTrain, defStation){")
html = html[:i0] + html[i1:]

# ---------------------------------------------------------------- submitReport → JSON only
rep("""  const btn = $("rpt-submit"); if(btn) btn.disabled = true;
  const fileInput = $("rpt-files");
  const files = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
  try{
    let r, j;
    if(files.length){
      const fd = new FormData();
      fd.append("type", type); fd.append("train", train);
      fd.append("station", station); fd.append("message", message);
      files.forEach(f=> fd.append("file", f));
      r = await fetch("/api/reports", {method:"POST", body: fd});
      j = await r.json().catch(()=>({}));
    } else {
      r = await fetch("/api/reports", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({type, train, station, message})});
      j = await r.json().catch(()=>({}));
    }""",
"""  const btn = $("rpt-submit"); if(btn) btn.disabled = true;
  try{
    const r = await fetch("/api/reports", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({type, train, station, message})});
    const j = await r.json().catch(()=>({}));""", 1)

open(P, "w").write(html)
print("frontend cleaned OK —", len(html) // 1024, "KB (was", len(orig) // 1024, "KB)")
