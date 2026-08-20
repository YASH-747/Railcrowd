#!/usr/bin/env python3
"""
Vercel Serverless entry point (path-preserving).

vercel.json rewrites EVERY request to `/api/index/<original-path>`, e.g.:
    /api/health      ->  /api/index/api/health
    /train/12951     ->  /api/index/train/12951
    /                ->  /api/index/

The PathNormalizer middleware below strips the `/api/index` prefix and restores
the original PATH_INFO, so Flask's own routes match again:
    /api/health -> JSON   (instead of the SPA HTML, which caused the
                            "Unexpected token '<' … is not valid JSON" error)
    /           -> index.html
    /train/12951-> index.html (SPA fallback)

Environment on Vercel:
  - Set POSTGRES_URL (Vercel Postgres) or KV_REST_API_URL + KV_REST_API_TOKEN
    (Vercel KV) so community reports/votes persist and affect crowd ratings in
    real time. Without them, reports fall back to local storage, which is
    read-only on Vercel (writes return a friendly error).
  - Optional live data: NTES_API_BASE/KEY, IRCTC_API_BASE/KEY, OPENWEATHER_API_KEY.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from app import app  # noqa: E402


class PathNormalizer:
    PREFIX = "/api/index"

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script = (environ.get("SCRIPT_NAME") or "").rstrip("/")
        path = environ.get("PATH_INFO") or "/"
        full = script + path

        if full == self.PREFIX or full == self.PREFIX + "/":
            environ["SCRIPT_NAME"] = ""
            environ["PATH_INFO"] = "/"
        elif full.startswith(self.PREFIX + "/"):
            environ["SCRIPT_NAME"] = ""
            environ["PATH_INFO"] = full[len(self.PREFIX):] or "/"
        # else: no prefix (local dev / direct call) — pass through unchanged

        return self.app(environ, start_response)


# Rebind the WSGI callable Vercel imports as `app`
app = PathNormalizer(app)
