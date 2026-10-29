"""Thumbnail concepts for new episodes (proposals only — nothing is uploaded).

1. Transcript: the episode's captions (downloaded from YouTube when the app has
   write access, otherwise a .srt/.vtt the owner drops in data/transcripts/).
2. Moments: deterministic candidate windows (retention replays/strong points +
   lines with questions, numbers, strong claims) → the model picks the 5
   strongest (emotional / controversial / educational / surprising). Every
   quote must appear word for word in the transcript or it is dropped.
3. Five concepts in five different layouts (guest-only, guest + host, sports
   documentary, editorial, three-person conversation) — only layouts this
   episode's real photos can fill. Headlines are 2–4 words and complement the
   title instead of repeating it.
4. The three most distinct (different layout AND different moment) are
   recommended for YouTube's native Test & Compare, which the owner starts in
   YouTube Studio. Thumbnails on the channel are never changed by this module.
"""

import json
import re

from growth_os import ai, analytics, cast, prep, thumbs
from growth_os.db import DATA_DIR, new_id, utcnow

LAYOUTS = {"guest": "Guest-only", "host_guest": "Guest + host", "documentary": "Sports documentary",
           "editorial": "Editorial", "trio": "Three-person conversation"}
SIGNAL = re.compile(r"\?|!|\b\d+%?|\b(never|always|nobody|everybody|everyone|worst|best|biggest|mistake|truth|secret|"
                    r"wrong|quit|crazy|honest(ly)?|real(ly)? (problem|reason)|nobody talks|changed my life|"
                    r"cried|broke|lost|fired|cut|injur\w*|scholarship|d1|pro|million)\b", re.I)
MAX_WINDOWS = 16


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (s or "").lower())).strip()


def fetch_captions(conn, tenant_id, asset_id, transport=None):
    """Download the episode's captions from YouTube (needs write access: captions.download). Returns path or None."""
    from growth_os import autopilot
    if not autopilot.write_status(conn, tenant_id)["has_write"]:
        return None
    _, _, call = autopilot._session(conn, tenant_id, transport)
    tracks = call("GET", "https://www.googleapis.com/youtube/v3/captions", params={"part": "snippet", "videoId": asset_id},
                  quota_units=50).get("items", [])
    tracks.sort(key=lambda t: (t["snippet"].get("language", "")[:2] != "en", t["snippet"].get("trackKind") == "asr"))
    if not tracks:
        return None
    from growth_os import vault
    from growth_os.connectors import youtube
    a, http, _ = autopilot._session(conn, tenant_id, transport)
    tok = youtube._access_token(http, conn, tenant_id, a["credential_id"], vault.load_client("youtube"))
    raw = http.download(f"https://www.googleapis.com/youtube/v3/captions/{tracks[0]['id']}?tfmt=srt",
                        headers={"Authorization": f"Bearer {tok}"}, log_name="youtube.captions.download")
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else None
    if not text:
        return None
    p = DATA_DIR / "transcripts" / tenant_id / f"{asset_id}.srt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def candidate_windows(segs, events, duration_s):
    """Up to MAX_WINDOWS short transcript windows worth considering, spread across the episode."""
    scored = []
    for e in events:  # where viewers rewound or stayed unusually well
        if e.get("t") is not None and e["kind"] in ("replay", "strong"):
            w = prep.window(segs, e["t"], before=15, after=25, max_chars=320)
            if w:
                scored.append((3.0 if e["kind"] == "replay" else 2.0, w["from"], w, f"retention {e['kind']}"))
    for i in range(0, len(segs), 3):  # sliding ~3-caption chunks with strong-language signals
        chunk = segs[i:i + 4]
        text = " ".join(s["text"] for s in chunk)
        hits = len(SIGNAL.findall(text))
        if hits:
            scored.append((min(2.5, 0.6 * hits), int(chunk[0]["start"]),
                           {"from": int(chunk[0]["start"]), "to": int(chunk[-1]["end"]), "text": text[:320]}, "strong language"))
    scored.sort(key=lambda x: -x[0])
    out, taken = [], []
    for score, t, w, why in scored:
        if all(abs(t - x) >= 60 for x in taken):
            taken.append(t)
            out.append({"from": w["from"], "to": w["to"], "text": w["text"], "signal": why})
        if len(out) >= MAX_WINDOWS:
            break
    return sorted(out, key=lambda w: w["from"])


MOMENT_INSTRUCTIONS = (
    "You pick thumbnail-worthy moments from a sports interview podcast. INPUT.windows are short transcript excerpts. "
    "Choose the 5 strongest DIFFERENT moments: emotional, controversial, educational or surprising. For each give the "
    "window index, the type, why it would make someone click, and a short quote copied EXACTLY (word for word, 4-14 "
    "words) from that window's text. Never paraphrase inside 'quote' and never invent anything. "
    'Shape: {"moments":[{"i":0,"type":"emotional|controversial|educational|surprising","why":"","quote":""}]}'
)

CONCEPT_INSTRUCTIONS = (
    "You are a YouTube thumbnail art director for RYJ (Respect Your Journey), a sports interview podcast. Brand: black, "
    "white and gold, bold condensed type. Using INPUT.moments, propose exactly one concept per layout in "
    "INPUT.layouts (they must be genuinely different ideas, not variations). Each concept: layout, moment index, a 2-4 "
    "word headline (mark one gold word with *asterisks*; readable on a phone; must COMPLEMENT INPUT.title, never repeat "
    "it; must be true to the moment — no invented quotes, reactions, stats or accomplishments), a one-line angle, and "
    "why it fits this audience. Rank them best first. "
    'Shape: {"concepts":[{"layout":"","moment":0,"headline":"","angle":"","why":""}]}'
)


def find_moments(conn, tenant_id, asset_id, segs, runner=None):
    vids = analytics.videos(conn, tenant_id)
    v = next(x for x in vids if x["asset_id"] == asset_id)
    curve = analytics.retention_curves(conn, tenant_id).get(asset_id, [])
    events = analytics.retention_events(curve, None, v["duration_s"], v["metrics"].get("views"))
    wins = candidate_windows(segs, events, v["duration_s"])
    if not wins:
        return []
    picked = []
    try:
        out, _ = ai.ask(conn, tenant_id, f"moments:{asset_id}", {"title": v["title"], "windows": [
            {"i": i, "t": f"{w['from'] // 60}:{w['from'] % 60:02d}", "text": w["text"]} for i, w in enumerate(wins)]},
            MOMENT_INSTRUCTIONS, runner=runner)
        for m in out.get("moments", []):
            i = m.get("i")
            if not isinstance(i, int) or not 0 <= i < len(wins):
                continue
            q = (m.get("quote") or "").strip().strip('"“”')
            if q and _norm(q) not in _norm(wins[i]["text"]):
                q = ""  # not verbatim → never shown as a quote
            picked.append({"t": wins[i]["from"], "type": m.get("type", ""), "why": m.get("why", ""), "quote": q,
                           "excerpt": wins[i]["text"]})
    except (ai.AIUnavailable, ValueError, KeyError):
        pass
    if not picked:  # rule-based: strongest windows, excerpt only
        picked = [{"t": w["from"], "type": w["signal"], "why": "", "quote": "", "excerpt": w["text"]} for w in wins[:5]]
    return picked[:5]


def feasible_layouts(people):
    hosts = {"jamar", "enrique"} & set(people)
    out = ["guest", "documentary", "editorial"]
    if hosts:
        out.insert(1, "host_guest")
    if len(hosts) == 2 and "guest" in people:
        out.append("trio")
    return out


def _render(layout, src, headline, people, frames, out_path, byline):
    if layout in ("guest", "host_guest", "trio"):
        return thumbs.render(src, headline, fmt=layout, cast=people, out_path=out_path)
    if layout == "documentary":
        frame = frames[len(frames) // 2] if frames else src
        return thumbs.render_documentary(frame, headline, orig_path=src, kicker=byline, out_path=out_path)
    portrait, focus = people.get("guest", (src, 0.5))
    return thumbs.render_editorial(portrait, headline, orig_path=src, byline=byline, focus=focus, out_path=out_path)


def generate(conn, tenant_id, asset_id, *, runner=None, transport=None):
    v = conn.execute("SELECT * FROM assets WHERE tenant_id=? AND asset_id=?", (tenant_id, asset_id)).fetchone()
    if not v:
        raise LookupError("video not found")
    if v["format"] != "long_form":
        raise ValueError("concepts are for full episodes (YouTube sets Shorts thumbnails from frames)")
    src = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if not src.exists():
        raise ValueError("the episode's thumbnail hasn't been downloaded yet (next sync)")
    segs, tsrc = prep.load_transcript(tenant_id, asset_id), "file"
    if not segs:
        try:
            if fetch_captions(conn, tenant_id, asset_id, transport):
                segs, tsrc = prep.load_transcript(tenant_id, asset_id), "youtube captions"
        except Exception:
            segs = None
    if not segs:
        segs, tsrc = [], "none"
    people = cast.load(tenant_id, asset_id)
    if not people and cast.available()[0]:
        cast.build(conn, tenant_id, asset_id)
        people = cast.load(tenant_id, asset_id)
    frames = sorted((DATA_DIR / "frames" / tenant_id).glob(f"{asset_id}_*.jpg"))
    moments = find_moments(conn, tenant_id, asset_id, segs, runner) if segs else []
    layouts = feasible_layouts(people)
    guest = thumbs.guest_of(v["title"]) or ""
    concepts = []
    try:
        out, _ = ai.ask(conn, tenant_id, f"concepts:{asset_id}", {
            "title": v["title"], "guest": guest, "layouts": layouts, "people_in_photos": sorted(people),
            "moments": [{"i": i, "type": m["type"], "quote": m["quote"], "excerpt": m["excerpt"][:200]}
                        for i, m in enumerate(moments)] or [{"i": 0, "type": "title", "excerpt": v["title"]}]},
            CONCEPT_INSTRUCTIONS, runner=runner)
        concepts = [c for c in out.get("concepts", []) if c.get("layout") in layouts]
    except (ai.AIUnavailable, ValueError, KeyError):
        pass
    seen, final = set(), []
    for c in concepts:  # one per layout, in the model's ranking
        if c["layout"] not in seen:
            seen.add(c["layout"])
            final.append(c)
    heads = thumbs.default_headlines(v["title"])
    for lay in layouts:  # fill any layout the model skipped (or all of them without AI)
        if lay not in seen:
            final.append({"layout": lay, "moment": len(final) % max(1, len(moments)) if moments else None,
                          "headline": heads[len(final) % 2], "angle": "rule-based draft", "why": ""})
    out_dir = DATA_DIR / "concepts" / tenant_id / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().replace(":", "").replace("-", "")[:15]
    for k, c in enumerate(final[:5]):
        name = f"{stamp}-{k + 1}-{c['layout']}.jpg"
        _render(c["layout"], src, c["headline"], people, frames, out_dir / name, guest)
        c["file"], c["url"] = name, f"/concept/{tenant_id}/{asset_id}/{name}"
        c["label"] = LAYOUTS[c["layout"]]
        mi = c.get("moment")
        c["moment_detail"] = moments[mi] if isinstance(mi, int) and 0 <= mi < len(moments) else None
    final = final[:5]
    picks, used_m, used_l = [], set(), set()
    for c in final:  # most distinct three: new layout family AND a different moment
        fam = "people" if c["layout"] in ("guest", "host_guest", "trio") else c["layout"]
        m = c.get("moment")
        if fam in used_l and len(final) > 3:
            continue
        if m is not None and m in used_m and len(final) > 3:
            continue
        picks.append(c["file"])
        used_l.add(fam)
        used_m.add(m)
        if len(picks) == 3:
            break
    for c in final:
        if len(picks) < 3 and c["file"] not in picks:
            picks.append(c["file"])
    cid = new_id("tc_")
    conn.execute("INSERT INTO thumb_concepts VALUES (?,?,?,?,?,?,?,?,?)",
                 (cid, tenant_id, asset_id, utcnow(), tsrc, json.dumps(moments), json.dumps(final), json.dumps(picks), "proposed"))
    return latest(conn, tenant_id, asset_id)


def latest(conn, tenant_id, asset_id):
    r = conn.execute("SELECT * FROM thumb_concepts WHERE tenant_id=? AND asset_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                     (tenant_id, asset_id)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "created_at": r["created_at"], "transcript": r["transcript_source"],
            "moments": json.loads(r["moments_json"]), "concepts": json.loads(r["concepts_json"]),
            "picks": json.loads(r["picks_json"]),
            "note": ("Proposals only. Your current thumbnails are not changed. To test, upload the 3 recommended images "
                     "in YouTube Studio → the video → Test & Compare."),
            "transcript_note": None if r["transcript_source"] != "none" else
            ("No transcript yet: concepts use the title only. Grant write access (captions download) or save the .srt "
             f"from YouTube Studio → Subtitles as data/transcripts/{tenant_id}/{asset_id}.srt.")}


def for_new_episodes(conn, tenant_id, days=7, runner=None):
    """Daily: concepts for long-form episodes published in the last `days` that don't have any yet."""
    made = []
    for r in conn.execute("""SELECT asset_id FROM assets WHERE tenant_id=? AND format='long_form'
                             AND published_at >= date('now', ?) AND asset_id NOT IN
                             (SELECT asset_id FROM thumb_concepts WHERE tenant_id=?)""",
                          (tenant_id, f"-{days} days", tenant_id)).fetchall():
        try:
            generate(conn, tenant_id, r["asset_id"], runner=runner)
            made.append(r["asset_id"])
        except Exception:  # one episode must not stop the others
            continue
    return made
