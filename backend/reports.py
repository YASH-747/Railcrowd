#!/usr/bin/env python3
"""
RailCrowd community reports — user-submitted complaints & observations.

Users can report: overcrowded platform, no space to stand in train, heavy rain
on platform, coach issues, cleanliness, security, delays, etc. Reports are
stored via `storage.py` (local JSON in dev; Vercel Postgres / Vercel KV in
production), can be up-voted, and feed the crowding/delay model in REAL TIME:
a recent report about a train (or any station on its route) nudges that
train's occupancy & delay, and the more up-votes a report has, the stronger
its effect — so community voting directly moves the crowd rating.

No auth required (public, device-local community feed).
"""
import re
import time
from datetime import datetime

import zoneinfo

from storage import get_backend, StorageError

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

REPORT_TYPES = [
    ("overcrowded_platform", "Overcrowded platform", 0.10, 0),
    ("no_space_train", "No space to stand in train", 0.12, 0),
    ("rain_platform", "Heavy rain on platform", 0.03, 10),
    ("coach_issue", "Coach problem (AC/lights/doors)", 0.05, 5),
    ("cleanliness", "Cleanliness / hygiene", 0.0, 0),
    ("security", "Security concern", 0.0, 8),
    ("delayed_train", "Train delayed / late", 0.02, 15),
    ("other", "Other", 0.0, 0),
]
TYPE_LABEL = {t[0]: t[1] for t in REPORT_TYPES}
TYPE_BOOST = {t[0]: t[2] for t in REPORT_TYPES}
TYPE_DELAY = {t[0]: t[3] for t in REPORT_TYPES}

# an up-voted report is more credible → its crowd/delay impact grows with votes
def _vote_weight(votes):
    v = max(0, int(votes or 0))
    return 1.0 + 0.08 * min(v, 25)   # +8% impact per up-vote, capped at ~3x


def _now_iso():
    return datetime.now(IST).isoformat(timespec="seconds")


def _seed():
    """A few starter reports so the community feed isn't empty (demo, dev only)."""
    base = time.time()
    samples = [
        ("no_space_train", "12951", "", "General coaches packed from Surat onwards, no place to stand near the doors.", 12),
        ("overcrowded_platform", "", "BCT", "Platform 3 extremely crowded during evening rush, queue till the footbridge.", 9),
        ("rain_platform", "", "ADI", "Heavy rain on platform 6, floor very slippery near the escalator.", 7),
        ("coach_issue", "12009", "", "AC in coach C3 not working, quite hot inside.", 5),
        ("delayed_train", "19023", "", "Train held at outer signal for 25 minutes, no announcement.", 4),
        ("cleanliness", "", "NDLS", "Water bottles and food packets littered on platform 1.", 3),
    ]
    out = []
    for i, (typ, train, station, msg, votes) in enumerate(samples):
        ts = datetime.fromtimestamp(base - (i + 1) * 37 * 60, IST).isoformat(timespec="seconds")
        out.append({
            "id": f"seed-{i + 1}",
            "ts": ts, "type": typ, "type_label": TYPE_LABEL[typ],
            "train": train, "station": station, "message": msg,
            "votes": votes, "seed": True,
        })
    return out


class ReportStore:
    def __init__(self, trains, stations):
        self.trains = {t["number"]: t for t in trains}
        self.stations = stations
        self.backend = get_backend()
        # seed only on the local dev backend when empty
        if self.backend.kind == "local":
            try:
                if not self.backend.list_all():
                    for r in _seed():
                        self.backend.insert(r)
            except StorageError:
                pass

    @property
    def storage_kind(self):
        return self.backend.kind

    # ------------------------------------------------------------- queries
    def list(self, train=None, station=None, limit=50):
        try:
            reports = self.backend.list_all()
        except StorageError:
            return []
        out = []
        for r in reports:
            if train and r.get("train") != train:
                continue
            if station and r.get("station") != station:
                continue
            out.append(r)
        out.sort(key=lambda r: r.get("ts", ""), reverse=True)
        return out[:limit]

    def recent_for_train(self, number, hours=12):
        now = datetime.now(IST)
        out = []
        for r in self.list(limit=300):
            if r.get("train") != number:
                continue
            try:
                ts = datetime.fromisoformat(r["ts"])
                if (now - ts).total_seconds() <= hours * 3600:
                    out.append(r)
            except Exception:
                continue
        return out

    def boost_for_train(self, train):
        """(occupancy_boost, delay_minutes, reports) from community posts.

        Time-decayed (≤12h) AND vote-weighted: each up-vote raises a report's
        impact, so voting changes the crowd rating in real time.
        """
        number = train["number"]
        stop_codes = {s["code"] for s in (train.get("stops") or [])}
        now = datetime.now(IST)
        boost, delay, hits = 0.0, 0, []
        for r in self.list(limit=300):
            if r.get("train") == number or (r.get("station") and r["station"] in stop_codes):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                    age_h = (now - ts).total_seconds() / 3600.0
                except Exception:
                    continue
                if age_h > 12:
                    continue
                w = max(0.2, 1.0 - age_h / 12.0) * _vote_weight(r.get("votes", 0))
                boost += TYPE_BOOST.get(r["type"], 0.0) * w
                delay += TYPE_DELAY.get(r["type"], 0) * w
                hits.append(r)
        return round(min(0.20, boost), 3), int(round(min(40, delay))), hits[:6]

    # ------------------------------------------------------------- writes
    def add(self, type_, train=None, station=None, message=""):
        type_ = (type_ or "").strip()
        if type_ not in TYPE_LABEL:
            return None, "Unknown report type"
        message = re.sub(r"<[^>]+>", "", message or "").strip()
        if len(message) < 3:
            return None, "Please describe the issue (at least a few words)"
        if train:
            train = train.strip().upper()
            if train not in self.trains:
                return None, f"Train {train} not found"
        if station:
            station = station.strip().upper()
            if station not in self.stations:
                return None, f"Station {station} not found"
        if not train and not station:
            return None, "Attach a train number or station code so others can find it"
        rep = {
            "id": f"r{int(time.time() * 1000)}",
            "ts": _now_iso(), "type": type_, "type_label": TYPE_LABEL[type_],
            "train": train, "station": station, "message": message[:400],
            "votes": 0,
        }
        try:
            self.backend.insert(rep)
        except StorageError as e:
            return None, str(e)
        return rep, None

    def vote(self, rid, delta=1):
        try:
            for r in self.backend.list_all():
                if r.get("id") == rid:
                    new = max(0, int(r.get("votes", 0)) + delta)
                    self.backend.update_votes(rid, new)
                    return new
        except StorageError:
            return None
        return None
