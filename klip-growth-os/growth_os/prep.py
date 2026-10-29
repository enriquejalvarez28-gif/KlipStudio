"""Spec v5 additions that sit on top of existing data: recommendation asset
packs, transcript windows, launch cohorts, Shorts-vs-long trend and the source
freshness strip. Deterministic except the optional cached title draft via ai.ask.
"""

import json
import re
from datetime import date, timedelta

from growth_os import ai, analytics, thumbs
from growth_os.db import DATA_DIR, utcnow

NO_REPACKAGE = ("double_down", "funnel")  # winners / funnel fixes keep their packaging
HEADLINE_INSTRUCTIONS = (
    "Write 2 different YouTube thumbnail headlines for the sports interview in INPUT. Each 2-4 words, a complete "
    "thought (never cut mid-phrase), punchy, true to the title (no invented claims or numbers), different from the "
    "title wording. Mark exactly one gold word per headline with *asterisks*. Examples: 'TOO YOUNG TO *LIFT?*', "
    "'SOCCER'S *BIGGEST* MISTAKE'. "
    'Shape: {"headlines":["",""]}'
)
SEO_INSTRUCTIONS = (
    "Write YouTube description opening lines and tags for the video in INPUT (a sports interview podcast). "
    "first_lines: 2 short sentences (max 300 characters) that say what the viewer will learn, naming the guest if given, "
    "using one natural search phrase from INPUT.search_terms or the title. Only facts in INPUT: no invented credentials, "
    "stats, quotes or links. tags: 8-12 specific tags about THIS video's subject (no unrelated topics, no hashtags). "
    'Shape: {"first_lines":"","tags":[""]}'
)
PREP_STRATEGIES = ["search_driven", "curiosity", "hybrid_search_plus_curiosity"]


# ── transcripts (owner drops the .srt/.vtt YouTube Studio offers for download) ──

def transcript_path(tenant_id, asset_id):
    for d in (DATA_DIR / "transcripts" / tenant_id, DATA_DIR / "transcripts"):
        for ext in ("srt", "vtt"):
            p = d / f"{asset_id}.{ext}"
            if p.exists():
                return p
    return None


_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _secs(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_captions(text):
    """SRT or WebVTT → [{"start": s, "end": s, "text": str}] (tags stripped, rolling duplicates merged)."""
    segs = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "")):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            m = _TS.search(ln)
            if m:
                body = " ".join(re.sub(r"<[^>]+>", "", x).strip() for x in lines[i + 1:]).strip()
                if body and not (segs and segs[-1]["text"] == body):
                    segs.append({"start": _secs(*m.groups()[:4]), "end": _secs(*m.groups()[4:]), "text": body})
                break
    return segs


def load_transcript(tenant_id, asset_id):
    p = transcript_path(tenant_id, asset_id)
    if not p:
        return None
    return parse_captions(p.read_text(encoding="utf-8", errors="replace"))


def window(segs, t, before=30, after=60, max_chars=600):
    """Short transcript excerpt around second `t` (spec: ±30–90 s windows, never the full transcript)."""
    if not segs or t is None:
        return None
    parts = [s for s in segs if s["end"] >= t - before and s["start"] <= t + after]
    if not parts:
        return None
    txt = " ".join(s["text"] for s in parts)
    return {"from": int(parts[0]["start"]), "to": int(parts[-1]["end"]),
            "text": txt if len(txt) <= max_chars else txt[:max_chars].rsplit(" ", 1)[0] + " …"}


def attach_windows(events, segs):
    for e in events:
        w = window(segs, e.get("t"))
        if w:
            e["transcript"] = w
    return events


def chapters(segs, duration_s, n=6):
    """Draft chapter markers at even spacing using the first words spoken there (owner renames them)."""
    if not segs or not duration_s or duration_s < 180:
        return []
    out = [{"t": 0, "label": "Intro"}]
    for k in range(1, n):
        t = duration_s * k / n
        s = next((x for x in segs if x["start"] >= t), None)
        if s:
            out.append({"t": int(s["start"]), "label": " ".join(s["text"].split()[:6]) + " …"})
    return out


def _mmss(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


# ── recommendation asset pack ─────────────────────────────────────────

def _keyword(detail, kws):
    terms = [s["term"] for s in detail["search_terms"]]
    if terms:
        return terms[0], "top YouTube search term for this video (measured)"
    low = (detail["video"]["title"] or "").lower()
    hit = next((k for k in kws if k.lower() in low), None)
    if hit:
        return hit, "brand topic keyword found in the title"
    return (kws[0], "first brand topic keyword (no search data yet)") if kws else (None, "no keywords configured")


def draft_titles(title, keyword, guest):
    base = (title or "").split("|")[0].strip()
    kw = (keyword or "").strip()
    has_kw = kw and kw.lower() in base.lower()
    search = base if has_kw or not kw else f"{kw.title()}: {base}"
    curiosity = base if base.endswith("?") else (f"What {guest} Wants You to Know" if guest else f"Why {base}")
    hybrid = f"{base} ({kw.title()})" if kw and not has_kw else (f"{base} | {guest}" if guest else base)
    return [{"strategy": s, "title": t[:70], "why": w, "source": "rule-based draft (no AI); edit before use"}
            for s, t, w in (("search_driven", search, "leads with the phrase viewers already search"),
                            ("curiosity", curiosity, "opens a question the episode answers; keep only if it does"),
                            ("hybrid", hybrid, "keeps the current hook and adds the search phrase"))]


def asset_pack(conn, tenant_id, asset_id, *, diagnosis="", runner=None, thumbnails_wanted=True, title_max=None,
               skip_titles=False):
    """3 titles, 2 thumbnail previews (long-form), SEO draft (first lines, tags, chapters) for one video. Local only."""
    from growth_os import api  # local import: api imports analytics
    d = api.video_detail(conn, tenant_id, asset_id)
    v = d["video"]
    kws = [k for k, _ in analytics.topic_keywords(conn, tenant_id)]
    keyword, kw_basis = _keyword(d, kws)
    guest = thumbs.guest_of(v["title"])
    pack = {"prepared_at": utcnow(), "keyword": keyword, "keyword_basis": kw_basis, "notes": [], "titles": []}
    try:
        if skip_titles:  # description/tags-only jobs don't need title drafts (saves an AI call per video)
            raise LookupError("skip")
        payload = {"title": v["title"], "format": v["format"], "duration_min": round((v["duration_s"] or 0) / 60),
                   "search_terms": [s["term"] for s in d["search_terms"][:8]], "topic_keywords": kws[:10],
                   "strategies": PREP_STRATEGIES, "diagnosis": diagnosis}
        if title_max:
            payload["max_chars"] = title_max
        from growth_os import thumbtext
        tt = thumbtext.read(tenant_id, asset_id)
        if tt:
            payload["thumbnail_text"] = tt
            pack["thumbnail_text"] = tt
        out, meta = ai.ask(conn, tenant_id, f"prep_titles:{asset_id}", payload, ai.TITLE_INSTRUCTIONS, runner=runner)
        pack["titles"] = [dict(x, source=f"AI draft ({meta['model']})") for x in out.get("titles", [])][:3]
        pack["keep_current"] = bool(out.get("keep_current")) and len(v["title"] or "") <= (title_max or 100)
        pack["keep_reason"] = out.get("keep_reason")
    except LookupError:
        pass
    except (ai.AIUnavailable, ValueError, KeyError) as e:
        pack["titles"] = draft_titles(v["title"], keyword, guest)
        pack["notes"].append(f"AI titles unavailable ({str(e)[:80]}); rule-based drafts shown.")
    pack["thumbnails"] = None
    if thumbnails_wanted:
        heads = thumbs.default_headlines(v["title"])
        try:
            out, _ = ai.ask(conn, tenant_id, f"thumb_headlines:{asset_id}", {"title": v["title"], "guest": guest,
                            "search_terms": [x["term"] for x in d["search_terms"][:5]]}, HEADLINE_INSTRUCTIONS, runner=runner)
            hs = [str(h).strip() for h in out.get("headlines", []) if str(h).strip()]
            if len(hs) >= 2 and all(len(h.replace("*", "").split()) <= 5 for h in hs[:2]):
                heads = hs[:2]
        except (ai.AIUnavailable, ValueError, KeyError):
            pass
        try:
            rf = thumbs.recommend_format(conn, tenant_id, asset_id)
            fmt = rf["recommended"]  # previews() degrades to what this episode's own frames can fill
            pack["thumbnails"] = thumbs.previews(conn, tenant_id, asset_id, heads, fmt=fmt)
            pack["thumbnails"]["format_why"] = rf["why"]
        except (ValueError, LookupError) as e:
            pack["notes"].append(f"Thumbnail previews: {e}")
    segs = load_transcript(tenant_id, asset_id) or []
    chs = chapters(segs, v["duration_s"])
    brand = conn.execute("SELECT display_name FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
    show = brand[0] if brand else ""
    base = (v["title"] or "").split("|")[0].strip()
    lead = base + ("" if not base or base[-1] in ".?!" else ".")
    if guest:
        lead += f" {guest} joins {show} to talk {keyword or 'sports'}." if show else f" With {guest}."
    low = (v["title"] or "").lower()
    relevant_kws = [k for k in kws if k.lower() in low]  # only brand topics this video is actually about
    if guest and keyword and kw_basis.startswith("first brand topic"):
        lead = lead.replace(f" to talk {keyword}.", ".")  # don't claim a topic the video may not cover
    ai_seo = {}
    try:
        seo_payload = {"title": v["title"], "guest": guest, "show": show, "format": v["format"],
                       "search_terms": [s["term"] for s in d["search_terms"][:8]], "related_topics": relevant_kws[:6]}
        ai_seo, _ = ai.ask(conn, tenant_id, f"prep_seo:{asset_id}", seo_payload, SEO_INSTRUCTIONS, runner=runner)
        if ai_seo.get("first_lines"):
            lead = str(ai_seo["first_lines"]).strip()[:400]
    except (ai.AIUnavailable, ValueError, KeyError):
        pass
    tags, seen = [], set()
    for t in [s["term"] for s in d["search_terms"][:6]] + list(ai_seo.get("tags") or [])[:10] \
            + ([guest] if guest else []) + ([show] if show else []) + relevant_kws[:4]:
        k = (t or "").strip()
        if k and k.lower() not in seen and len(k) <= 60:
            seen.add(k.lower())
            tags.append(k)
    pack["seo"] = {
        "first_lines": lead.strip(),
        "tags": tags[:12],
        "keyword_in_title": bool(keyword and keyword.lower() in (v["title"] or "").lower()),
        "chapters": [f"{_mmss(c['t'])} {c['label']}" for c in chs],
        "chapters_note": None if chs else ("Chapters need the transcript: download the .srt from YouTube Studio → Subtitles "
                                           f"and save it as data/transcripts/{asset_id}.srt" if (v["duration_s"] or 0) >= 180
                                           else "Shorts don't use chapters."),
        "rules": "Draft only. The first 2 lines show in search; keep the guest's real credentials, no invented claims."}
    return pack


def prepare_rec(conn, tenant_id, rec_id, runner=None):
    """Build the asset pack for a card: 3 titles, 2 thumbnail previews, SEO draft. Nothing is published."""
    r = conn.execute("SELECT * FROM recommendations WHERE id=? AND tenant_id=?", (rec_id, tenant_id)).fetchone()
    if not r:
        raise LookupError("recommendation not found")
    if not r["asset_id"]:
        raise ValueError("this card isn't about a single video, so there is nothing to prepare")
    if r["kind"] in NO_REPACKAGE:
        raise ValueError("this card says keep the current title and thumbnail, so there is nothing to repackage")
    pack = asset_pack(conn, tenant_id, r["asset_id"], diagnosis=r["diagnosis"], runner=runner)
    alts = json.loads(r["alternatives_json"] or "[]")
    alts = alts if isinstance(alts, dict) else {"items": alts}
    alts["prepared"] = pack
    conn.execute("UPDATE recommendations SET alternatives_json=? WHERE id=?", (json.dumps(alts), rec_id))
    if (r["workflow"] or "suggested") == "suggested":
        analytics.move_rec(conn, tenant_id, rec_id, "prepared", "operator", "asset pack prepared (local, not published)")
    return pack


# ── launch cohorts: views at day 1/3/7/28 since publish ───────────────

COHORT_POINTS = (1, 3, 7, 28)


def cohorts(conn, tenant_id, fmt=None, limit=12):
    rows = conn.execute("""SELECT m.asset_id, m.period_start d, m.metric_name k, m.value FROM metrics m
                           WHERE m.tenant_id=? AND m.grain='video_day'""", (tenant_id,)).fetchall()
    vids = {v["asset_id"]: v for v in analytics.videos(conn, tenant_id)}
    acc = {}
    for r in rows:
        acc.setdefault(r["asset_id"], {}).setdefault(r["d"], {})[r["k"]] = r["value"]
    out = []
    for aid, days in acc.items():
        v = vids.get(aid)
        if not v or not v["published_at"] or (fmt and v["format"] != fmt):
            continue
        pub = date.fromisoformat(v["published_at"][:10])
        pts = {}
        for n in COHORT_POINTS:
            through = pub + timedelta(days=n - 1)
            if through > date.today() - timedelta(days=3):
                pts[n] = None  # not reached yet / YouTube data lag
                continue
            vs = [x.get("views", 0) for d, x in days.items() if date.fromisoformat(d) <= through]
            mins = [x.get("estimatedMinutesWatched", 0) for d, x in days.items() if date.fromisoformat(d) <= through]
            pts[n] = {"views": int(sum(vs)), "watch_hours": round(sum(mins) / 60, 1)}
        out.append({"asset_id": aid, "title": v["title"], "format": v["format"], "published_at": v["published_at"][:10],
                    "points": {str(k): x for k, x in pts.items()}})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return {"items": out[:limit], "points": list(COHORT_POINTS),
            "note": "Cumulative views from publish day through day N (YouTube Analytics, per-video daily). "
                    "Blank = that day hasn't happened yet or is inside YouTube's 2–3 day lag."}


# ── Shorts vs long-form daily trend + freshness strip ─────────────────

def ctype_trend(conn, tenant_id, days=90):
    start = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""SELECT period_start d, asset_id a, metric_name k, value FROM metrics WHERE tenant_id=?
                           AND grain='day_ctype' AND period_start>=? ORDER BY period_start""", (tenant_id, start)).fetchall()
    by = {}
    for r in rows:
        key = "shorts" if r["a"].endswith("SHORTS") else "long" if r["a"].endswith("VIDEO_ON_DEMAND") else "other"
        dd = by.setdefault(r["d"], {"d": r["d"], "shorts_views": 0, "long_views": 0, "shorts_hours": 0.0, "long_hours": 0.0})
        if key == "other":
            continue
        if r["k"] == "views":
            dd[f"{key}_views"] += int(r["value"])
        else:
            dd[f"{key}_hours"] = round(dd[f"{key}_hours"] + r["value"] / 60, 2)
    return list(by.values())


def freshness_strip(conn, tenant_id):
    def one(sql, *a):
        r = conn.execute(sql, (tenant_id, *a)).fetchone()
        return r[0] if r else None
    return [
        {"source": "YouTube Analytics", "as_of": one("SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day' AND platform='youtube'"),
         "note": "daily totals; YouTube lags 2–3 days"},
        {"source": "Impressions & CTR (Reporting API)", "as_of": one("SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day_video' AND metric_name='videoThumbnailImpressions'"),
         "note": "daily files arrive ~2 days late"},
        {"source": "Retention curves", "as_of": one("SELECT MAX(fetched_at) FROM metrics WHERE tenant_id=? AND grain='retention_bucket'")},
        {"source": "Last sync", "as_of": one("SELECT MAX(fetched_at) FROM metrics WHERE tenant_id=? AND platform='youtube'"),
         "note": "when this app last pulled data"},
    ]
