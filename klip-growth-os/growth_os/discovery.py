"""Discovery page (spec v5 §6): distribution health, keyword workspace,
manual AI-visibility log, competitor library and the pre-recording episode
planner. Public lookups only (iTunes Search API + the show's public RSS);
no invented search volumes, no autonomous AI querying.
"""

import json
import re
from collections import Counter
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

from growth_os import ai, analytics, brands, thumbs, trends
from growth_os.db import new_id, utcnow

ITUNES = "https://itunes.apple.com/search"
STATUSES = ("Connected analytics", "Verified listing only", "Imported report", "Needs authorization", "Not found",
            "Unavailable")
AI_SAMPLE_QUERIES = ["sports podcasts for parents of young athletes", "interviews about youth athlete development",
                     "podcasts covering the business of sports"]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _show_names(conn, tenant_id):
    names = [r[0] for r in conn.execute("SELECT account_name FROM platform_accounts WHERE tenant_id=? AND account_name!=''",
                                        (tenant_id,))]
    b = conn.execute("SELECT display_name FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
    return list(dict.fromkeys(names + ([b[0]] if b else [])))


def parse_feed(raw):
    root = ET.fromstring(raw)
    ch = root.find("channel")
    if ch is None:
        return {}
    items = ch.findall("item")
    dates = [i.findtext("pubDate") for i in items if i.findtext("pubDate")]
    return {"title": ch.findtext("title"), "episodes": len(items), "latest": dates[0] if dates else None,
            "has_description": bool((ch.findtext("description") or "").strip()),
            "has_category": ch.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}category") is not None,
            "has_image": ch.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}image") is not None or ch.find("image") is not None}


def check_distribution(conn, tenant_id, *, transport=None, term=None):
    """Refresh distribution statuses. Each platform gets exactly one of STATUSES."""
    http = trends.RawTextClient(conn, tenant_id, transport=transport)
    accts = {a["platform"]: a for a in brands.accounts(conn, tenant_id) if a["state"] != brands.REJECTED}
    imports = {r[0] for r in conn.execute("SELECT DISTINCT platform FROM metrics WHERE tenant_id=? AND source LIKE '%import%'",
                                          (tenant_id,))}
    names = [term] if term else _show_names(conn, tenant_id)
    now = utcnow()
    out = {}
    yt = accts.get("youtube")
    out["youtube"] = ("Connected analytics" if yt and yt["state"] in (brands.ACTIVE, brands.SYNCING, brands.ASSIGNED)
                      else "Needs authorization", {"account": yt["account_name"] if yt else None})
    # Apple Podcasts: public iTunes Search API, matched on the show name.
    apple, feed = None, None
    for n in names:
        try:
            raw = http.get_text(ITUNES, {"term": n, "media": "podcast", "limit": 10}, "itunes.search")
            res = json.loads(raw).get("results", [])
            apple = next((x for x in res if _norm(x.get("collectionName")) == _norm(n)
                          or _norm(n) in _norm(x.get("collectionName"))), None)
            if apple:
                break
        except Exception as e:  # network/budget: say Unavailable, never guess
            out["apple_podcasts"] = ("Unavailable", {"error": str(e)[:120]})
    if "apple_podcasts" not in out:
        if "apple_podcasts" in imports:
            out["apple_podcasts"] = ("Imported report", {"listing": bool(apple)})
        elif apple:
            out["apple_podcasts"] = ("Verified listing only", {k: apple.get(k) for k in (
                "collectionName", "artistName", "collectionViewUrl", "trackCount", "releaseDate", "primaryGenreName")})
            feed = apple.get("feedUrl")
        else:
            out["apple_podcasts"] = ("Not found", {"searched": names})
    if feed:
        try:
            out["rss"] = ("Verified listing only", dict(parse_feed(http.get_text(feed, None, "podcast.rss")), url=feed))
        except Exception as e:
            out["rss"] = ("Unavailable", {"url": feed, "error": str(e)[:120]})
    else:
        out["rss"] = ("Not found", {"why": "no public feed found via the Apple listing"})
    sp = accts.get("spotify")
    out["spotify"] = ("Imported report" if "spotify" in imports else "Verified listing only" if sp
                      else "Needs authorization", {"why": "Spotify has no public search without sign-in; add the show link "
                                                         "in Manage Accounts or import a Spotify for Creators CSV"})
    out["instagram"] = ("Needs authorization", {"why": "Meta access must be granted by the Facebook account that owns it"})
    for p, (st, det) in out.items():
        conn.execute("INSERT OR REPLACE INTO distribution_checks VALUES (?,?,?,?,?)", (tenant_id, p, st, json.dumps(det), now))
    return distribution(conn, tenant_id)


def distribution(conn, tenant_id):
    return [{"platform": r["platform"], "status": r["status"], "detail": json.loads(r["detail_json"]), "checked_at": r["checked_at"]}
            for r in conn.execute("SELECT * FROM distribution_checks WHERE tenant_id=? ORDER BY platform", (tenant_id,))]


def keywords(conn, tenant_id):
    """Topic keywords + observed YouTube search terms (views are measured; no volumes are invented)."""
    terms = [{"term": r[0], "views": int(r[1]), "videos": r[2]} for r in conn.execute(
        """SELECT period_start, SUM(value), COUNT(DISTINCT asset_id) FROM metrics WHERE tenant_id=? AND grain='search_term'
           GROUP BY period_start ORDER BY SUM(value) DESC LIMIT 40""", (tenant_id,))]
    titles = " ".join((r[0] or "").lower() for r in conn.execute("SELECT title FROM assets WHERE tenant_id=?", (tenant_id,)))
    topics = [{"keyword": k, "in_titles": titles.count(k.lower())} for k, _ in analytics.topic_keywords(conn, tenant_id)]
    return {"search_terms": terms, "topics": topics,
            "note": "Search terms = YouTube search queries that led to your videos (views, measured). "
                    "Search volume is not available from free sources, so none is shown."}


def ai_samples(conn, tenant_id):
    rows = [dict(r) for r in conn.execute("SELECT * FROM ai_visibility_samples WHERE tenant_id=? ORDER BY sampled_on DESC, created_at DESC",
                                          (tenant_id,))]
    by_q = {}
    for r in rows:
        q = by_q.setdefault(r["query"], {"query": r["query"], "samples": 0, "mentioned": 0})
        q["samples"] += 1
        q["mentioned"] += r["mentioned"]
    return {"items": rows, "summary": list(by_q.values()), "suggested_queries": AI_SAMPLE_QUERIES,
            "method": "Manual samples: ask the same question in a free AI interface, record whether RYJ appears. "
                      "These are sampled mentions, not a ranking."}


def add_ai_sample(conn, tenant_id, body):
    q, eng = str(body.get("query", "")).strip()[:300], str(body.get("engine", "")).strip()[:80]
    if not q or not eng:
        raise ValueError("query and engine/model are required")
    d = str(body.get("sampled_on") or date.today().isoformat())[:10]
    date.fromisoformat(d)
    rid = new_id("ais_")
    conn.execute("INSERT INTO ai_visibility_samples VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, tenant_id, d, eng, q, 1 if body.get("mentioned") else 0, str(body.get("cited_url", ""))[:300],
                  str(body.get("note", ""))[:500], utcnow()))
    return {"id": rid}


def competitors(conn, tenant_id):
    lib = []
    for c in conn.execute("SELECT * FROM competitors WHERE tenant_id=? ORDER BY name", (tenant_id,)):
        ups = conn.execute("""SELECT title, url, published_at FROM trends WHERE tenant_id=? AND source_type='youtube_competitor'
                              AND (source=? OR source=?) ORDER BY published_at DESC LIMIT 30""",
                           (tenant_id, c["name"], c["ref"])).fetchall()
        dates = sorted(date.fromisoformat(u["published_at"][:10]) for u in ups if u["published_at"])
        cadence = round((dates[-1] - dates[0]).days / (len(dates) - 1), 1) if len(dates) > 2 else None
        lib.append({"platform": c["platform"], "ref": c["ref"], "name": c["name"], "uploads_seen": len(ups),
                    "days_between_uploads": cadence, "latest": [dict(u) for u in ups[:3]]})
    return {"library": lib, "gaps": trends.competitor_gaps(conn, tenant_id),
            "note": "Public feeds only (latest ~15 uploads per channel). Competitors' impressions/retention are never shown."}


PLANNER_INSTRUCTIONS = (
    "You are the producer of a sports interview podcast. Plan ONE pre-recording episode on INPUT.topic for INPUT.show. "
    "Stay sports-specific (no entertainment gossip). Use only INPUT.sources for anything time-sensitive and cite them by "
    "index; if none support 'why now', say evergreen. Never invent quotes, stats or search volume. "
    'Shape: {"viewer_question":"","why_ryj":"","trending_or_evergreen":"trending|evergreen","guest_expertise":"",'
    '"questions":["8-12 natural questions"],"hooks":["3 opening hooks"],"follow_ups":["3"],"titles":["3"],'
    '"thumbnail_headlines":["2, max 4 words each, use *word* for the gold word"],"clip_themes":["3-5"],'
    '"metric_to_watch":"","cited_sources":[0]}'
)


def plan_episode(conn, tenant_id, topic, guest="", runner=None):
    topic = (topic or "").strip()[:200]
    if not topic:
        raise ValueError("topic is required")
    toks = set(trends.tokens(topic))
    src = [dict(r) for r in conn.execute("""SELECT title, url, source, published_at FROM trends WHERE tenant_id=?
                                            ORDER BY published_at DESC LIMIT 300""", (tenant_id,))]
    src = sorted([s for s in src if toks & set(trends.tokens(s["title"]))],
                 key=lambda s: -len(toks & set(trends.tokens(s["title"]))))[:8]
    past = [r[0] for r in conn.execute("SELECT title FROM assets WHERE tenant_id=?", (tenant_id,))
            if toks & set(trends.tokens(r[0] or ""))][:8]
    show = (_show_names(conn, tenant_id) or [""])[0]
    payload = {"topic": topic, "guest": guest, "show": show, "past_related_episodes": past,
               "sources": [{"i": i, "title": s["title"], "source": s["source"], "date": (s["published_at"] or "")[:10]}
                           for i, s in enumerate(src)]}
    try:
        plan, meta = ai.ask(conn, tenant_id, f"plan:{_norm(topic)[:40]}", payload, PLANNER_INSTRUCTIONS, runner=runner)
        plan["_meta"] = meta
    except ai.AIUnavailable as e:
        plan = {"_unavailable": str(e)[:160],
                "viewer_question": topic if topic.endswith("?") else None,
                "trending_or_evergreen": "trending" if src else "evergreen",
                "questions": [], "hooks": [], "titles": [],
                "thumbnail_headlines": thumbs.default_headlines(topic)}
    cited = [src[i] for i in plan.get("cited_sources", []) if isinstance(i, int) and 0 <= i < len(src)]
    rid = new_id("plan_")
    conn.execute("INSERT INTO episode_plans VALUES (?,?,?,?,?,?,?)",
                 (rid, tenant_id, topic, guest[:120], json.dumps(plan), json.dumps(cited or src), utcnow()))
    return {"id": rid, "topic": topic, "guest": guest, "plan": plan, "sources": cited or src, "past_related": past,
            "rules": "Draft for planning. After recording, check hooks/titles against the actual transcript; never use a quote "
                     "the guest didn't say. Watch day 1/3/7/28 in Launch cohorts."}


def plans(conn, tenant_id):
    return [dict(r, plan=json.loads(r["plan_json"]), sources=json.loads(r["sources_json"]))
            for r in conn.execute("SELECT * FROM episode_plans WHERE tenant_id=? ORDER BY created_at DESC LIMIT 20", (tenant_id,))]


def page(conn, tenant_id):
    return {"distribution": distribution(conn, tenant_id), "statuses": STATUSES, "keywords": keywords(conn, tenant_id),
            "ai_visibility": ai_samples(conn, tenant_id), "competitors": competitors(conn, tenant_id),
            "plans": [{k: p[k] for k in ("id", "topic", "guest", "created_at", "plan", "sources")} for p in plans(conn, tenant_id)]}


# ── Operator dry run (spec §10.2): what a write would do, and why it is blocked ──

WRITE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


def operator_dry_run(conn, tenant_id, rec_id, target_channel_id):
    """Simulate the approved change. Never calls the platform. Refuses the wrong channel; BLOCKED without a write scope."""
    r = conn.execute("SELECT * FROM recommendations WHERE id=? AND tenant_id=?", (rec_id, tenant_id)).fetchone()
    if not r:
        raise LookupError("recommendation not found")
    acct = conn.execute("SELECT * FROM platform_accounts WHERE tenant_id=? AND platform='youtube' AND state!=?",
                        (tenant_id, brands.REJECTED)).fetchone()
    plan = {"rec_id": rec_id, "destination": target_channel_id, "change": r["title"], "asset_id": r["asset_id"],
            "required_scope": WRITE_SCOPE, "dry_run": True}
    if not acct or acct["platform_account_id"] != target_channel_id:
        return dict(plan, result="REFUSED", reason="destination channel is not the YouTube channel bound to this brand")
    if r["workflow"] not in ("approved", "blocked"):
        return dict(plan, result="REFUSED", reason=f"card is {r['workflow']}; it needs your approval first")
    if WRITE_SCOPE not in (acct["scopes"] or ""):
        if r["workflow"] != "blocked":
            analytics.move_rec(conn, tenant_id, rec_id, "blocked", "operator", "awaiting authorization: read-only connection")
        return dict(plan, result="BLOCKED", reason="awaiting authorization: the YouTube connection is read-only "
                                                   "(no write scope). Apply it yourself in YouTube Studio, then mark Executed.")
    return dict(plan, result="READY", reason="write scope present; a real run would apply, read back and log rollback")


# ── Competition research (public YouTube data via the channel's read-only token) ──

MIN_SUBS, MAX_SUBS = 1_000, 500_000
COMPETITOR_QUERIES = ["youth sports podcast", "athlete development podcast", "sports parents podcast",
                      "youth soccer development podcast", "high school athletes recruiting podcast"]


def _yt(conn, tenant_id, transport=None):
    from growth_os import vault
    from growth_os.connectors import youtube
    from growth_os.http import Client
    a = conn.execute("SELECT * FROM platform_accounts WHERE tenant_id=? AND platform='youtube' AND state IN (?,?,?)",
                     (tenant_id, brands.ASSIGNED, brands.ACTIVE, brands.SYNCING)).fetchone()
    if not a:
        raise ValueError("connect and assign the YouTube channel first")
    http, client = Client(conn, tenant_id, transport=transport), vault.load_client("youtube")
    return a, (lambda path, params, q=1: youtube._get(http, conn, tenant_id, a["credential_id"], client,
                                                       f"{youtube.DATA_API}/{path}", params, quota_units=q))


def _dur(iso):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def research_competitors(conn, tenant_id, *, transport=None, queries=COMPETITOR_QUERIES, keep=10):
    """Find comparable channels (YouTube search) and store their recent uploads' public stats. ~550 quota units."""
    a, get = _yt(conn, tenant_id, transport)
    seen = Counter()
    for q in queries:
        for it in get("search", {"part": "snippet", "type": "channel", "q": q, "maxResults": 10}, 100).get("items", []):
            cid = it["snippet"]["channelId"]
            if cid != a["platform_account_id"]:
                seen[cid] += 1
    existing = [r[0] for r in conn.execute("SELECT ref FROM competitors WHERE tenant_id=? AND platform='youtube'", (tenant_id,))]
    ids = list(dict.fromkeys(existing + [c for c, _ in seen.most_common(30)]))
    chans = []
    for i in range(0, len(ids), 50):
        chans += get("channels", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50])}).get("items", [])
    def ok(ch):
        st = ch.get("statistics", {})
        subs, vids = int(st.get("subscriberCount") or 0), int(st.get("videoCount") or 0)
        return MIN_SUBS <= subs <= MAX_SUBS and vids >= 20  # comparable or a step ahead, not national media
    drop = [c["id"] for c in chans if not ok(c)]
    for cid in drop:  # keep the library comparable: remove channels that outgrew / never fit the band
        conn.execute("DELETE FROM competitors WHERE tenant_id=? AND platform='youtube' AND ref=?", (tenant_id, cid))
        conn.execute("DELETE FROM competitor_videos WHERE tenant_id=? AND channel_id=?", (tenant_id, cid))
    chans = sorted([c for c in chans if ok(c)], key=lambda c: (c["id"] not in existing, -seen[c["id"]]))[:keep]
    now = utcnow()
    stored = 0
    for ch in chans:
        name = ch["snippet"]["title"]
        conn.execute("INSERT OR IGNORE INTO competitors VALUES (?,?,?,?)", (tenant_id, "youtube", ch["id"], name))
        up = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not up:
            continue
        vids = [x["contentDetails"]["videoId"] for x in
                get("playlistItems", {"part": "contentDetails", "playlistId": up, "maxResults": 15}).get("items", [])]
        if not vids:
            continue
        for v in get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(vids)}).get("items", []):
            conn.execute("INSERT OR REPLACE INTO competitor_videos VALUES (?,?,?,?,?,?,?,?,?)",
                         (tenant_id, ch["id"], name, v["id"], v["snippet"]["title"], v["snippet"]["publishedAt"],
                          int(v.get("statistics", {}).get("viewCount") or 0), _dur(v.get("contentDetails", {}).get("duration")), now))
            stored += 1
    return {"channels": [c["snippet"]["title"] for c in chans], "videos": stored}


def competition_facts(conn, tenant_id, top=12):
    rows = [dict(r) for r in conn.execute("SELECT * FROM competitor_videos WHERE tenant_id=?", (tenant_id,))]
    if not rows:
        return None
    today = date.today()
    for r in rows:
        age = max(1, (today - date.fromisoformat(r["published_at"][:10])).days) if r["published_at"] else None
        r["views_per_day"] = round(r["views"] / age, 1) if age else None
        r["format"] = "short" if (r["duration_s"] or 0) <= 180 else "long"
    rows = [r for r in rows if r["views_per_day"] is not None]
    ranked, per = [], Counter()
    for r in sorted(rows, key=lambda r: -r["views_per_day"]):
        if per[r["channel_name"]] < 2:  # max 2 per channel so one big channel can't fill the list
            ranked.append(r)
            per[r["channel_name"]] += 1
    best = ranked
    lens = sorted(len(r["title"]) for r in best[: max(5, len(best) // 4)])
    return {"channels": sorted({r["channel_name"] for r in rows}), "videos_seen": len(rows),
            "fetched_at": max(r["fetched_at"] for r in rows),
            "top_videos": [{"channel": r["channel_name"], "title": r["title"], "views": r["views"],
                            "views_per_day": r["views_per_day"], "format": r["format"]} for r in best[:top]],
            "top_title_median_chars": lens[len(lens) // 2] if lens else None,
            "note": "Public view counts of comparable channels' latest uploads. Their impressions and retention are private."}
