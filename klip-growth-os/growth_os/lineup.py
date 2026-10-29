"""Lineup thumbnail: Jamar | guest | Enrique standing together on one dark backdrop.

Spacing rules (what makes a 3-person podcast thumbnail read as organised):
- equal head sizes, eyes on one line; the guest in the middle is ~8% bigger and in front;
- even spacing between faces, shoulders overlapping so it reads as one group;
- no outlines or stickers; one shared backdrop and matched exposure;
- the headline sits in a band across the bottom, logo top-left.
People come only from THIS episode's frames (cast.py). Faces are never edited: they are cut out,
scaled and given one overall brightness match.
"""

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageStat

from growth_os import thumbs

W, H = 1280, 720
ORDER = ("jamar", "guest", "enrique")
CENTERS = {3: (318, 640, 962), 2: (450, 830)}
FACE_W = {"side": 172, "middle": 186}
EYE_Y = 205                     # eyes on one line
BAND_TOP = 470                  # headline band


MATTE = ("isnet-general-use.onnx", "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx")


class _Tools:
    """Face detector, caption (text) detector and a high-quality person matte (IS-Net), all local and free."""

    def __init__(self):
        import urllib.request
        import cv2
        from growth_os import cast
        d = cast.ensure_models()
        m = d / MATTE[0]
        if not m.exists() or m.stat().st_size < 1_000_000:  # one-time ~170 MB download
            with urllib.request.urlopen(MATTE[1], timeout=600) as r:
                m.write_bytes(r.read())
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(str(d / cast.MODELS["det"][0]), "", (320, 320), 0.7)
        self.matte = cv2.dnn.readNet(str(m))
        self.txt = cv2.dnn_TextDetectionModel_DB(str(d / cast.MODELS["ocr_det"][0]))
        self.txt.setBinaryThreshold(0.3).setPolygonThreshold(0.5).setMaxCandidates(50).setUnclipRatio(2.0)
        self.txt.setInputParams(1.0 / 255.0, (736, 416), (122.67891434, 116.66876762, 104.00698793), True)

    def faces(self, img):
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, f = self.det.detect(img)
        return [] if f is None else [r for r in f]

    def alpha(self, img):
        import numpy as np
        cv2 = self.cv2
        x = cv2.resize(img, (1024, 1024))[:, :, ::-1].astype(np.float32) / 255.0 - 0.5
        self.matte.setInput(x.transpose(2, 0, 1)[None].copy())
        m = self.matte.forward()[0, 0]
        m = (m - m.min()) / max(1e-6, m.max() - m.min())
        return cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)

    def caption_top(self, img, below_y, min_w):
        """y of burned-in captions under the face (Shorts), or None."""
        boxes, _ = self.txt.detect(img)
        ys = []
        for b in boxes or []:
            xs_, ys_ = [p[0] for p in b], [p[1] for p in b]
            if min(ys_) > below_y and max(xs_) - min(xs_) > min_w:
                ys.append(min(ys_))
        return min(ys) if ys else None


_T = []


def _tools():
    if not _T:
        _T.append(_Tools())
    return _T[0]


def _person(t, crop_path, frame_path=None):
    """Cut the person out of the FULL episode frame (more shoulders, cleaner edges) located via their saved crop."""
    import numpy as np
    cv2 = t.cv2
    crop = cv2.imread(str(crop_path))
    img, ox, oy = crop, 0, 0
    if frame_path and frame_path.exists():
        fr = cv2.imread(str(frame_path))
        if fr is not None and fr.shape[0] >= crop.shape[0] and fr.shape[1] >= crop.shape[1]:
            r = cv2.matchTemplate(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
            _, score, _, (ox, oy) = cv2.minMaxLoc(r)
            img = fr if score > 0.8 else crop
            ox, oy = (ox, oy) if score > 0.8 else (0, 0)
    cf = t.faces(crop)
    if not cf:
        return None
    f = max(cf, key=lambda r: r[2] * r[3])
    x, y, w, h = float(f[0]) + ox, float(f[1]) + oy, float(f[2]), float(f[3])
    eye_y = (float(f[5]) + float(f[7])) / 2 + oy
    cx = x + w / 2
    H_, W_ = img.shape[:2]
    x0, x1 = int(max(0, cx - 2.1 * w)), int(min(W_, cx + 2.1 * w))
    y0, y1 = int(max(0, y - 0.9 * h)), H_
    reg = img[y0:y1, x0:x1]
    cap = t.caption_top(reg, (y + h * 0.9) - y0, w * 0.6)
    if cap is not None:
        y1 = int(y0 + cap - 6)
        reg = img[y0:y1, x0:x1]
    a = t.alpha(reg)
    hard = (a > 0.45).astype(np.uint8)
    fcx, fcy = int(cx - x0), int(y + h / 2 - y0)
    # Other people touching this one: split at the midpoint between faces.
    for o in t.faces(reg):
        ocx = float(o[0]) + float(o[2]) / 2
        if abs(ocx - fcx) > w * 0.6:
            mid = int((ocx + fcx) / 2)
            if ocx > fcx:
                hard[:, mid:] = 0
            else:
                hard[:, :mid] = 0
    n, lab = cv2.connectedComponents(hard)
    keep = lab[min(fcy, lab.shape[0] - 1), min(fcx, lab.shape[1] - 1)]
    if keep == 0:
        return None
    a = np.where(lab == keep, a, 0).astype(np.float32)
    hh, ww = a.shape
    ramp = np.ones((hh, ww), np.float32)  # where the region edge cuts the body, fade instead of a hard line
    e = max(8, int(ww * 0.08))
    for i in range(e):
        k = (i / e) ** 1.3
        if x0 > 0 or i < 2:
            ramp[:, i] = np.minimum(ramp[:, i], k)
        if x1 < W_ or i < 2:
            ramp[:, ww - 1 - i] = np.minimum(ramp[:, ww - 1 - i], k)
    b = max(10, int(hh * 0.12))
    for i in range(b):
        ramp[hh - 1 - i, :] = np.minimum(ramp[hh - 1 - i, :], (i / b) ** 1.1)
    a = cv2.GaussianBlur((a * ramp).clip(0, 1), (0, 0), 0.7)
    rgb = Image.fromarray(cv2.cvtColor(reg, cv2.COLOR_BGR2RGB))
    rgb.putalpha(Image.fromarray((a * 255).astype(np.uint8)))
    return rgb, (cx - x0, eye_y - y0, w)


def _match(im, target_l):
    """One overall brightness/contrast match so three different shots look like one shoot."""
    rgb = im.convert("RGB")
    l = ImageStat.Stat(rgb.convert("L"), mask=im.split()[3].point(lambda v: 255 if v > 128 else 0)).mean[0] or target_l
    out = ImageEnhance.Brightness(rgb).enhance(max(0.8, min(1.25, target_l / l)))
    out = ImageEnhance.Contrast(out).enhance(1.06)
    out.putalpha(im.split()[3])
    return out


def _backdrop(gold, src=None):
    bg = Image.new("RGB", (W, H), (12, 12, 13))
    if src is not None:  # a whisper of the episode's own set, very dark and blurred
        from PIL import ImageOps
        s = ImageOps.fit(src.convert("RGB"), (W, H)).filter(ImageFilter.GaussianBlur(28))
        bg = Image.blend(bg, s, 0.16)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W * 0.12, -H * 0.35, W * 0.88, H * 0.85], fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    bg = Image.composite(Image.new("RGB", (W, H), gold), bg, glow.point(lambda v: int(v * 0.22)))
    # thin gold floor line behind the group, like a set edge
    d = ImageDraw.Draw(bg)
    d.line([(0, BAND_TOP - 30), (W, BAND_TOP - 30)], fill=tuple(int(c * 0.35) for c in gold), width=2)
    return bg


def _balanced(d, lines):
    """Headline as 1 line if short, else 2 lines of similar width (no orphan word)."""
    words = [w for line in lines for w in line]
    if len(words) <= 3:
        return [words]
    f = thumbs._font(100)
    wid = lambda ws: d.textlength(" ".join(w for w, _ in ws), font=f)
    k = min(range(1, len(words)), key=lambda i: max(wid(words[:i]), wid(words[i:])))
    return [words[:k], words[k:]]


import threading

_LOCK = threading.Lock()  # OpenCV nets aren't thread-safe; the server renders drafts on several threads


def render(cast_crops, headline, **kw):
    with _LOCK:
        return _render(cast_crops, headline, **kw)


def _render(cast_crops, headline, *, gold=None, out_path=None, backdrop_src=None, logo=None, frames=None):
    """cast_crops: {role: crop_path} for this episode (cast.load); frames: {role: full frame path}.
    Needs the guest and at least one host."""
    t = _tools()
    frames = frames or {}
    gold = gold or thumbs.brand_gold()
    roles = [r for r in ORDER if r in cast_crops]
    if "guest" not in roles or len(roles) < 2:
        raise ValueError("lineup needs the guest and at least one host from this episode")
    people = {}
    for r in roles:
        p = _person(t, cast_crops[r], frames.get(r))
        if p:
            people[r] = p
    roles = [r for r in roles if r in people]
    if "guest" not in roles or len(roles) < 2:
        raise ValueError("couldn't cut out enough people from this episode's frames")
    centers = CENTERS[len(roles)]
    canvas = _backdrop(gold, backdrop_src).convert("RGBA")
    target_l = 118
    # Sides first, the guest last so the guest is in front.
    for r in sorted(roles, key=lambda r: r == "guest"):
        im, (fcx, fey, fw) = people[r]
        tw = FACE_W["middle" if r == "guest" else "side"]
        s = min(2.2, tw / fw)
        im = _match(im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS), target_l)
        cx = centers[roles.index(r)]
        ey = EYE_Y - (6 if r == "guest" else 0)
        # soft contact shadow so overlapping people separate cleanly
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sh.putalpha(im.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55)))
        pos = (int(cx - fcx * s), int(ey - fey * s))
        canvas.alpha_composite(sh, (pos[0] + 10, pos[1] + 8))
        canvas.alpha_composite(im, pos)
    # Bottom band: dark gradient that the people fade into, headline on top.
    band = Image.new("L", (W, H), 0)
    bd = ImageDraw.Draw(band)
    for y in range(BAND_TOP - 120, H):
        bd.line([(0, y), (W, y)], fill=int(255 * min(1.0, max(0.0, (y - (BAND_TOP - 120)) / 190)) ** 1.3))
    canvas = Image.composite(Image.new("RGBA", (W, H), (8, 8, 8, 255)), canvas, band).convert("RGB")
    d = ImageDraw.Draw(canvas)
    lg = logo if logo is not None else thumbs._logo_from_original(None) if (thumbs.BRAND_DIR / "logo.jpg").exists() else None
    if lg:
        lg = lg.convert("RGB").resize((132, 132), Image.LANCZOS)
        m = Image.new("L", lg.size, 0)
        ImageDraw.Draw(m).ellipse([3, 3, 129, 129], fill=255)
        canvas.paste(lg, (30, 24), m.filter(ImageFilter.GaussianBlur(1)))
    lines = _balanced(d, thumbs.parse_headline(headline))
    f, lh, lines = thumbs._layout(d, lines, W - 120, H - BAND_TOP - 40, max_lines=2, start=130)
    y = BAND_TOP + max(0, (H - BAND_TOP - 30 - lh * len(lines)) // 2)
    for line in lines:
        width = d.textlength(" ".join(w for w, _ in line), font=f)
        x = (W - width) / 2  # centred under the group
        for w_, g in line:
            d.text((x, y), w_, font=f, fill=gold if g else (255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
            x += d.textlength(w_ + " ", font=f)
        y += lh
    if out_path:
        canvas.save(out_path, "JPEG", quality=92)
    return canvas
