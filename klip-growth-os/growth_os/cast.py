"""Per-episode cast for thumbnails: Jamar, Enrique and the guest, each cut from
THAT episode's own frames (never a photo from another episode).

Frames: YouTube's public in-video stills (maxres1-3.jpg, 1280×720, taken across
the episode) plus the same stills from Shorts cut from the same recording
(matched by the guest's face). Faces: OpenCV YuNet (detect) + SFace (recognize),
small free ONNX models, run locally. Hosts are recognized against reference
crops in data/brand/host_refs/<name>/*.jpg; everyone else is the guest.
If OpenCV isn't installed this module reports unavailable and thumbnails fall
back to the guest photo from the episode's current thumbnail.
"""

import json
import urllib.request
from datetime import date

from growth_os.db import DATA_DIR, utcnow

_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = {
    "det": ("face_detection_yunet_2023mar.onnx", _ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    "rec": ("face_recognition_sface_2021dec.onnx", _ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx"),
    # expression (pick each person's most animated frame) and person cut-outs for viral thumbnails
    "fer": ("facial_expression_recognition_mobilefacenet_2022july.onnx",
            _ZOO + "facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx"),
    "seg": ("human_segmentation_pphumanseg_2023mar.onnx", _ZOO + "human_segmentation_pphumanseg/human_segmentation_pphumanseg_2023mar.onnx"),
    # read the words already on a thumbnail so titles can complement them
    "ocr_det": ("text_detection_en_ppocrv3_2023may.onnx", _ZOO + "text_detection_ppocr/text_detection_en_ppocrv3_2023may.onnx"),
    "ocr_rec": ("text_recognition_CRNN_EN_2021sep.onnx", _ZOO + "text_recognition_crnn/text_recognition_CRNN_EN_2021sep.onnx"),
}
EMOTIONS = ("angry", "disgust", "fearful", "happy", "neutral", "sad", "surprised")
HOST_MATCH = 0.65      # SFace cosine: real host matches score 0.66–1.0 on RYJ frames; look-alikes 0.55–0.57; guests < 0.40
UNSURE = 0.36          # between UNSURE and HOST_MATCH: not sure who it is → not used at all
GUEST_MATCH = 0.45     # a Short belongs to the episode when its guest face matches this well
SHORTS_WINDOW_DAYS = 45
FRAME_URLS = ("https://i.ytimg.com/vi/{vid}/maxres{n}.jpg", "https://i.ytimg.com/vi/{vid}/sd{n}.jpg")
ROLES = ("jamar", "guest", "enrique")  # studio order, left → right


def model_dir():
    return DATA_DIR / "models"


def ensure_models():
    d = model_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.values():
        p = d / name
        if not p.exists() or p.stat().st_size < 100_000:  # (also replaces a failed tiny download)
            with urllib.request.urlopen(url, timeout=120) as r:
                p.write_bytes(r.read())
    return d


def available():
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False, "OpenCV isn't installed (pip install opencv-python-headless); thumbnails use the guest photo only."
    try:
        ensure_models()
    except Exception as e:  # offline
        return False, f"face models couldn't be downloaded: {str(e)[:80]}"
    if not refs_dir().exists() or not any(refs_dir().glob("*/*.jpg")):
        return False, "no host reference photos in data/brand/host_refs/<name>/"
    return True, None


def refs_dir():
    return DATA_DIR / "brand" / "host_refs"


class _Faces:
    def __init__(self):
        import cv2
        d = ensure_models()
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(str(d / MODELS["det"][0]), "", (320, 320), 0.8)
        self.rec = cv2.FaceRecognizerSF.create(str(d / MODELS["rec"][0]), "")
        self.fer = cv2.dnn.readNet(str(d / MODELS["fer"][0]))
        self.seg = cv2.dnn.readNet(str(d / MODELS["seg"][0]))
        self.refs = {}
        for p in sorted(refs_dir().glob("*/*.jpg")):
            img = cv2.imread(str(p))
            f = self.detect(img)
            if f:
                self.refs.setdefault(p.parent.name, []).append(self.embed(img, max(f, key=lambda x: x[2] * x[3])))

    def detect(self, img, x0=0, x1=None):
        if img is None:
            return []
        sub = img[:, x0:x1] if (x0 or x1) else img
        h, w = sub.shape[:2]
        self.det.setInputSize((w, h))
        _, f = self.det.detect(sub)
        out = []
        for r in ([] if f is None else f):
            r = r.copy()
            r[0] += x0
            for k in range(4, 14, 2):  # landmark x coords
                r[k] += x0
            out.append(r)
        return out

    def embed(self, img, f):
        return self.rec.feature(self.rec.alignCrop(img, f))

    def expression(self, img, f):
        """{emotion: probability} from the aligned face; 'energy' = how animated (0 calm … 1 big reaction)."""
        import numpy as np
        face = self.cv2.cvtColor(self.rec.alignCrop(img, f), self.cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        self.fer.setInput(self.cv2.dnn.blobFromImage((face - 0.5) / 0.5))
        z = dict(zip(EMOTIONS, self.fer.forward()[0].astype(float).tolist()))
        # Softmax saturates on talking/smiling podcast faces, so rank by the logit gap between the strongest
        # reaction (happy / surprised / angry) and neutral: 0 ≈ flat, 1 ≈ big reaction.
        gap = max(z["happy"], z["surprised"] + 1.0, z["angry"]) - z["neutral"]
        out = {k: round(v, 2) for k, v in z.items()}
        out["energy"] = round(min(1.0, max(0.0, (gap - 4.0) / 10.0)), 3)
        return out

    def person_mask(self, crop, face_xy, face_w=100):
        """Soft alpha (0–255) of the person whose face is at face_xy inside crop."""
        import numpy as np
        cv2 = self.cv2
        h, w = crop.shape[:2]
        rgb = cv2.cvtColor(cv2.resize(crop, (192, 192)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        self.seg.setInput(cv2.dnn.blobFromImage((rgb - 0.5) / 0.5))
        out = self.seg.forward()[0]
        e = np.exp(out - out.max(axis=0))
        prob = cv2.resize((e[1] / e.sum(axis=0)).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        hard = (prob > 0.5).astype(np.uint8)
        k = max(3, int(face_w * 0.09)) | 1  # opening removes thin things stuck to the person (mic arms, stands)
        hard = cv2.morphologyEx(hard, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        n, lab = cv2.connectedComponents(hard)
        fx_, fy_ = int(min(w - 1, max(0, face_xy[0]))), int(min(h - 1, max(0, face_xy[1])))
        keep = lab[fy_, fx_]
        if keep == 0:  # face pixel fell outside the mask: keep the biggest blob
            counts = np.bincount(lab.ravel())
            counts[0] = 0
            keep = int(counts.argmax())
        alpha = np.where(lab == keep, np.maximum(prob, 0.0), 0).astype(np.float32) * (lab == keep)
        alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)
        return (np.clip(alpha, 0, 1) * 255).astype(np.uint8)

    def sim(self, a, b):
        return float(self.rec.match(a, b, self.cv2.FaceRecognizerSF_FR_COSINE))

    def who(self, e):
        best, score = "guest", 0.0
        for name, embs in self.refs.items():
            s = max(self.sim(e, r) for r in embs)
            if s > score:
                best, score = name, s
        if score >= HOST_MATCH:
            return best, score
        return ("unsure" if score >= UNSURE else "guest"), score


def _frames(tenant_id, vid, fetch):
    d = DATA_DIR / "frames" / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for n in (1, 2, 3):
        p = d / f"{vid}_{n}.jpg"
        stale = not p.exists() or p.stat().st_size < 8000  # missing or a grey placeholder
        for url in FRAME_URLS if stale else ():
            try:
                data = fetch(url.format(vid=vid, n=n))
            except Exception:
                continue
            if data and len(data) > 8000:  # YouTube's grey placeholder is tiny
                p.write_bytes(data)
                break
        if p.exists() and p.stat().st_size >= 8000:
            out.append(p)
    return out


def _default_fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "KlipGrowthOS/1.0"}), timeout=30) as r:
        return r.read()


def _crop(img, f, out_path, below=2.4):
    """Portrait around the face: shoulders up, face a bit above center. Returns horizontal focus (0–1)."""
    H, W = img.shape[:2]
    x, y, w, h = (float(v) for v in f[:4])
    cw = min(W, w * 2.6)
    top, bot = max(0, y - h * 1.0), min(H, y + h * below)  # shoulders up: stops above burned-in captions
    cx = x + w / 2
    x0 = int(max(0, min(W - cw, cx - cw / 2)))
    crop = img[int(top):int(bot), x0:int(x0 + cw)]
    import cv2
    cv2.imwrite(str(out_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 94])
    return round((cx - x0) / cw, 3)


def _cutout(fx, img, f, out_path, below=2.2):
    """Person cut-out (RGBA PNG) around the face, background removed. Returns the file name or None."""
    import numpy as np
    cv2 = fx.cv2
    H, W = img.shape[:2]
    x, y, w, h = (float(v) for v in f[:4])
    x0, x1 = int(max(0, x + w / 2 - w * 1.55)), int(min(W, x + w / 2 + w * 1.55))  # head and shoulders
    y0, y1 = int(max(0, y - h * 0.75)), int(min(H, y + h * below))
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    alpha = fx.person_mask(crop, (x + w / 2 - x0, y + h / 2 - y0), w)
    if alpha.mean() < 8:
        return None
    rgba = np.dstack([crop, alpha])
    cv2.imwrite(str(out_path), rgba)
    return out_path.name


def build(conn, tenant_id, asset_id, *, fetch=None, faces=None):
    """Find Jamar, Enrique and the guest in this episode's frames; save one portrait each."""
    fetch = fetch or _default_fetch
    fx = faces or _Faces()
    cv2 = fx.cv2
    a = conn.execute("SELECT * FROM assets WHERE tenant_id=? AND asset_id=?", (tenant_id, asset_id)).fetchone()
    if not a:
        raise LookupError("video not found")
    found = {}   # role → (face_width, img_path, face, score)
    guest_embs = []

    def scan(paths, center_only=False, guest_only=False):
        weight = 0.7 if center_only else 1.0  # prefer the episode's own frames over Shorts (captions, upscaling)
        hit = False
        for p in paths:
            img = cv2.imread(str(p))
            fs = fx.detect(img, 448, 832) if center_only else fx.detect(img)
            for f in fs:
                e = fx.embed(img, f)
                role, score = fx.who(e)
                if role == "unsure":
                    continue
                if role == "guest":
                    if guest_only and guest_embs and max(fx.sim(e, g) for g in guest_embs) < GUEST_MATCH:
                        continue
                    if not guest_only:
                        guest_embs.append(e)
                    hit = True
                ex = fx.expression(img, f)
                rank = min(float(f[2]), 220) * weight * (0.55 + ex["energy"])  # big AND animated beats big and flat
                if rank > found.get(role, (0,))[0]:
                    found[role] = (rank, str(p), f, round(score, 2), center_only, ex)
        return hit

    scan(_frames(tenant_id, asset_id, fetch))
    thumb = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if thumb.exists():  # the current thumbnail shows the guest (sharp, from this episode): a guest candidate too
        img = cv2.imread(str(thumb))
        for f in fx.detect(img):
            e = fx.embed(img, f)
            if fx.who(e)[0] == "guest":
                if not guest_embs or max(fx.sim(e, g) for g in guest_embs) >= GUEST_MATCH or "guest" not in found:
                    guest_embs.append(e)
                    ex = fx.expression(img, f)
                    rank = min(float(f[2]), 220) * 0.9 * (0.55 + ex["energy"])
                    if rank > found.get("guest", (0,))[0]:
                        found["guest"] = (rank, str(thumb), f, 0.0, False, ex)
    used_shorts = []
    SHARP = 105  # px: below this a face came from a wide shot; look for a close-up in the Shorts
    if a["format"] == "long_form" and guest_embs and (len(found) < 3 or any(v[2][2] < SHARP for v in found.values())):
        pub = date.fromisoformat((a["published_at"] or "2000-01-01")[:10])
        for s in conn.execute("SELECT asset_id, published_at FROM assets WHERE tenant_id=? AND format!='long_form'",
                              (tenant_id,)):
            if not s["published_at"] or abs((date.fromisoformat(s["published_at"][:10]) - pub).days) > SHORTS_WINDOW_DAYS:
                continue
            paths = _frames(tenant_id, s["asset_id"], fetch)
            before = dict(found)
            if scan(paths, center_only=True, guest_only=True):
                used_shorts.append(s["asset_id"])
            else:
                found.clear()  # frames of other recordings don't count: undo anything they added
                found.update(before)
            if len(found) == 3 and all(found[r][2][2] >= SHARP for r in found):
                break
    out_dir = DATA_DIR / "cast" / tenant_id / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cast = {}
    for role, (rank, path, f, score, short, ex) in found.items():
        img = cv2.imread(path)
        below = 1.25 if short else 1.9  # Shorts burn captions just under the chin
        focus = _crop(img, f, out_dir / f"{role}.jpg", below=below)
        cut = _cutout(fx, img, f, out_dir / f"{role}_cut.png", below=min(below + 0.2, 2.0))
        cast[role] = {"file": f"{role}.jpg", "cut": cut, "focus": focus, "face_px": int(f[2]), "match": score,
                      "expression": max(EMOTIONS, key=lambda k: ex[k]), "energy": ex["energy"],
                      "from": path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]}
    meta = {"asset_id": asset_id, "built_at": utcnow(), "cast": cast, "shorts_used": used_shorts}
    (out_dir / "cast.json").write_text(json.dumps(meta, indent=1))
    return meta


def load_cuts(tenant_id, asset_id):
    """{role: (cutout_png_path, meta)} for viral thumbnails."""
    p = DATA_DIR / "cast" / tenant_id / asset_id / "cast.json"
    try:
        meta = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return {r: (p.parent / c["cut"], c) for r, c in meta.get("cast", {}).items() if c.get("cut") and (p.parent / c["cut"]).exists()}


def load(tenant_id, asset_id):
    p = DATA_DIR / "cast" / tenant_id / asset_id / "cast.json"
    try:
        meta = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return {r: (p.parent / c["file"], c["focus"]) for r, c in meta.get("cast", {}).items() if (p.parent / c["file"]).exists()}
