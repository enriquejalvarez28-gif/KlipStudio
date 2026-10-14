"""Trend & opportunity radar from permitted public feeds.

Sources (all public RSS, no login, no scraping of private data):
  * Google News RSS search, one query per batch of brand topic keywords
  * Google Trends "trending now" RSS (US), kept only when it matches a topic
  * YouTube public channel feeds for configured competitor channels
Scores are a transparent HEURISTIC (relevance, freshness, momentum,
novelty). They are not search volume and not a virality prediction.
"""

import hashlib
import json
import math
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from growth_os import analytics
from growth_os.db import new_id, utcnow
from growth_os.http import Client

NEWS_RSS = "https://news.google.com/rss/search"
TRENDS_RSS = "https://trends.google.com/trending/rss"
YT_FEED = "https://www.youtube.com/feeds/videos.xml"
WEIGHTS = {"relevance": 0.4, "freshness": 0.3, "momentum": 0.2, "novelty": 0.1}
HALF_LIFE_H = 48
STOP = set("the a an and or of to in on for with at by from is are was be as it its this that vs after over new".split())


class RawTextClient(Client):
    """Same budget/logging as Client but returns bytes (feeds are XML)."""

    def get_text(self, url, params, name):
        import time

        from growth_os.http import BudgetExceeded
        if params:
            url += "?" + urllib.parse.urlencode(params)
        if self.used_today() >= self.daily_requests:
            raise BudgetExceeded("daily request budget reached")
        t0 = time.monotonic()
        status, raw = self.transport("GET", url, {"User-Agent": "KlipGrowthOS/1.0 (+owner dashboard)"}, None)
        self._log(name, status, int((time.monotonic() - t0) * 1000), 0, False)
        if status >= 400:
            raise RuntimeError(f"{name}: HTTP {status}")
        return raw


def _parse_date(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def parse_rss(raw, source_type):
    root = ET.fromstring(raw)
    items = []
    if source_type == "youtube_competitor":
        ns = {"a": "http://www.w3.org/2005/Atom"}
        author = root.findtext("a:title", default="", namespaces=ns)
        for e in root.findall("a:entry", ns):
            link = e.find("a:link", ns)
            items.append({"title": e.findtext("a:title", default="", namespaces=ns),
                          "url": link.get("href") if link is not None else None,
                          "published": _parse_date(e.findtext("a:published", default="", namespaces=ns)),
                          "source": author})
        return items
    for it in root.iter("item"):
        src = it.find("source")
        items.append({"title": (it.findtext("title") or "").strip(), "url": it.findtext("link"),
                      "published": _parse_date(it.findtext("pubDate")),
                      "source": (src.text if src is not None else "") or source_type,
                      "traffic": it.findtext("{https://trends.google.com/trending/rss}approx_traffic")})
    return items


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def cluster_key(title):
    return " ".join(sorted(tokens(title))[:6])


def score_item(item, keywords, now, cluster_sizes, covered_tokens):
    low = (item["title"] or "").lower()
    matched = [(k, w) for k, w in keywords if k.lower() in low]
    total_w = sum(w for _, w in keywords) or 1
    relevance = min(1.0, sum(w for _, w in matched) / max(1.0, total_w * 0.15)) if matched else 0.0
    age_h = (now - item["published"]).total_seconds() / 3600 if item["published"] else None
    freshness = 0.5 ** (age_h / HALF_LIFE_H) if age_h is not None else 0.2
    momentum = min(1.0, (cluster_sizes.get(item["cluster"], 1) - 1) / 4)
    t = tokens(item["title"])
    overlap = len(t & covered_tokens) / len(t) if t else 0
    novelty = 1 - min(1.0, overlap * 1.5)
    parts = {"relevance": round(relevance, 2), "freshness": round(freshness, 2), "momentum": round(momentum, 2),
             "novelty": round(novelty, 2)}
    score = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()))
    n_sources = cluster_sizes.get(item["cluster"], 1)
    if n_sources >= 3 and relevance >= 0.5:
        unc = "lower — several independent sources, strong topic match"
    elif n_sources >= 2 or relevance >= 0.5:
        unc = "medium — limited corroboration or partial topic match"
    else:
        unc = "high — single source; verify before acting"
    return score, parts, [k for k, _ in matched], unc, age_h


def research(conn, tenant_id, *, transport=None, now=None):
    keywords = analytics.topic_keywords(conn, tenant_id)
    if not keywords:
        return {"skipped": "no topic keywords configured for this brand (Settings → Topics)"}
    now = now or datetime.now(timezone.utc)
    http = RawTextClient(conn, tenant_id, transport=transport)
    collected, errors = [], []

    # Google News: batch keywords into OR queries (fewer requests).
    kws = [k for k, _ in keywords][:12]
    for i in range(0, len(kws), 4):
        q = " OR ".join(f'"{k}"' for k in kws[i:i + 4]) + " when:7d"
        try:
            raw = http.get_text(NEWS_RSS, {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}, "google.news.rss")
            collected += [dict(x, source_type="news") for x in parse_rss(raw, "news")[:30]]
        except Exception as e:
            errors.append(f"news: {str(e)[:120]}")
    try:
        raw = http.get_text(TRENDS_RSS, {"geo": "US"}, "google.trends.rss")
        collected += [dict(x, source_type="google_trends") for x in parse_rss(raw, "google_trends")]
    except Exception as e:
        errors.append(f"trends: {str(e)[:120]}")
    for c in conn.execute("SELECT ref, name FROM competitors WHERE tenant_id=? AND platform='youtube'", (tenant_id,)):
        try:
            raw = http.get_text(YT_FEED, {"channel_id": c["ref"]}, "youtube.public.feed")
            collected += [dict(x, source_type="youtube_competitor") for x in parse_rss(raw, "youtube_competitor")[:15]]
        except Exception as e:
            errors.append(f"competitor {c['name'] or c['ref']}: {str(e)[:120]}")

    # Same story from several queries counts once; near-duplicate headlines
    # (Jaccard ≥ 0.5) form one cluster; momentum = distinct outlets in it.
    seen, unique = set(), []
    for it in collected:
        if it.get("url") and it["url"] not in seen:
            seen.add(it["url"])
            unique.append(it)
    collected = unique
    clusters = []  # [(token_set, key, outlets)]
    for it in collected:
        t = tokens(it["title"])
        home = next((c for c in clusters if t and len(t & c[0]) / len(t | c[0]) >= 0.5), None)
        if home is None:
            home = (set(t), cluster_key(it["title"]), set())
            clusters.append(home)
        home[2].add(it["source"] or it["url"])
        it["cluster"] = home[1]
    sizes = {c[1]: len(c[2]) for c in clusters}
    covered = set()
    for r in conn.execute("SELECT title FROM assets WHERE tenant_id=? UNION SELECT title FROM calendar_items WHERE tenant_id=? "
                          "UNION SELECT title FROM trends WHERE tenant_id=? AND status='dismissed'",
                          (tenant_id, tenant_id, tenant_id)):
        covered |= tokens(r[0])
    added = 0
    fetched = utcnow()
    for it in collected:
        if not it.get("url"):
            continue
        score, parts, matched, unc, age_h = score_item(it, keywords, now, sizes, covered)
        if it["source_type"] == "google_trends" and not matched:
            continue  # national trend unrelated to this brand
        if it["source_type"] == "news" and not matched:
            continue
        parts["age_hours"] = round(age_h, 1) if age_h is not None else None
        parts["sources_in_cluster"] = sizes.get(it["cluster"], 1)
        if it.get("traffic"):
            parts["google_trends_approx_traffic"] = it["traffic"]
        cur = conn.execute(
            """INSERT INTO trends (id, tenant_id, cluster_key, title, url, source, source_type, published_at, fetched_at,
               matched_keywords, score, score_json, uncertainty) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (tenant_id, url) DO UPDATE SET score=excluded.score, score_json=excluded.score_json,
               uncertainty=excluded.uncertainty, fetched_at=excluded.fetched_at""",
            (new_id("tr_"), tenant_id, it["cluster"], it["title"], it["url"], it["source"], it["source_type"],
             it["published"].isoformat() if it["published"] else None, fetched, ", ".join(matched), score,
             json.dumps(parts), unc))
        added += cur.rowcount
    return {"items_seen": len(collected), "stored_or_updated": added, "errors": errors}


def competitor_gaps(conn, tenant_id, days=30):
    """Competitor uploads (public feeds) whose topic tokens this brand hasn't covered."""
    mine = set()
    for r in conn.execute("SELECT title FROM assets WHERE tenant_id=?", (tenant_id,)):
        mine |= tokens(r[0])
    rows = conn.execute("""SELECT * FROM trends WHERE tenant_id=? AND source_type='youtube_competitor'
                           ORDER BY published_at DESC LIMIT 60""", (tenant_id,)).fetchall()
    out = []
    for r in rows:
        t = tokens(r["title"])
        if t and len(t & mine) / len(t) < 0.34:
            out.append({"title": r["title"], "competitor": r["source"], "url": r["url"], "published_at": r["published_at"]})
    return out[:15]


def digest(items):
    return hashlib.sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()[:16]
