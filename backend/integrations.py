#!/usr/bin/env python3
"""
RailCrowd optional LIVE API integrations, gated behind a .env file.

Principle: if an API key/base-url is present in `.env`, RailCrowd will try that
authorised source first; otherwise it silently falls back to the public/static
data + model currently bundled. Nothing breaks without keys.

Create `railcrowd/backend/.env` (copy .env.example) and set any of:

  NTES_API_BASE / NTES_API_KEY        → live train running status (delay, position)
  IRCTC_API_BASE / IRCTC_API_KEY      → authorised IRCTC seat-availability / schedule
  RAILWAYAPI_BASE / RAILWAYAPI_KEY    → commercial rail data provider (e.g. RailAPI)
  GOOGLE_MAPS_API_KEY                 → station geocoding / static maps (reserved)
  OPENWEATHER_API_KEY                 → live weather at stations (rain/flood context)

The normalised outputs below are best-effort: the exact field names of the
official authorised endpoints vary by provider, so each parser keeps a raw
fallback and the app only uses values it can recognise.
"""
import os
import re

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

ENV_FILES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
]


def load_dotenv(path):
    """Tiny .env loader (no dependency). Existing env vars win."""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)
    except Exception:
        pass


def load_env():
    for p in ENV_FILES:
        load_dotenv(p)


def get(name, default=""):
    return os.environ.get(name, default).strip()


class Integrations:
    def __init__(self):
        self.ntes_base = get("NTES_API_BASE")
        self.ntes_key = get("NTES_API_KEY")
        self.irctc_base = get("IRCTC_API_BASE")
        self.irctc_key = get("IRCTC_API_KEY")
        self.railapi_base = get("RAILWAYAPI_BASE")
        self.railapi_key = get("RAILWAYAPI_KEY")
        self.gmaps_key = get("GOOGLE_MAPS_API_KEY")
        self.owm_key = get("OPENWEATHER_API_KEY")

    # ------------------------------------------------------------- status
    def active(self):
        """List of configured (active) providers — shown in /api/health."""
        a = []
        if self.ntes_base:
            a.append("NTES")
        if self.irctc_base and self.irctc_key:
            a.append("IRCTC")
        if self.railapi_base and self.railapi_key:
            a.append("RailAPI")
        if self.owm_key:
            a.append("OpenWeather")
        return a

    def _call(self, url, params=None, bearer=None, timeout=6):
        if requests is None:
            return None
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json() if "json" in r.headers.get("content-type", "") or r.text.lstrip().startswith(("{", "[")) else r.text
        except Exception:
            pass
        return None

    def train_status(self, number):
        """Live running status. Returns None if no provider configured / reachable."""
        # 1) NTES / authorised Indian Railways partner endpoint
        if self.ntes_base:
            data = self._call(self.ntes_base.rstrip("/") + f"/{number}",
                              bearer=self.ntes_key or None)
            if data:
                return self._parse_status(data, "ntes")
        # 2) commercial provider (RailAPI-style)
        if self.railapi_base and self.railapi_key:
            data = self._call(self.railapi_base.rstrip("/") + "/train/status",
                              params={"train": number, "apikey": self.railapi_key})
            if data:
                return self._parse_status(data, "railapi")
        return None

    def _parse_status(self, data, provider):
        d = data if isinstance(data, dict) else {"raw": data}
        def pick(*keys):
            for k in keys:
                if k in d:
                    return d[k]
            return None
        lat = pick("lat", "latitude", "current_lat", "position", "lat_lon")
        lon = pick("lon", "longitude", "current_lon")
        # lat/lon might be a comma string
        if isinstance(lat, str) and "," in lat:
            try:
                lat, lon = lat.split(",", 1)
            except Exception:
                pass
        out = {
            "provider": provider,
            "delay_min": pick("delay", "delay_min", "delay_minutes"),
            "position": None,
            "speed_kmh": pick("speed", "speed_kmh"),
            "last_station": pick("last_station", "current_station", "station"),
            "next_station": pick("next_station"),
            "status": pick("status", "train_status"),
        }
        try:
            if lat is not None and lon is not None:
                out["position"] = {"lat": float(lat), "lon": float(lon)}
        except (TypeError, ValueError):
            pass
        return out if (out["delay_min"] is not None or out["position"]) else None

    def seat_availability(self, number, date, from_code, to_code, class_code):
        """Authorised IRCTC availability. Returns None if not configured."""
        if not (self.irctc_base and self.irctc_key):
            return None
        data = self._call(self.irctc_base.rstrip("/") + "/availability",
                          params={"train": number, "date": date, "from": from_code,
                                  "to": to_code, "class": class_code},
                          bearer=self.irctc_key)
        if not data:
            return None
        d = data if isinstance(data, dict) else {"raw": data}
        avail = d.get("available") or d.get("availability") or d.get("seats")
        return {"class": class_code, "available": avail, "provider": "irctc"}

    # ------------------------------------------------------------- weather
    def weather(self, lat, lon):
        """OpenWeather current conditions. Returns None if no key."""
        if not self.owm_key:
            return None
        data = self._call("https://api.openweathermap.org/data/2.5/weather",
                          params={"lat": lat, "lon": lon, "appid": self.owm_key,
                                  "units": "metric"})
        if not isinstance(data, dict) or "main" not in data:
            return None
        w = (data.get("weather") or [{}])[0]
        return {
            "temp_c": round(data["main"].get("temp", 0), 1),
            "humidity": data["main"].get("humidity"),
            "desc": w.get("description", ""),
            "main": w.get("main", ""),
            "provider": "openweather",
        }
