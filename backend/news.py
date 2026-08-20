#!/usr/bin/env python3
"""
RailCrowd news crawler — REAL live data, multiple sources, recency-aware.

Sources (no API keys):
  1. Google News RSS  — topic queries, incl. `when:3d` / `when:7d` recency filters
  2. Bing News RSS    — same topics (format=rss)
  3. Times of India RSS — India feed, filtered to railway keywords

Each article is classified (delay / cancellation / weather / strike / derailment /
festival rush / security / new service), given an impact level, matched to trains &
stations in our dataset, and time-stamped so the UI can show "2h ago" and sort
newest-first. Fetched in parallel; cached ~8 minutes; degrades to cached / offline
sample if the network is unreachable.
"""
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

CACHE_TTL = 480  # seconds

G_QUERIES = [
    'Indian Railways train delay when:3d',
    'Indian Railways train cancelled OR diverted when:3d',
    'Indian Railways accident OR derail OR emergency when:7d',
    'Vande Bharat Express when:7d',
    'railway station rush OR crowding OR passengers when:7d',
    'Indian Railways monsoon OR fog OR weather when:7d',
]
B_QUERIES = [
    'Indian Railways train delay',
    'Indian Railways train cancelled',
    'Vande Bharat Express',
]
INDIA_FEEDS = [
    ("https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms", "Times of India"),
    ("https://www.thehindu.com/news/national/feeder/default.rss", "The Hindu"),
]

TRAIN_RE = re.compile(r"\b(\d{5})\b")
RAIL_KW = re.compile(r"rail|train|railway|vande bharat|shatabdi|rajdhani|express|station|coach|irctc|platform|passenger", re.I)
# clearly-foreign rail stories (kept only if the article also mentions India)
FOREIGN_RE = re.compile(
    r"\bbritain\b|\bengland\b|\blondon\b|\bunited kingdom\b|\bunited states\b|\bamerica\b"
    r"|\bcanada\b|\bgermany\b|\bfrance\b|\bjapan\b|\bchina\b|\bchinese\b|\bjapanese\b"
    r"|\bpakistan\b|\bbangladesh\b|\bnepal\b|\bsri lanka\b|\baustralia\b|\btokyo\b|\bbeijing\b|\bbbc\b", re.I)

CATEGORY_RULES = [
    ("Derailment/Accident", r"\bderail|\baccident|\bcollision|\bderailment|casualt|\bblast\b|caught fire", 1.0),
    ("Cancellation",       r"\bcancel|short-terminat|\bdivert", 0.95),
    ("Delay",              r"\bdelay|\blate\b|behind schedule|running late|\bdiverted", 0.8),
    ("Strike/Protest",     r"\bstrike|\bagitation|\bprotest|rail roko|\bblockade|\bbandh", 0.9),
    ("Weather",            r"\bmonsoon|\bflood|\bfog\b|\bcyclone|\bheatwave|\brains?\b|\bstorm|\bsnow|waterlog", 0.85),
    ("Festival rush",      r"\bfestival|\brush\b|\bholiday|special train|extra train|spl train|chhath|diwali|\bholi\b|\bmela\b|\bkumbh", 0.7),
    ("Security",           r"\bsecurity|\bbomb|\bhoax|\bsuspicious|\bsabotage", 0.9),
    ("New service",        r"new train|flag off|inaugurat|\blaunch|\bannounce", 0.6),
]


def parse_pub(s):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def classify(title, desc):
    text = f"{title} {desc}".lower()
    best_cat, best_sev = "General", 0.5
    for cat, pat, sev in CATEGORY_RULES:
        if re.search(pat, text) and sev > best_sev:
            best_cat, best_sev = cat, sev
    impact = "high" if best_sev >= 0.85 else ("medium" if best_sev >= 0.7 else "low")
    return best_cat, impact, best_sev


def _parse_rss(xml_text, source_label):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        desc = (it.findtext("description") or "").strip()
        src = ""
        m = re.search(r"<source[^>]*>([^<]+)</source>", desc)
        if m:
            src = m.group(1)
        items.append({
            "title": title, "link": link,
            "published": parse_pub(pub),
            "pub_raw": pub,
            "desc": re.sub(r"<[^>]+>", "", desc)[:240],
            "source": src or source_label,
        })
    return items


def _get(url, params=None, timeout=7):
    if requests is None:
        return None
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"},
                         timeout=timeout)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


class NewsCrawler:
    def __init__(self, trains, stations):
        self.trains = {t["number"]: t for t in trains}
        self.stations = stations
        self.cache = {"items": [], "at": 0.0}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ fetching
    def _fetch_google(self):
        out = []
        for q in G_QUERIES:
            xml = _get("https://news.google.com/rss/search",
                       {"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
            if xml:
                out += _parse_rss(xml, "Google News")
        return out

    def _fetch_bing(self):
        out = []
        for q in B_QUERIES:
            xml = _get("https://www.bing.com/news/search",
                       {"q": q, "format": "rss"})
            if xml:
                out += _parse_rss(xml, "Bing News")
        return out

    def _fetch_india_feeds(self):
        out = []
        for feed, label in INDIA_FEEDS:
            xml = _get(feed)
            if xml:
                for it in _parse_rss(xml, label):
                    if RAIL_KW.search(f"{it['title']} {it['desc']}"):
                        out.append(it)
        return out

    def _fetch_all(self):
        raw = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(self._fetch_google),
                    ex.submit(self._fetch_bing),
                    ex.submit(self._fetch_india_feeds)]
            for fut in as_completed(futs):
                try:
                    raw += fut.result()
                except Exception:
                    continue
        return raw

    def _normalize(self, raw):
        now = datetime.now(timezone.utc)
        seen, items = set(), []
        for it in raw:
            if not it.get("title"):
                continue
            # keep only railway-relevant articles
            if not RAIL_KW.search(f"{it['title']} {it['desc']}"):
                continue
            # drop clearly-foreign rail stories (unless they mention India too)
            if FOREIGN_RE.search(f"{it['title']} {it['desc']}") and "india" not in f"{it['title']} {it['desc']}".lower():
                continue
            key = re.sub(r"[^a-z0-9]+", "", it["title"].lower())[:90]
            if key in seen:
                continue
            seen.add(key)
            age = None
            if it["published"]:
                age = max(0, (now - it["published"]).total_seconds() / 60.0)
            it["age_min"] = round(age, 1) if age is not None else None
            it["fresh"] = age is not None and age < 48 * 60
            items.append(it)
        # newest first (unknown dates last)
        items.sort(key=lambda x: (x["published"] is None, -(x["published"].timestamp()
                     if x["published"] else 0)))
        return items

    def get_news(self, limit=80):
        now = time.time()
        with self.lock:
            if now - self.cache["at"] < CACHE_TTL and self.cache.get("annotated"):
                return self.cache["annotated"][:limit]
            if now - self.cache["at"] < CACHE_TTL and self.cache["items"]:
                items = list(self.cache["items"])
            else:
                raw = self._fetch_all()
                if raw:
                    items = self._normalize(raw)
                    self.cache = {"items": items, "at": now}
                elif self.cache["items"]:
                    items = list(self.cache["items"])  # stale-but-served
                else:
                    items = self._normalize([dict(OFFLINE_SAMPLE[0],
                                                  published=None, pub_raw="", age_min=None,
                                                  fresh=False),
                                             dict(OFFLINE_SAMPLE[1],
                                                  published=None, pub_raw="", age_min=None,
                                                  fresh=False)])
            annotated = self.annotate(items)
            self.cache["annotated"] = annotated
            return annotated[:limit]

    def annotate(self, items):
        out = []
        for it in items:
            cat, impact, sev = classify(it["title"], it["desc"])
            trains_hit, stations_hit = self.match(it)
            out.append({
                "title": it["title"], "link": it["link"], "source": it["source"],
                "published": it.get("pub_raw") or "",
                "age_min": it.get("age_min"), "fresh": it.get("fresh", False),
                "category": cat, "impact": impact, "severity": round(sev, 2),
                "trains": trains_hit, "stations": stations_hit,
            })
        rank = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda x: (rank[x["impact"]],
                                x["age_min"] if x["age_min"] is not None else 1e9))
        return out

    def match(self, it):
        text = f"{it['title']} {it['desc']}"
        train_hits, station_hits = [], []
        for num in TRAIN_RE.findall(text):
            if num in self.trains and len(train_hits) < 5:
                t = self.trains[num]
                train_hits.append({"number": num, "name": t["name"]})
        for code, st in self.stations.items():
            name = st["name"]
            if len(name) >= 5 and name.lower() in text.lower():
                station_hits.append({"code": code, "name": name})
                if len(station_hits) >= 6:
                    break
        return train_hits, station_hits

    # ------------------------------------------------------- impact lookup
    def impact_for_train(self, number, items=None):
        """Return (news_boost, news_delay_minutes, events) for a train.

        Precise matches (train number, or both origin+destination cities named)
        boost the model; softer regional matches are listed as related events.
        `items` may be an already-annotated news list (avoids re-annotation).
        """
        if items is None:
            items = self.get_news(limit=80)
        num = str(number)
        train = self.trains.get(num)
        if not train:
            return 0.0, 0, []
        from_tok = (train.get("from_name") or "").lower().split()[0]
        to_tok = (train.get("to_name") or "").lower().split()[0]
        events, related, boost, delay = [], [], 0.0, 0
        for it in items:
            raw = (it["title"] + " " + it.get("desc", ""))
            text = raw.lower()
            numbers = TRAIN_RE.findall(raw)
            hit_num = num in numbers
            hit_route = (from_tok and to_tok and len(from_tok) >= 4 and len(to_tok) >= 4
                         and from_tok in text and to_tok in text)
            hit_soft = (from_tok and len(from_tok) >= 4 and from_tok in text) or \
                       (to_tok and len(to_tok) >= 4 and to_tok in text)
            if hit_num or hit_route:
                events.append(it)
                if it["impact"] == "high":
                    boost = max(boost, 0.10)
                    delay = max(delay, 12)
                elif it["impact"] == "medium":
                    boost = max(boost, 0.05)
                    delay = max(delay, 6)
                else:
                    boost = max(boost, 0.02)
            elif hit_soft and it["impact"] == "high" and len(related) < 4:
                related.append(it)
                boost = max(boost, 0.02)
        final = events[:6] if events else related
        return round(boost, 3), delay, final


OFFLINE_SAMPLE = [
    {"title": "Indian Railways announces special trains for festival rush",
     "desc": "Additional coaches and special trains on major routes.", "source": "Sample",
     "published": "", "category": "Festival rush", "impact": "medium", "severity": 0.7,
     "trains": [], "stations": []},
    {"title": "Fog delays several north-bound trains",
     "desc": "Low visibility affected punctuality on the Northern Railway network.",
     "source": "Sample", "published": "", "category": "Weather", "impact": "medium",
     "severity": 0.85, "trains": [], "stations": []},
]
