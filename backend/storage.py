#!/usr/bin/env python3
"""
RailCrowd storage — pluggable persistence for community reports & votes.

Picks a backend automatically, in this order:

  1. Vercel Postgres  — when POSTGRES_URL (or POSTGRES_HOST/...) is set.
                        Used on Vercel so votes persist and affect crowd
                        ratings in REAL TIME across every serverless instance.
  2. Vercel KV        — when KV_REST_API_URL + KV_REST_API_TOKEN are set
                        (Upstash-compatible REST, no native driver needed).
  3. Local JSON       — development fallback (data/reports.json).

All backends expose the same interface used by reports.py:
    list_all()                  -> [report, ...]  (newest first)
    insert(report)              -> None
    update_votes(rid, votes)    -> None
    kind                        -> "postgres" | "kv" | "local"

Any backend may raise StorageError (caught by reports.py → friendly 400/500).
"""
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
REPORTS_FILE = os.path.join(DATA, "reports.json")


class StorageError(Exception):
    pass


def _env(name, default=""):
    return os.environ.get(name, default).strip()


# =================================================================== local
class LocalBackend:
    kind = "local"

    def _load(self):
        if os.path.exists(REPORTS_FILE):
            try:
                with open(REPORTS_FILE) as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self, reports):
        try:
            os.makedirs(DATA, exist_ok=True)
            tmp = REPORTS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(reports, f, indent=1, ensure_ascii=False)
            os.replace(tmp, REPORTS_FILE)
        except OSError as e:
            raise StorageError(
                "Storage unavailable — on Vercel configure POSTGRES_URL or "
                "KV_REST_API_URL (see .env.example / docs)") from e

    def list_all(self):
        return self._load()

    def insert(self, rep):
        reports = self._load()
        reports.append(rep)
        self._save(reports)

    def update_votes(self, rid, votes):
        reports = self._load()
        for r in reports:
            if r.get("id") == rid:
                r["votes"] = int(votes)
                self._save(reports)
                return
        raise StorageError("report not found")


# =================================================================== Vercel KV (REST)
class KVBackend:
    """Upstash/Vercel KV REST. Whole list stored as one JSON key."""
    kind = "kv"
    KEY = "railcrowd:reports"

    def __init__(self):
        self.url = _env("KV_REST_API_URL").rstrip("/")
        self.token = _env("KV_REST_API_TOKEN")
        self.headers = {"Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json"}

    def _req(self, method, path, body=None, timeout=8):
        import requests
        r = requests.request(method, f"{self.url}{path}",
                             headers=self.headers, json=body, timeout=timeout)
        if r.status_code != 200:
            raise StorageError(f"KV error {r.status_code}")
        return r.json()

    def _get_raw(self):
        try:
            out = self._req("GET", f"/get/{self.KEY}")
            res = out.get("result")
            return res
        except Exception:
            return None

    def _set(self, reports):
        self._req("POST", f"/set/{self.KEY}", body=[json.dumps(reports)])

    def list_all(self):
        res = self._get_raw()
        if res is None:
            return []
        if isinstance(res, (list, dict)):
            return res if isinstance(res, list) else []
        try:
            parsed = json.loads(res)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    def insert(self, rep):
        reports = self.list_all()
        reports.append(rep)
        self._set(reports)

    def update_votes(self, rid, votes):
        reports = self.list_all()
        for r in reports:
            if r.get("id") == rid:
                r["votes"] = int(votes)
                self._set(reports)
                return
        raise StorageError("report not found")


# =================================================================== Vercel Postgres
class PostgresBackend:
    kind = "postgres"
    TABLE = ("CREATE TABLE IF NOT EXISTS reports ("
             "id TEXT PRIMARY KEY, ts TEXT, type TEXT, type_label TEXT, "
             "train TEXT, station TEXT, message TEXT, votes INT DEFAULT 0)")

    def __init__(self):
        try:
            import psycopg2
            self.psycopg2 = psycopg2
        except ImportError as e:
            raise StorageError(
                "DATABASE_URL is set but psycopg2 is missing — "
                "add psycopg2-binary to requirements.txt") from e
        self.dsn = self._dsn()
        self._ensure_schema()

    def _dsn(self):
        # URL form — Neon / Vercel pooler URLs.
        # `DATABASE_URL` is auto-injected by the Vercel↔Neon integration;
        # `POSTGRES_URL` by the Vercel Postgres (legacy) integration.
        for key in ("DATABASE_URL", "POSTGRES_URL"):
            url = _env(key)
            if url:
                if url.startswith("postgres://"):
                    url = "postgresql://" + url[len("postgres://"):]
                return url
        # Unpooled / direct URL fallback
        for key in ("DATABASE_URL_UNPOOLED", "POSTGRES_URL_NON_POOLING",
                    "POSTGRES_URL_NO_SSL"):
            url = _env(key)
            if url:
                if url.startswith("postgres://"):
                    url = "postgresql://" + url[len("postgres://"):]
                return url
        # Discrete PGHOST/… variables (newer Neon integration style)
        host = _env("PGHOST") or _env("POSTGRES_HOST")
        if not host:
            raise StorageError(
                "No database configured — set DATABASE_URL (Neon/Vercel) in "
                "the project Environment Variables, or PGHOST/POSTGRES_HOST…")
        from urllib.parse import quote
        port = _env("PGPORT") or _env("POSTGRES_PORT") or "5432"
        dbname = _env("PGDATABASE") or _env("POSTGRES_DATABASE")
        user = _env("PGUSER") or _env("POSTGRES_USER")
        password = quote(_env("PGPASSWORD") or _env("POSTGRES_PASSWORD"), safe="")
        return (f"host={host} port={port} dbname={dbname} user={user} "
                f"password={password} sslmode=require")

    def _connect(self):
        return self.psycopg2.connect(self.dsn)

    def _ensure_schema(self):
        """Create the reports table. execute() runs on a CURSOR (not the
        connection) and we commit() explicitly — psycopg2's `with conn:`
        only closes, it does NOT commit."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(self.TABLE)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_all(self):
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, ts, type, type_label, train, "
                                "station, message, votes FROM reports "
                                "ORDER BY ts DESC LIMIT 500")
                    rows = cur.fetchall()
            finally:
                conn.close()
            return [{"id": r[0], "ts": r[1], "type": r[2],
                     "type_label": r[3], "train": r[4],
                     "station": r[5], "message": r[6],
                     "votes": int(r[7] or 0)} for r in rows]
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Postgres read failed: {e}")

    def insert(self, rep):
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO reports (id, ts, type, type_label, "
                        "train, station, message, votes) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (id) DO NOTHING",
                        (rep["id"], rep["ts"], rep["type"], rep["type_label"],
                         rep.get("train") or None, rep.get("station") or None,
                         rep["message"], int(rep.get("votes", 0))))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Postgres write failed: {e}")

    def update_votes(self, rid, votes):
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE reports SET votes=%s WHERE id=%s",
                                (int(votes), rid))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Postgres update failed: {e}")


# =================================================================== factory
def get_backend():
    # Postgres first (Neon / Vercel), auto-detected from any of the URL/host vars.
    # Any construction/connection error falls back gracefully so the site never
    # crashes at import — /api/health will report `storage: local` for diagnosis.
    if (_env("DATABASE_URL") or _env("DATABASE_URL_UNPOOLED")
            or _env("POSTGRES_URL") or _env("POSTGRES_URL_NON_POOLING")
            or _env("POSTGRES_URL_NO_SSL")
            or _env("PGHOST") or _env("POSTGRES_HOST")):
        try:
            return PostgresBackend()
        except Exception:
            pass  # driver missing / bad config / DB down — fall back, don't crash
    if _env("KV_REST_API_URL") and _env("KV_REST_API_TOKEN"):
        try:
            return KVBackend()
        except Exception:
            pass
    return LocalBackend()
