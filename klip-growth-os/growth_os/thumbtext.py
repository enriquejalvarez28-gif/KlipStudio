"""Read the headline words on a video's current thumbnail (free local OCR:
OpenCV PP-OCRv3 text detection + CRNN recognition). Thumbnails belong to the
channel's other agent; we only read them so titles can work WITH the image.
Results are cached per thumbnail file hash. Returns "" when OpenCV or the
models aren't available.
"""

import hashlib
import json

from growth_os import cast
from growth_os.db import DATA_DIR

MIN_TEXT_PX = 80   # headline letters are big; small text (watermarks, captions) is ignored
_models = {}


def _load():
    if _models:
        return _models
    import cv2
    d = cast.ensure_models()
    det = cv2.dnn_TextDetectionModel_DB(str(d / cast.MODELS["ocr_det"][0]))
    det.setBinaryThreshold(0.3).setPolygonThreshold(0.5).setMaxCandidates(50).setUnclipRatio(2.0)
    det.setInputParams(1.0 / 255.0, (736, 416), (122.67891434, 116.66876762, 104.00698793), True)
    rec = cv2.dnn_TextRecognitionModel(str(d / cast.MODELS["ocr_rec"][0]))
    rec.setDecodeType("CTC-greedy").setVocabulary(list("0123456789abcdefghijklmnopqrstuvwxyz"))
    rec.setInputParams(1 / 127.5, (100, 32), (127.5, 127.5, 127.5), False)
    _models.update(cv2=cv2, det=det, rec=rec)
    return _models


def ocr(path):
    import numpy as np
    m = _load()
    cv2 = m["cv2"]
    img = cv2.resize(cv2.imread(str(path)), (1280, 720))
    boxes, _ = m["det"].detect(img)
    words = []
    for b in boxes:
        rect = cv2.minAreaRect(np.array(b, dtype=np.float32))
        src = cv2.boxPoints(rect).astype(np.float32)
        s, dif = src.sum(1), np.diff(src, axis=1).ravel()
        tl, br, tr, bl = src[np.argmin(s)], src[np.argmax(s)], src[np.argmin(dif)], src[np.argmax(dif)]
        w, h = int(max(rect[1])), int(min(rect[1]))
        if h < MIN_TEXT_PX or tl[0] > 680:  # RYJ headlines sit on the left; the right side is the photo/backdrop
            continue
        mtx = cv2.getPerspectiveTransform(np.array([bl, tl, tr, br], np.float32),
                                          np.array([[0, h], [0, 0], [w, 0], [w, h]], np.float32))
        crop = cv2.cvtColor(cv2.warpPerspective(img, mtx, (w, h)), cv2.COLOR_BGR2GRAY)
        t = m["rec"].recognize(crop).strip()
        if len(t) >= 2 and t != "ryj":
            words.append((int(tl[1] // 60), float(tl[0]), t))
    return " ".join(t for _, _, t in sorted(words))


def read(tenant_id, asset_id):
    p = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if not p.exists():
        return ""
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    cache = DATA_DIR / "cache" / "thumbtext" / tenant_id / f"{asset_id}.json"
    try:
        c = json.loads(cache.read_text())
        if c.get("hash") == h:
            return c["text"]
    except (OSError, ValueError):
        pass
    try:
        text = ocr(p)
    except Exception:  # OpenCV/models missing or unreadable image
        return ""
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"hash": h, "text": text}))
    return text
