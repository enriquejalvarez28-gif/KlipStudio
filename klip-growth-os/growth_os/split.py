"""Clean two-shot thumbnail (the look of top interview podcasts): two big, sharp, natural-colour photos straight
from the episode frames, people at the outer edges facing in, the real studio behind them, a big stacked headline
in the middle with the key word in an RYJ gold box. No cut-outs, no dark fades. Faces are never edited.
"""

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from growth_os import thumbs

W, H = 1280, 720
FACE_H = 285          # face box height on the canvas: big, like the reference
EYE_Y = 300           # eyes on one line
EDGE_X = 215          # face centre distance from the outer edge
BLEND = (500, 780)    # where the two photos melt into each other (background only)


def _locate(t, crop_path, frame_path):
    """Source frame + face (x, y, w, h, yaw) of the person in their saved crop."""
    cv2 = t.cv2
    crop = cv2.imread(str(crop_path))
    img, ox, oy = crop, 0, 0
    if frame_path and frame_path.exists():
        fr = cv2.imread(str(frame_path))
        if fr is not None and fr.shape[0] >= crop.shape[0] and fr.shape[1] >= crop.shape[1]:
            r = cv2.matchTemplate(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(r)
            if score > 0.8:
                img, (ox, oy) = fr, loc
    cf = t.faces(crop)
    if not cf:
        return None
    f = max(cf, key=lambda r: r[2] * r[3])
    x, y, w, h = float(f[0]) + ox, float(f[1]) + oy, float(f[2]), float(f[3])
    rex, lex, nx = float(f[4]) + ox, float(f[6]) + ox, float(f[8]) + ox
    yaw = (nx - (rex + lex) / 2) / max(abs(lex - rex), 1.0)
    eye_y = (float(f[5]) + float(f[7])) / 2 + oy
    return img, (x, y, w, h, yaw, eye_y)


def _panel(t, img, face, side, face_h=None, eye_y=None, target_x=None, max_zoom=None):
    """The person's photo filling the canvas, face big at the outer edge (side -1 = left, +1 = right)."""
    cv2 = t.cv2
    x, y, w, h, _, src_eye = face
    face_h, EYE = face_h or FACE_H, eye_y or EYE_Y
    s = face_h / h
    eye_y = src_eye
    cap = t.caption_top(img, y + h * 0.9, w * 0.6)  # burned-in captions under the chin: keep them out of frame
    if cap is not None and EYE + (cap - eye_y) * s < H:
        s = max(s, (H - EYE) / max(cap - eye_y - 4, 1))
        if max_zoom:
            s = min(s, face_h / h * max_zoom)
    _panel.cap_y = None if cap is None else EYE + (cap - eye_y) * s  # where captions land on the canvas
    big = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_LANCZOS4 if s > 1 else cv2.INTER_AREA)
    fx = (x + w / 2) * s
    if target_x is None:
        target_x = EDGE_X if side < 0 else W - EDGE_X
    ox, oy = int(fx - target_x), int(eye_y * s - EYE)
    canvas = Image.new("RGB", (W, H), (20, 20, 20))
    src = Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB))
    canvas.paste(src, (-ox, -oy))
    if -ox > 0 or -oy > 0 or src.width - ox < W or src.height - oy < H:  # frame edge reached: fill with a blurred copy
        bg = src.resize((W, H)).filter(ImageFilter.GaussianBlur(30))
        bg.paste(src, (-ox, -oy))
        canvas = bg
    return canvas


def _grade(im):
    """Crisp, bright, natural colour (same treatment for both photos)."""
    im = ImageEnhance.Contrast(im).enhance(1.08)
    im = ImageEnhance.Color(im).enhance(1.12)
    return im.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))


def _match(a, b):
    """Bring two shots to the same brightness so they read as one photo."""
    from PIL import ImageStat
    la, lb = ImageStat.Stat(a.convert("L")).mean[0], ImageStat.Stat(b.convert("L")).mean[0]
    t = (la + lb) / 2
    return (ImageEnhance.Brightness(a).enhance(max(0.85, min(1.2, t / max(la, 1)))),
            ImageEnhance.Brightness(b).enhance(max(0.85, min(1.2, t / max(lb, 1)))))


def _choose(t, cast_crops, frames):
    """Guest + one host, each on the side they face (looking in toward the other)."""
    found = {}
    for r in ("guest", "jamar", "enrique"):
        if r in cast_crops:
            p = _locate(t, cast_crops[r], frames.get(r))
            if p:
                found[r] = p
    if "guest" not in found:
        hosts = [r for r in ("jamar", "enrique") if r in found]
        return [(found[r], -1 if i == 0 else 1) for i, r in enumerate(hosts[:2])]
    gy = found["guest"][1][4]
    g_side = -1 if gy > 0.12 else (1 if gy < -0.12 else 0)  # facing right → sits on the left
    best = None
    for r in ("jamar", "enrique"):
        if r not in found:
            continue
        hy = found[r][1][4]
        h_side = -1 if hy > 0.12 else (1 if hy < -0.12 else (-1 if r == "jamar" else 1))
        fits = g_side == 0 or g_side == -h_side
        score = (2 if fits else 0) + (1 if r == "jamar" else 0)
        if best is None or score > best[0]:
            best = (score, r, h_side)
    if best is None:
        return [(found["guest"], 1)]
    _, host, h_side = best
    return [(found[host], h_side), (found["guest"], -h_side)]


def _headline(d, canvas, headline, gold, top, bottom, col_w=400, max_size=140):
    """Stacked white lines with a soft shadow; the gold word(s) in a gold box with black text."""
    lines = thumbs.parse_headline(headline)
    words = [w for line in lines for w in line]
    runs = []  # consecutive words with the same colour
    for w, g in words:
        if runs and runs[-1][0] == g:
            runs[-1][1].append(w)
        else:
            runs.append((g, [w]))
    probe = thumbs._font(min(125, max_size - 10))
    groups = []  # white runs wrapped into short stacked lines (bigger type); gold runs stay one boxed line
    for g, ws in runs:
        if g:
            groups.append((g, ws))
            continue
        cur = []
        for w in ws:
            if cur and d.textlength(" ".join(cur + [w]), font=probe) > col_w + 30:
                groups.append((g, cur))
                cur = []
            cur.append(w)
        if cur:
            groups.append((g, cur))
    max_w = col_w
    GAP, PAD = 14, 12  # space between lines; padding inside the gold box

    def metrics(f):
        x0, y0, x1, y1 = f.getbbox("HÁGQ")
        return y0, y1 - y0  # top offset, cap+descender height

    size = max_size
    while size > 50:
        f = thumbs._font(size)
        _, lh = metrics(f)
        total = sum(lh + (2 * PAD if g else 0) for g, _ in groups) + GAP * (len(groups) - 1)
        if all(d.textlength(" ".join(ws), font=f) + (40 if g else 0) <= max_w for g, ws in groups) and total <= bottom - top:
            break
        size -= 4
    f = thumbs._font(size)
    off, lh = metrics(f)
    total = sum(lh + (2 * PAD if g else 0) for g, _ in groups) + GAP * (len(groups) - 1)
    y = top + (bottom - top - total) / 2
    shadow = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shadow)
    items = []
    for g, ws in groups:
        txt = " ".join(ws)
        tw = d.textlength(txt, font=f)
        x = (W - tw) / 2
        if g:
            items.append(("box", [x - 20, y, x + tw + 20, y + lh + 2 * PAD], txt, x, y + PAD - off))
            y += lh + 2 * PAD + GAP
        else:
            sd.text((x + 4, y - off + 6), txt, font=f, fill=200)
            items.append(("text", None, txt, x, y - off))
            y += lh + GAP
    canvas.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(canvas)
    for kind, box, txt, x, ty in items:
        if kind == "box":
            d.rectangle(box, fill=gold)
            d.text((x, ty), txt, font=f, fill=(12, 12, 12))
        else:
            d.text((x, ty), txt, font=f, fill=(255, 255, 255), stroke_width=5, stroke_fill=(10, 10, 10))
    return canvas


def render(cast_crops, headline, *, gold=None, out_path=None, frames=None, name_tag="", **_):
    from growth_os import lineup
    with lineup._LOCK:
        t = lineup._tools()
        gold = gold or thumbs.brand_gold()
        people = _choose(t, cast_crops, frames or {})
        if not people:
            raise ValueError("no usable photos for this episode")
        panels = [(_grade(_panel(t, img, face, side)), side) for (img, face), side in people]
        if len(panels) == 2:
            a, b = _match(panels[0][0], panels[1][0])
            panels = [(a, panels[0][1]), (b, panels[1][1])]
            left = next(p for p, s in panels if s < 0) if any(s < 0 for _, s in panels) else panels[0][0]
            right = next(p for p, s in panels if s > 0) if any(s > 0 for _, s in panels) else panels[1][0]
            mask = Image.new("L", (W, H), 0)
            md = ImageDraw.Draw(mask)
            for xx in range(W):
                v = 0 if xx < BLEND[0] else 255 if xx > BLEND[1] else int(255 * (xx - BLEND[0]) / (BLEND[1] - BLEND[0]))
                md.line([(xx, 0), (xx, H)], fill=v)
            canvas = Image.composite(right, left, mask)
        else:
            canvas = panels[0][0]
        # Calm the busy studio wall behind the headline (centre column only; faces untouched).
        band = Image.new("L", (W, H), 0)
        bd = ImageDraw.Draw(band)
        for xx in range(W):
            v = max(0.0, 1 - abs(xx - W / 2) / 300)
            bd.line([(xx, 0), (xx, H)], fill=int(255 * min(1.0, v * 1.4)))
        calm = ImageEnhance.Brightness(canvas.filter(ImageFilter.GaussianBlur(16))).enhance(0.5)
        canvas = Image.composite(calm, canvas, band)
        d = ImageDraw.Draw(canvas)
        top, bottom = 118, H - (100 if name_tag else 40)
        canvas = _headline(d, canvas, headline, gold, top, bottom)
        d = ImageDraw.Draw(canvas)
        if name_tag:
            nf = thumbs._font(32)
            txt = name_tag.upper()
            tw = d.textlength(txt, font=nf)
            x0 = (W - tw) / 2 - 16
            d.rounded_rectangle([x0, H - 86, x0 + tw + 32, H - 38], radius=6, fill=(12, 12, 12))
            d.text((x0 + 16, H - 82), txt, font=nf, fill=gold)
        lg = thumbs._logo_from_original(None) if (thumbs.BRAND_DIR / "logo.jpg").exists() else None
        if lg:
            lg = lg.convert("RGB").resize((96, 96), Image.LANCZOS)
            m = Image.new("L", lg.size, 0)
            ImageDraw.Draw(m).ellipse([2, 2, 94, 94], fill=255)
            canvas.paste(lg, (W - 118, 20) if people[0][1] < 0 and len(people) == 1 else ((W - 96) // 2, 14), m)
        if out_path:
            canvas.save(out_path, "JPEG", quality=94)
        return canvas


# ── Three people: Jamar | guest | Enrique (owner: "always the three of us"), same photo quality ──

TRIO_X = (215, 640, 1065)
TRIO_FACE_H, TRIO_EYE_Y = 225, 190
TRIO_BLEND = ((335, 485), (795, 945))
TRIO_TEXT_TOP = 430


def render3(cast_crops, headline, *, gold=None, out_path=None, frames=None, name_tag="", **_):
    from growth_os import lineup
    with lineup._LOCK:
        t = lineup._tools()
        gold = gold or thumbs.brand_gold()
        frames = frames or {}
        found = {}
        for r in ("jamar", "guest", "enrique"):
            if r in cast_crops:
                p = _locate(t, cast_crops[r], frames.get(r))
                if p:
                    found[r] = p
        if len(found) < 3:
            raise ValueError("need Jamar, Enrique and the guest")
        panels, caps = [], []
        for r, x in zip(("jamar", "guest", "enrique"), TRIO_X):
            img, face = found[r]
            panels.append(_grade(_panel(t, img, face, 0, face_h=TRIO_FACE_H, eye_y=TRIO_EYE_Y, target_x=x, max_zoom=1.06)))
            if _panel.cap_y is not None:
                caps.append(_panel.cap_y)
        from PIL import ImageStat
        ls = [ImageStat.Stat(p.convert("L")).mean[0] for p in panels]
        avg = sum(ls) / 3
        panels = [ImageEnhance.Brightness(p).enhance(max(0.85, min(1.2, avg / max(l, 1)))) for p, l in zip(panels, ls)]
        canvas = panels[0]
        for (a, b), p in zip(TRIO_BLEND, panels[1:]):
            mask = Image.new("L", (W, H), 0)
            md = ImageDraw.Draw(mask)
            for xx in range(W):
                v = 0 if xx < a else 255 if xx > b else int(255 * (xx - a) / (b - a))
                md.line([(xx, 0), (xx, H)], fill=v)
            canvas = Image.composite(p, canvas, mask)
        # Soft dark fade at the bottom so the headline reads over shirts and mics.
        fade = Image.new("L", (W, H), 0)
        fd = ImageDraw.Draw(fade)
        solid = min([c - 12 for c in caps if c < H] + [H + 1])  # burned-in captions: fully covered from here down
        solid = min(solid, H - 60)
        start = min(TRIO_TEXT_TOP - 110, solid - 230)
        for yy in range(int(start), H):
            v = 255 if yy >= solid else int(255 * max(0.0, (yy - start) / (solid - start)) ** 1.6)
            fd.line([(0, yy), (W, yy)], fill=v)
        canvas = Image.composite(Image.new("RGB", (W, H), (8, 8, 8)), canvas, fade)
        d = ImageDraw.Draw(canvas)
        canvas = _headline(d, canvas, headline, gold, TRIO_TEXT_TOP, H - 22, col_w=1120, max_size=128)
        d = ImageDraw.Draw(canvas)
        if name_tag:
            nf = thumbs._font(30)
            txt = name_tag.upper()
            tw = d.textlength(txt, font=nf)
            x0 = (W - tw) / 2 - 16
            y0 = TRIO_TEXT_TOP - 58
            d.rounded_rectangle([x0, y0, x0 + tw + 32, y0 + 44], radius=6, fill=gold)
            d.text((x0 + 16, y0 + 4), txt, font=nf, fill=(12, 12, 12))
        lg = thumbs._logo_from_original(None) if (thumbs.BRAND_DIR / "logo.jpg").exists() else None
        if lg:
            lg = lg.convert("RGB").resize((84, 84), Image.LANCZOS)
            m = Image.new("L", lg.size, 0)
            ImageDraw.Draw(m).ellipse([2, 2, 82, 82], fill=255)
            canvas.paste(lg, (18, 16), m)
        if out_path:
            canvas.save(out_path, "JPEG", quality=94)
        return canvas
