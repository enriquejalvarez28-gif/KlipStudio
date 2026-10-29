"""RYJ thumbnail strategy: formats, format performance, recommendations,
experiments and rendered previews (owner directive 2026-10-15).

Formats
  guest      Guest-focused: the guest is the primary visual.
  host_guest Host + guest: a host whose reaction/question/disagreement adds to the story.
  host_led   Host-led: both hosts, for debates, rankings, commentary, analysis.

Rules baked in
  * Preserve the RYJ identity: black left panel, tall white condensed caps,
    gold emphasis, RYJ logo, authentic portrait on the right.
  * Previews reuse authentic photography (crops/scales only). Faces are never
    altered. Host formats need real host photos in data/brand/hosts/.
  * Nothing is ever uploaded or replaced: previews are local files. Changing a
    live thumbnail needs the owner's approval (and write access, which is off).
  * Hosts are never recommended just for branding when the guest is the hook.
"""

import json
import re
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from growth_os import analytics
from growth_os.db import DATA_DIR, new_id, utcnow

MIN_IMPRESSIONS = 100  # below this a video's CTR is noise (e.g. 0 clicks on 12 impressions)
FORMATS = {"guest": "Guest-focused", "host_guest": "Host + guest", "host_led": "Host-led", "trio": "Host + co-host + guest",
           "viral": "Viral cut-out (big faces, outline, few words)"}
W, H = 1280, 720
ASSETS = Path(__file__).resolve().parent / "assets"
BRAND_DIR = DATA_DIR / "brand"
FALLBACK_GOLD = (0xF0, 0xB0, 0x00)  # sampled from RYJ thumbnails (≈ #F0B000); brand file can override

HOST_LED_WORDS = re.compile(r"\b(rank|ranks|ranking|mount rushmore|top \d+|best|worst|debate|vs\.?|versus|hot take|"
                            r"predict|prediction|picks?|goat|who wins|reacts?|breakdown|analysis)\b", re.I)
HOST_GUEST_WORDS = re.compile(r"\b(disagree|disagrees|push back|pushback|challenge|debate|argue|argument|controversial|"
                              r"hot take|vs\.?|versus)\b", re.I)


# ── classification ───────────────────────────────────────────────────

def guest_of(title):
    return analytics._guest(title)


def suggest_format(title):
    """Heuristic from the title/topic only (no face detection installed)."""
    guest = guest_of(title)
    t = title or ""
    if HOST_LED_WORDS.search(t) and not guest:
        return "host_led", "ranking / debate / commentary topic with no named guest"
    if guest and HOST_GUEST_WORDS.search(t):
        return "host_guest", "named guest and a question/disagreement angle where a host reaction adds tension"
    if guest:
        return "guest", f"{guest} is the hook; the guest leads the thumbnail"
    if HOST_LED_WORDS.search(t):
        return "host_led", "ranking / debate topic"
    return "guest", "default RYJ format"


def tags(conn, tenant_id):
    """Owner-confirmed format per video (latest wins)."""
    out = {}
    for r in conn.execute("SELECT asset_id, value, observed_at FROM asset_history WHERE tenant_id=? AND field='thumb_format' "
                          "ORDER BY observed_at", (tenant_id,)):
        out[r[0]] = r[1]
    return out


def set_tag(conn, tenant_id, asset_id, fmt):
    if fmt not in FORMATS:
        raise ValueError("unknown format")
    if not conn.execute("SELECT 1 FROM assets WHERE tenant_id=? AND asset_id=?", (tenant_id, asset_id)).fetchone():
        raise LookupError("video not found for this brand")
    conn.execute("INSERT OR REPLACE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",
                 (tenant_id, "youtube", asset_id, "thumb_format", fmt, f"{fmt}:{utcnow()}"[:16], utcnow(), "owner"))
    return {"asset_id": asset_id, "format": fmt}


# ── performance by format ─────────────────────────────────────────────

def format_performance(conn, tenant_id):
    vids = analytics.videos(conn, tenant_id)
    tg = tags(conn, tenant_id)
    groups = {}
    for v in vids:
        if (v["age_days"] or 0) < 7:
            continue
        fmt = tg.get(v["asset_id"])
        source = "owner" if fmt else "suggested"
        fmt = fmt or suggest_format(v["title"])[0]
        key = (v["format"], fmt)
        groups.setdefault(key, {"videos": [], "owner_tagged": 0})
        groups[key]["videos"].append(v)
        groups[key]["owner_tagged"] += source == "owner"
    rows = []
    for (vf, fmt), g in sorted(groups.items()):
        vs = g["videos"]

        def med(get):
            xs = [get(v) for v in vs if get(v) is not None]
            return round(statistics.median(xs), 2) if xs else None
        rows.append({"video_format": vf, "thumb_format": fmt, "label": FORMATS[fmt], "n": len(vs),
                     "owner_tagged": g["owner_tagged"],
                     "median_ctr": med(lambda v: v["metrics"].get("videoThumbnailImpressionsClickRate")
                                       if (v["metrics"].get("videoThumbnailImpressions") or 0) >= MIN_IMPRESSIONS else None),
                     "ctr_videos": sum(1 for v in vs if (v["metrics"].get("videoThumbnailImpressions") or 0) >= MIN_IMPRESSIONS),
                     "median_impressions": med(lambda v: v["metrics"].get("videoThumbnailImpressions")),
                     "median_views_per_day": med(lambda v: v["views_per_day"]),
                     "median_pct_viewed": med(lambda v: v["metrics"].get("averageViewPercentage"))})
    return {"rows": rows,
            "note": f"CTR counts only videos with ≥{MIN_IMPRESSIONS} impressions. Compare within Shorts or within long-form only. Groups under 5 videos, or CTR from only a few days of "
                    "reach data, are not evidence that one format wins. Untagged videos use the title-based suggestion."}


def recommend_format(conn, tenant_id, asset_id):
    vids = analytics.videos(conn, tenant_id)
    v = next((x for x in vids if x["asset_id"] == asset_id), None)
    if not v:
        raise LookupError("video not found for this brand")
    base, why = suggest_format(v["title"])
    current = tags(conn, tenant_id).get(asset_id)
    perf = [r for r in format_performance(conn, tenant_id)["rows"] if r["video_format"] == v["format"]]
    evidence = None
    best = max((r for r in perf if r["median_ctr"] is not None and r["ctr_videos"] >= 5), key=lambda r: r["median_ctr"], default=None)
    mine = next((r for r in perf if r["thumb_format"] == base), None)
    test = None
    if best and mine and best["thumb_format"] != base and mine["median_ctr"] is not None \
            and best["median_ctr"] > mine["median_ctr"] * 1.15 and mine["ctr_videos"] >= 5:
        evidence = (f"{best['label']} thumbnails on {('Shorts' if v['format'] == 'short_heuristic' else 'long-form')} show a "
                    f"median CTR of {best['median_ctr']:.1f}% vs {mine['median_ctr']:.1f}% (n={best['n']} vs {mine['n']}).")
        if not (base == "guest" and best["thumb_format"] != "guest" and guest_of(v["title"])):
            test = best["thumb_format"]
        else:
            evidence += " The guest is this episode's hook, so a host format is only worth a test, not a switch."
            test = best["thumb_format"]
    return {"asset_id": asset_id, "current_format": current, "recommended": base, "label": FORMATS[base], "why": why,
            "evidence": evidence or "Not enough CTR history per format yet; the recommendation follows the episode's content.",
            "test_format": test, "guest": guest_of(v["title"]),
            "hosts_available": [p.stem for p in host_photos()]}


# ── experiments ───────────────────────────────────────────────────────

def experiments(conn, tenant_id):
    rows = []
    for r in conn.execute("SELECT * FROM thumb_experiments WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)):
        d = dict(r)
        d["variants"] = json.loads(d.pop("variants_json") or "[]")
        d["result"] = json.loads(d.pop("result_json") or "{}")
        rows.append(d)
    return rows


def save_experiment(conn, tenant_id, body):
    asset_id = str(body.get("asset_id", ""))
    if not conn.execute("SELECT 1 FROM assets WHERE tenant_id=? AND asset_id=?", (tenant_id, asset_id)).fetchone():
        raise LookupError("video not found for this brand")
    method = body.get("method", "native")
    if method not in ("native", "sequential"):
        raise ValueError("method must be native (YouTube Test & Compare) or sequential")
    eid = body.get("id") or new_id("exp_")
    variants = [{"format": x.get("format"), "label": str(x.get("label", ""))[:80], "file": str(x.get("file", ""))[:200],
                 "watch_time_share": x.get("watch_time_share")} for x in (body.get("variants") or [])][:3]
    result = {"winner": body.get("winner"), "notes": str(body.get("notes", ""))[:500],
              "caveat": None if method == "native" else "Sequential change: timing and other factors are confounded."}
    conn.execute("""INSERT OR REPLACE INTO thumb_experiments (id, tenant_id, asset_id, method, status, started_at, ended_at,
                    variants_json, result_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,COALESCE((SELECT created_at FROM
                    thumb_experiments WHERE id=?), ?))""",
                 (eid, tenant_id, asset_id, method, body.get("status", "planned"), body.get("started_at"), body.get("ended_at"),
                  json.dumps(variants), json.dumps(result), eid, utcnow()))
    return {"id": eid}


# ── rendering ─────────────────────────────────────────────────────────

def _font(size):
    for f in [*sorted(BRAND_DIR.glob("fonts/*.ttf")), *sorted(BRAND_DIR.glob("fonts/*.otf")),
              ASSETS / "fonts" / "Anton-Regular.woff",
              Path("C:/Windows/Fonts/impact.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf")]:
        try:
            if Path(f).exists():
                return ImageFont.truetype(str(f), size)
        except OSError:
            continue
    return ImageFont.load_default()


def brand_gold(img=None):
    try:
        cfg = json.loads((BRAND_DIR / "brand.json").read_text())
        h = cfg["gold"].lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    if img is not None:  # sample the gold already used in this thumbnail
        px = [p for p in img.convert("RGB").resize((320, 180)).getdata() if p[0] > 190 and 130 < p[1] < 200 and p[2] < 70]
        if len(px) > 40:
            return tuple(int(statistics.median(c)) for c in zip(*px))
    return FALLBACK_GOLD


def host_photos():
    return sorted([p for p in (BRAND_DIR / "hosts").glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")])


def host_focus():
    """Optional data/brand/hosts.json: {"enrique": 0.42} = where the face sits across each host photo (0–1)."""
    try:
        return {k: float(v) for k, v in json.loads((BRAND_DIR / "hosts.json").read_text()).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _cover(img, w, h, focus_x=0.5):
    """Scale-and-crop to fill w×h (no distortion, no face edits)."""
    s = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x = int((r.width - w) * focus_x)
    return r.crop((x, (r.height - h) // 2, x + w, (r.height - h) // 2 + h))


def _text_edge(o):
    """Rightmost column of the original's left-panel headline (white/gold glyphs on black)."""
    small = o.resize((320, 180))
    px = small.load()
    last = 0
    for x in range(int(320 * 0.30), int(320 * 0.70)):
        bright = dark = 0
        for y in range(25, 160):
            r, g, b = px[x, y]
            lum = (r + g + b) / 3
            if lum > 200 or (r > 190 and g > 130 and b < 80):
                bright += 1
            elif lum < 45:
                dark += 1
        if bright >= 3 and dark > 135 * 0.55:
            last = x
    return int(last * W / 320)


def _portrait_from_original(orig):
    """RYJ originals put the person on the right; reuse that region, starting
    after the old headline so none of its letters leak into the preview."""
    o = orig.convert("RGB").resize((W, H))
    x0 = max(int(W * 0.48), _text_edge(o) + 24)
    return o.crop((x0, 0, W, H))


def _logo_from_original(orig):
    saved = BRAND_DIR / "logo.jpg"  # a clean RYJ badge cut once from a good thumbnail: always preferred
    if saved.exists():
        return Image.open(saved).convert("RGB")
    return _logo_crop(orig)


def _logo_crop(orig):
    o = orig.convert("RGB").resize((W, H))
    box = o.crop((30, 20, 190, 170))
    lum = [sum(p) / 3 for p in box.resize((40, 38)).getdata()]
    # A logo region has some bright pixels on a dark field; plain black → no logo.
    bright = sum(1 for x in lum if x > 150)
    return box if 25 < bright < 520 else None  # a big bright block is old headline text, not the logo


def _wrap(draw, words, font, max_w):
    lines, cur = [], []
    for w in words:
        trial = cur + [w]
        if cur and draw.textlength(" ".join(x for x, _ in trial), font=font) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _layout(draw, lines_in, max_w, max_h, max_lines=3, start=170):
    """Biggest size where the words fit in ≤ max_lines lines (RYJ uses big 3-line stacks).
    Manual '/' breaks are kept when they fit; otherwise words re-wrap."""
    words = [w for line in lines_in for w in line]
    for size in range(start, 44, -4):
        f = _font(size)
        lh = int(size * 1.0)
        manual = lines_in if len(lines_in) > 1 else None
        for cand in ([manual] if manual else []) + [_wrap(draw, words, f, max_w)]:
            if len(cand) <= max_lines and lh * len(cand) <= max_h and \
                    max(draw.textlength(" ".join(w for w, _ in ln), font=f) for ln in cand) <= max_w:
                return f, lh, cand
    f = _font(44)
    return f, 46, _wrap(draw, words, f, max_w)[:max_lines]


def parse_headline(text, max_lines=3):
    """'ARE ATHLETES / MORE THAN / *THEIR MEDALS?*' → lines of (word, gold?).
    '/' breaks lines; *…* marks gold. Without '/', words are balanced across
    lines; without '*', the last line is gold (RYJ default)."""
    text = re.sub(r"\s+", " ", (text or "").strip().upper())
    if not text:
        return []
    text = re.sub(r"\*([^*]+)\*([?!.,]+)", r"*\1\2*", text)  # keep "?" with its gold word
    gold_spans = set()
    toks, gold = [], False
    for raw in re.split(r"(\*|/)", text):
        if raw == "*":
            gold = not gold
            continue
        if raw == "/":
            toks.append(("/", False))
            continue
        for w in raw.split():
            toks.append((w, gold))
            if gold:
                gold_spans.add(len(toks) - 1)
    if any(t == "/" for t, _ in toks):
        lines, cur = [], []
        for t in toks:
            if t[0] == "/":
                if cur:
                    lines.append(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            lines.append(cur)
    else:
        words = [t for t in toks]
        n = min(max_lines, max(1, round(len(words) / 2.2)))
        per = -(-len(words) // n)
        lines = [words[i:i + per] for i in range(0, len(words), per)]
    if not gold_spans and lines:
        lines[-1] = [(w, True) for w, _ in lines[-1]]
    return lines[:max_lines]


def fit_format(fmt, cast):
    """Degrade to a layout this episode's own frames can fill (never borrow another episode's photo)."""
    has = set(cast or {})
    hosts = has & {"jamar", "enrique"}
    if fmt == "trio" and not ({"guest"} <= has and len(hosts) == 2):
        fmt = "host_guest"
    if fmt == "host_led" and len(hosts) < 2:
        fmt = "host_guest" if hosts else "guest"
    if fmt == "host_guest" and not hosts:
        fmt = "guest"
    return fmt


def render(orig_path, headline, *, fmt="guest", credential="", host_paths=(), gold=None, out_path=None, cast=None):
    """Render one 1280×720 RYJ-style preview from authentic imagery."""
    orig = Image.open(orig_path)
    gold = gold or brand_gold(orig)
    canvas = Image.new("RGB", (W, H), (8, 8, 8))
    portrait = _portrait_from_original(orig)
    if cast is not None:
        fmt = fit_format(fmt, cast)
    multi = fmt != "guest" and (cast is not None or host_paths)
    right_x = int(W * 0.44) if fmt == "trio" else (int(W * 0.48) if multi else min(int(W * 0.50), W - portrait.width))
    pw, ph = W - right_x, H
    if not multi:
        canvas.paste(portrait, (W - portrait.width, 0))
    elif cast is not None:
        def im(role):
            path, focus = cast[role]
            return Image.open(path).convert("RGB"), focus
        host = next((r for r in ("enrique", "jamar") if r in cast), None)
        if fmt == "trio":
            people, widths = [im("jamar"), im("guest"), im("enrique")], [int(pw * 0.3), int(pw * 0.4)]
            widths.append(pw - sum(widths))
        elif fmt == "host_led":
            people, widths = [im("jamar"), im("enrique")], [pw // 2, pw - pw // 2]
        else:  # host_guest: the episode's guest frame if found, else the current thumbnail's guest
            g = im("guest") if "guest" in cast else (_portrait_from_original(orig), 0.5)
            people, widths = [g, im(host)], [int(pw * 0.55), pw - int(pw * 0.55)]
        x = right_x
        for (img, fx), w in zip(people, widths):
            canvas.paste(_cover(img, w, ph, fx), (x, 0))
            x += w
    else:
        # Split the right panel: guest keeps the larger share; hosts come from real host photos only.
        hints = host_focus()
        hosts = list(host_paths[: (1 if fmt == "host_guest" else 2)])
        people = ([(_portrait_from_original(orig), 0.5)] if fmt == "host_guest" else []) + \
            [(Image.open(p).convert("RGB"), hints.get(Path(p).stem, 0.5)) for p in hosts]
        widths = [int(pw * 0.55), pw - int(pw * 0.55)] if fmt == "host_guest" else [pw // len(people)] * len(people)
        x = right_x
        for (img, fx), w in zip(people, widths):
            canvas.paste(_cover(img, w, ph, fx), (x, 0))
            x += w
    # Fade the photo into the black panel (same treatment as the originals).
    fade = Image.new("L", (W, H), 0)
    fd = ImageDraw.Draw(fade)
    fw = 60 if multi else 220  # narrow fade when several faces share the panel
    for i in range(fw):
        fd.line([(right_x + i, 0), (right_x + i, H)], fill=int(255 * (1 - i / fw) ** 1.6))
    fd.rectangle([0, 0, right_x, H], fill=255)
    canvas = Image.composite(Image.new("RGB", (W, H), (8, 8, 8)), canvas, fade)
    d = ImageDraw.Draw(canvas)
    logo = _logo_from_original(orig)
    if logo:
        canvas.paste(logo, (30, 20))
    lines = parse_headline(headline)
    top = 215 if logo else 150
    bottom = H - (150 if credential else 70)
    f, lh, lines = _layout(d, lines, right_x - 110, bottom - top)
    y = top + max(0, (bottom - top - lh * len(lines)) // 2)
    for line in lines:
        x = 62
        for w, g in line:
            d.text((x, y), w, font=f, fill=gold if g else (255, 255, 255))
            x += d.textlength(w + " ", font=f)
        y += lh
    if credential:
        cf = _font(30)
        tw = d.textlength(credential.upper(), font=cf)
        d.rounded_rectangle([56, H - 82, 56 + tw + 36, H - 32], radius=8, fill=gold)
        d.text((74, H - 77), credential.upper(), font=cf, fill=(14, 14, 14))
    if out_path:
        canvas.save(out_path, "JPEG", quality=92)
    return canvas


def contact_sheet(original, variants, labels, out_path):
    """Old + variants at full size and at YouTube mobile size (≈ 246×138)."""
    full_w, mob_w = 560, 246
    full_h, mob_h = full_w * 9 // 16, mob_w * 9 // 16
    n = 1 + len(variants)
    sheet = Image.new("RGB", (40 + n * (full_w + 30), 120 + full_h + mob_h + 90), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    f = _font(26)
    for i, (img, lab) in enumerate(zip([original] + list(variants), ["CURRENT (live)"] + labels)):
        x = 30 + i * (full_w + 30)
        d.text((x, 30), lab, font=f, fill=(235, 235, 235))
        sheet.paste(img.convert("RGB").resize((full_w, full_h), Image.LANCZOS), (x, 80))
        d.text((x, 100 + full_h), "phone size", font=_font(18), fill=(150, 150, 150))
        sheet.paste(img.convert("RGB").resize((mob_w, mob_h), Image.LANCZOS), (x, 130 + full_h))
    sheet.save(out_path, "JPEG", quality=88)
    return out_path


def default_headlines(title):
    """Two faithful starting headlines from the title (owner edits before rendering)."""
    t = re.sub(r"[^\w\s?'.,!-]", "", (title or "").split("|")[0]).strip()
    words = t.split()
    dangling = {"at", "to", "from", "the", "a", "an", "of", "and", "for", "in", "on", "with", "his", "her", "my", "your", "is", "are"}

    def trim(ws):
        ws = list(ws)
        while len(ws) > 2 and ws[-1].lower().strip("?!.,") in dangling:
            ws.pop()
        while len(ws) > 2 and ws[0].lower() in ("and", "but", "so", "or"):
            ws.pop(0)
        return ws
    a = " ".join(trim(words[:6]))
    q = next((s.strip() for s in re.split(r"(?<=[?!.])\s", t) if s.strip().endswith("?")), None)
    b = " ".join(trim((q or t).split()[:5]))
    return [a, b if b.upper() != a.upper() else " ".join(trim(words[-5:]))]


def previews(conn, tenant_id, asset_id, headlines, fmt="guest", credential=""):
    v = conn.execute("SELECT * FROM assets WHERE tenant_id=? AND asset_id=?", (tenant_id, asset_id)).fetchone()
    if not v:
        raise LookupError("video not found for this brand")
    src = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if not src.exists():
        raise ValueError("no cached thumbnail for this video yet (it is downloaded on the next sync)")
    if fmt not in FORMATS:
        raise ValueError("unknown format")
    from growth_os import cast as cast_mod
    cast = cast_mod.load(tenant_id, asset_id)
    if fmt != "guest" and not cast:
        try:  # first time for this episode: find the hosts and guest in its own frames
            ok, why = cast_mod.available()
            if ok:
                cast_mod.build(conn, tenant_id, asset_id)
                cast = cast_mod.load(tenant_id, asset_id)
        except Exception:
            cast = {}
    cuts = {}
    if fmt == "viral":
        cuts = cast_mod.load_cuts(tenant_id, asset_id)
        if not cuts:
            try:  # casts built before cut-outs existed: rebuild once
                if cast_mod.available()[0]:
                    cast_mod.build(conn, tenant_id, asset_id)
                    cuts, cast = cast_mod.load_cuts(tenant_id, asset_id), cast_mod.load(tenant_id, asset_id)
            except Exception:
                cuts = {}
        if not cuts:
            fmt = "trio"
    if fmt != "viral":
        fmt = fit_format(fmt, cast)
    out_dir = DATA_DIR / "previews" / tenant_id / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().replace(":", "").replace("-", "")[:15]
    orig = Image.open(src)
    made, labels = [], []
    for i, h in enumerate([h for h in headlines if h and h.strip()][:2]):
        name = f"{stamp}-{fmt}-{'AB'[i]}.jpg"
        if fmt == "viral":
            from growth_os import viral
            frames = sorted((DATA_DIR / "frames" / tenant_id).glob(f"{asset_id}_*.jpg"))
            img = viral.render(src, h, cuts, out_path=out_dir / name, backdrop=frames[0] if frames else None)
        else:
            img = render(src, h, fmt=fmt, credential=credential, cast=cast, out_path=out_dir / name)
        made.append({"file": name, "headline": h, "format": fmt, "url": f"/preview/{tenant_id}/{asset_id}/{name}"})
        labels.append(f"{'AB'[i]}: {FORMATS[fmt]}")
    sheet = f"{stamp}-{fmt}-sheet.jpg"
    contact_sheet(orig, [Image.open(out_dir / m["file"]) for m in made], labels, out_dir / sheet)
    conn.execute("INSERT OR REPLACE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",  # same-second rerender
                 (tenant_id, "youtube", asset_id, "thumb_preview", json.dumps({"variants": made, "sheet": sheet}),
                  stamp, utcnow(), "thumbs.render (local preview, not uploaded)"))
    return {"variants": made, "sheet": f"/preview/{tenant_id}/{asset_id}/{sheet}",
            "source": "Built from this video's own published thumbnail photo and logo; faces unchanged. Local preview only.",
            "approval": "Not uploaded. Changing the live thumbnail needs your approval and is done in YouTube Studio."}
