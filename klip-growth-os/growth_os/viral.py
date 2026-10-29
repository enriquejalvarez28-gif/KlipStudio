"""Viral-style RYJ thumbnail: big cut-out people with a bright outline over a
dark, blurred backdrop from the same episode; 2–4 huge words in white with one
gold word. Black/white/gold brand kept; faces are never edited (only cut out).

Why this look: the patterns that consistently win clicks on phone-size
thumbnails are one big expressive face (or a clear trio), very few words in
very large type, and strong subject/background separation.
"""

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from growth_os import thumbs

W, H = 1280, 720
OUTLINE = 7
MIN_FACE = 105        # px in the source frame; smaller faces (wide shots) look soft when enlarged
MAX_UPSCALE = 1.9


def _sticker(cut, face_px, target_face):
    """Scale an RGBA cut-out so the face is ~target_face px; solid person, white outline, soft shadow."""
    cut = cut.convert("RGBA")
    s = min(MAX_UPSCALE, target_face / max(face_px, 1))
    height = int(cut.height * s)
    cut = cut.resize((max(1, int(cut.width * s)), height), Image.LANCZOS)
    soft = cut.split()[3]
    # Segmentation edges are soft: make the person fully opaque inside, keep a 1–2 px feathered edge.
    solid = soft.point(lambda v: 0 if v < 70 else 255 if v > 150 else int((v - 70) * 255 / 80)).filter(ImageFilter.GaussianBlur(0.8))
    pad = OUTLINE * 3 + 24
    size = (cut.width + pad * 2, cut.height + pad * 2)
    m = Image.new("L", size, 0)
    m.paste(solid, (pad, pad))
    hard = m.point(lambda v: 255 if v > 128 else 0)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow = hard.filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v * 0.7))
    out.paste((0, 0, 0, 255), (12, 16), shadow)
    ring = hard.filter(ImageFilter.MaxFilter(OUTLINE * 2 + 1)).filter(ImageFilter.GaussianBlur(1.0))
    white = Image.new("RGBA", size, (255, 255, 255, 0))
    white.putalpha(ring)
    out.alpha_composite(white)
    person = Image.new("RGBA", size, (0, 0, 0, 0))
    rgb = cut.convert("RGB")
    rgb.putalpha(solid)
    person.paste(rgb, (pad, pad))
    out.alpha_composite(person)
    return out


def _backdrop(src_img, gold):
    bg = ImageOps.fit(src_img.convert("RGB"), (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(22))
    bg = Image.blend(Image.new("RGB", (W, H), (6, 6, 6)), bg, 0.32)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W * 0.42, -H * 0.2, W * 1.15, H * 1.2], fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    bg = Image.composite(Image.new("RGB", (W, H), gold), bg, glow.point(lambda v: int(v * 0.35)))
    fade = Image.new("L", (W, H), 0)  # dark left side for the words
    d = ImageDraw.Draw(fade)
    for x in range(W):
        d.line([(x, 0), (x, H)], fill=int(255 * max(0.0, min(1.0, (0.62 - x / W) / 0.30))))
    return Image.composite(Image.new("RGB", (W, H), (4, 4, 4)), bg, fade)


def render(orig_path, headline, cuts, *, gold=None, out_path=None, backdrop=None):
    """cuts: {role: (png_path, meta)} from cast.load_cuts. Layout by who was found in this episode."""
    orig = Image.open(orig_path)
    gold = gold or thumbs.brand_gold(orig)
    canvas = _backdrop(Image.open(backdrop) if backdrop else orig, gold).convert("RGBA")
    sharp = {r: v for r, v in cuts.items() if v[1].get("face_px", 0) >= MIN_FACE}
    if "guest" in cuts and "guest" not in sharp and len(sharp) < 1:
        sharp["guest"] = cuts["guest"]
    have = {r: Image.open(p) for r, (p, _) in sharp.items()}
    face = {r: m.get("face_px", 100) for r, (_, m) in sharp.items()}
    # Who goes where (studio order Jamar | guest | Enrique). The guest is biggest and in front.
    # (role, target face px, centre x). Studio order Jamar | guest | Enrique; guest biggest and in front.
    if "guest" in have and len(have) == 3:
        plan = [("jamar", 160, 690), ("enrique", 160, 1170), ("guest", 210, 930)]
    elif "guest" in have and len(have) == 2:
        host = next(r for r in have if r != "guest")
        # guest first, the host in front at the edge so both faces stay fully visible
        plan = [("guest", 215, 830 if host == "enrique" else 1010), (host, 170, 1165 if host == "enrique" else 700)]
    elif "guest" in have:
        plan = [("guest", 250, 930)]
    elif len(have) == 2:
        plan = [("jamar", 210, 780), ("enrique", 210, 1100)]
    elif have:
        plan = [(next(iter(have)), 250, 930)]
    else:
        raise ValueError("no usable cut-outs for this episode")
    for role, target, cx in plan:
        st = _sticker(have[role], face[role], target)
        y = H - st.height + 40  # people sit on the bottom edge, slightly cropped like real thumbnails
        x = int(cx - st.width / 2)  # cut-outs are centred on the face, so cx is where the face lands
        x = max(x, int(W * 0.40) - 140)  # keep bodies mostly off the headline on the left
        canvas.alpha_composite(st, (x, max(-120, y)))
    canvas = canvas.convert("RGB")
    d = ImageDraw.Draw(canvas)
    logo = thumbs._logo_from_original(orig)
    if logo:
        canvas.paste(logo, (30, 20))
    lines = thumbs.parse_headline(headline)
    top, bottom = (200 if logo else 120), H - 60
    f, lh, lines = thumbs._layout(d, lines, 600, bottom - top, start=220)
    y = top + max(0, (bottom - top - lh * len(lines)) // 2)
    for line in lines:
        x = 56
        for word, g in line:
            d.text((x, y), word, font=f, fill=gold if g else (255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0))
            x += d.textlength(word + " ", font=f)
        y += lh
    if out_path:
        canvas.save(out_path, "JPEG", quality=92)
    return canvas
