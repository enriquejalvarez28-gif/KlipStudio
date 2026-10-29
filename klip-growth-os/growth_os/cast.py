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

MODELS = {
    "det": ("face_detection_yunet_2023mar.onnx",
            "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    "rec": ("face_recognition_sface_2021dec.onnx",
            "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"),
}
HOST_MATCH = 0.62      # SFace cosine: real host matches score 0.66–1.0 on RYJ frames; look-alikes 0.55–0.57; guests < 0.40
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
        if not p.exists() or p.stat().st_size < 100_000:
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


def _crop(img, f, out_path):
    """Portrait around the face: shoulders up, face a bit above center. Returns horizontal focus (0–1)."""
    H, W = img.shape[:2]
    x, y, w, h = (float(v) for v in f[:4])
    cw = min(W, w * 2.6)
    top, bot = max(0, y - h * 1.0), min(H, y + h * 2.4)  # shoulders up: stops above burned-in captions
    cx = x + w / 2
    x0 = int(max(0, min(W - cw, cx - cw / 2)))
    crop = img[int(top):int(bot), x0:int(x0 + cw)]
    import cv2
    cv2.imwrite(str(out_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 94])
    return round((cx - x0) / cw, 3)


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
                if f[2] > found.get(role, (0,))[0]:
                    found[role] = (float(f[2]), str(p), f, round(score, 2))
        return hit

    scan(_frames(tenant_id, asset_id, fetch))
    thumb = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if thumb.exists():  # the current thumbnail shows the guest; use it to recognise them in Shorts
        img = cv2.imread(str(thumb))
        for f in fx.detect(img):
            e = fx.embed(img, f)
            if fx.who(e)[0] == "guest":
                guest_embs.append(e)
    used_shorts = []
    if a["format"] == "long_form" and guest_embs and len(found) < 3:
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
            if len(found) == 3 and all(found[r][0] >= 120 for r in found):
                break
    out_dir = DATA_DIR / "cast" / tenant_id / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cast = {}
    for role, (w, path, f, score) in found.items():
        img = cv2.imread(path)
        focus = _crop(img, f, out_dir / f"{role}.jpg")
        cast[role] = {"file": f"{role}.jpg", "focus": focus, "face_px": int(w), "match": score,
                      "from": path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]}
    meta = {"asset_id": asset_id, "built_at": utcnow(), "cast": cast, "shorts_used": used_shorts}
    (out_dir / "cast.json").write_text(json.dumps(meta, indent=1))
    return meta


def load(tenant_id, asset_id):
    p = DATA_DIR / "cast" / tenant_id / asset_id / "cast.json"
    try:
        meta = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return {r: (p.parent / c["file"], c["focus"]) for r, c in meta.get("cast", {}).items() if (p.parent / c["file"]).exists()}
