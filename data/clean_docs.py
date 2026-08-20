#!/usr/bin/env python3
"""Remove media/seatmap/R2 references from DOCUMENTATION.md (after feature removal)."""
import sys

P = "/home/user/railcrowd/DOCUMENTATION.md"
s = open(P).read()


def rep(old, new, n=1):
    global s
    c = s.count(old)
    if c != n:
        print(f"FAIL ({c}x, want {n}): {old[:80]!r}")
        sys.exit(1)
    s = s.replace(old, new, 1)


rep("every external dependency (live APIs, Cloudflare R2, news RSS)",
    "every external dependency (live APIs, news RSS)")
rep("see [`requirements.txt`](requirements.txt) (`flask`, `numpy`, `scipy`, `boto3`, `requests`).",
    "see [`requirements.txt`](requirements.txt) (`flask`, `numpy`, `scipy`, `requests`).")
rep("""│   ├── media.py              # photo/video storage (Cloudflare R2 → local fallback)
│   ├── seatmap.py            # IRCTC-style seat charts (seat numbers, AVAILABLE/RAC/WL)
""", "")
rep("│   ├── integrations.py       # optional live APIs (NTES/IRCTC/RailAPI/OpenWeather)",
    "│   ├── integrations.py       # optional live APIs (NTES/IRCTC/RailAPI/OpenWeather)")
rep("""    ├── dataset.json          # 5,207 trains + 8,697 stations (compiled)
    ├── reports.json          # community reports (created at runtime)
    ├── media.json            # media metadata (created at runtime)
    ├── media/                # uploaded files when using LOCAL storage
""", """    ├── dataset.json          # 5,023 trains + 8,697 stations (compiled, audited)
    ├── reports.json          # community reports (created at runtime)
""")
rep("pip install flask numpy scipy boto3     # boto3 optional (only for Cloudflare R2)",
    "pip install -r requirements.txt")
rep("cp .env.example .env                    # optional — add keys for live data / R2",
    "cp .env.example .env                    # optional — add keys for live data")
rep("""| `GOOGLE_MAPS_API_KEY` | integrations | Geocoding / static maps (reserved) |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | media | Cloudflare R2 object storage for uploads |
| `R2_PUBLIC_BASE` | media | Optional public r2.dev / custom domain for direct file links |
| `MAX_UPLOAD_MB` | media | Per-file upload cap (default 40) |
| `PORT` | app | HTTP port (default 5000) |

`GET /api/health` returns `integrations` (list of active providers) and the startup log prints
which media backend is in use.""",
"""| `GOOGLE_MAPS_API_KEY` | integrations | Geocoding / static maps (reserved) |
| `PORT` | app | HTTP port (default 5000) |

`GET /api/health` returns `integrations` (list of active providers).""")

rep("""| `_attach via media.attach` | Enriches report lists with their media |
""", "")
rep("""| `/api/train/<number>/seats?class=&date=` | GET | **IRCTC-style seat chart** (seat numbers, AVAILABLE/RAC/WL) |
""", "")
rep("""| `/api/reports/<rid>/media` | GET/POST | List media for a report / attach a file |
""", "")
rep("""| `/api/media/<mid>` | GET | Serve/redirect a media file |
""", "")

# ---------------------------------------------------------------- remove sections 4.5 (media) + 4.7 (seatmap)
i0 = s.index("### 4.5 `media.py` — photo/video storage")
i1 = s.index("### 4.6 `integrations.py` — optional live APIs")
s = s[:i0] + s[i1:]

i0 = s.index("### 4.7 `seatmap.py` — IRCTC-style seat charts")
i1 = s.index("## 5. Frontend reference")
s = s[:i0] + s[i1:]

rep("""| `renderReportList(reports, emptyMsg)` | Feed items incl. media |
| `renderMedia(items)` | Image `<img>`, video `<video controls>`, other `<a>` — all via `/api/media/<id>` |""",
"""| `renderReportList(reports, emptyMsg)` | Feed items (text reports + votes) |""")

rep("`reports.py`/`media.py` backends for Postgres/S3 when scaling.",
    "`reports.py` backend for Postgres when scaling.")

rep("""- **Scaling media:** keep `MediaStore`'s interface; swap `media.py` internals for multipart
  direct-to-R2 presigned uploads to avoid proxying large videos through Flask.
""", "")

rep("| `ModuleNotFoundError: flask` | Re-run `pip install flask numpy scipy boto3` (sandbox packages don't persist between sessions) |",
    "| `ModuleNotFoundError: flask` | Re-run `pip install -r requirements.txt` (sandbox packages don't persist between sessions) |")

rep("""| Uploads saved locally, not R2 | Check all 4 `R2_*` vars + boto3 installed; see startup log line "media storage:" |
""", "")

# ---------------------------------------------------------------- add data-audit note after data pipeline
rep("""6. **`smoke_map.js`** — Node smoke-test for the map code (no browser needed).""",
"""6. **`smoke_map.js`** — Node smoke-test for the map code (no browser needed).

> **Data audit:** the compiled `dataset.json` excludes (a) hand-added reference schedules and
> (b) all 0-prefixed "Special" trains (temporary/defunct services that no longer appear in the
> official *Where is my Train* app), leaving 5,023 trains. The remaining list is a public
> timetable snapshot — verify any single train against NTES before relying on it.""")

open(P, "w").write(s)
print("DOCUMENTATION.md cleaned OK —", len(s) // 1024, "KB")
