"""High-quality cast photos: scan the episode's real 1080p video (not YouTube's 3 random auto-frames) and keep
the best shot of each person: sharp, big, facing the camera, eyes open, animated. Same quality for every episode.

Frames come from the channel's own public video stream (yt-dlp gives the URL; OpenCV reads single frames, nothing
is downloaded in full). Faces are never edited.
"""

import json
import math

from growth_os.db import DATA_DIR, utcnow

SAMPLES = 72
MIN_FACE = 150          # px in a 1080p frame; smaller = wide shot, not thumbnail quality
FORMAT = "bv*[vcodec^=avc1][height<=1080]/bv*[height<=1080]/best[height<=1080]"


def stream_url(video_id):
    import yt_dlp
    with yt_dlp.YoutubeDL({"format": FORMAT, "quiet": True, "no_warnings": True, "noplaylist": True}) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    return info["url"], float(info.get("duration") or 0)


def sample_frames(tenant_id, video_id, n=SAMPLES, progress=lambda m: None, workers=6):
    """Save ~n frames spread over the episode (5%–95%); resumable cache on disk. Returns [(path, seconds)]."""
    import threading
    import cv2
    d = DATA_DIR / "frames" / tenant_id / "hq" / video_id
    d.mkdir(parents=True, exist_ok=True)
    done_marker = d / "done.json"
    if done_marker.exists() and len(list(d.glob("*.jpg"))) >= n * 0.6:
        return [(p, int(p.stem)) for p in sorted(d.glob("*.jpg"))]
    url, dur = stream_url(video_id)
    if not dur:
        c = cv2.VideoCapture(url)
        dur = c.get(cv2.CAP_PROP_FRAME_COUNT) / max(c.get(cv2.CAP_PROP_FPS) or 30, 1)
        c.release()
    times = sorted({int(dur * (0.05 + 0.90 * i / max(n - 1, 1))) for i in range(n)})
    todo = [t for t in times if not (d / f"{t:05d}.jpg").exists()]
    lock, count = threading.Lock(), [len(times) - len(todo)]

    def work(chunk):
        for t in chunk:  # a fresh reader per frame: on Windows a reader returns nothing after its first seek
            cap = cv2.VideoCapture(url)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            cap.release()
            if ok and img is not None:
                cv2.imwrite(str(d / f"{t:05d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            with lock:
                count[0] += 1  # progress is reported from the main thread (the DB connection lives there)

    ths = [threading.Thread(target=work, args=(todo[k::workers],)) for k in range(workers)]
    for th in ths:
        th.start()
    import time
    while any(th.is_alive() for th in ths):
        time.sleep(2)
        progress(f"frame {count[0]}/{len(times)}")
    for th in ths:
        th.join()
    got = len(list(d.glob("*.jpg")))
    if got < len(times) * 0.6:
        raise RuntimeError(f"only {got}/{len(times)} frames could be read from the video")
    done_marker.write_text(json.dumps({"n": len(times), "at": utcnow()}))
    return [(p, int(p.stem)) for p in sorted(d.glob("*.jpg"))]


GAZE_MODEL = ("face_landmarker.task",
              "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task")
_GAZE = []


def _gaze_model():
    """MediaPipe face landmarker (free, local): blink and look-down scores per eye. None if unavailable."""
    if not _GAZE:
        try:
            import urllib.request
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
            from growth_os import cast as cm
            m = cm.model_dir() / GAZE_MODEL[0]
            if not m.exists() or m.stat().st_size < 1_000_000:
                with urllib.request.urlopen(GAZE_MODEL[1], timeout=120) as r:
                    m.write_bytes(r.read())
            opt = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(m)),
                                               output_face_blendshapes=True, num_faces=1)
            _GAZE.append((mp, vision.FaceLandmarker.create_from_options(opt)))
        except Exception:
            _GAZE.append(None)
    return _GAZE[0]


def gaze(cv2, img, f):
    """{'blink': 0..1, 'down': 0..1, 'smile': 0..1} for the face f, or None when the model isn't available."""
    g = _gaze_model()
    if g is None:
        return None
    mp, det = g
    x, y, w, h = (float(v) for v in f[:4])
    m = 0.6
    crop = img[max(0, int(y - h * m)):int(y + h * (1 + m)), max(0, int(x - w * m)):int(x + w * (1 + m))]
    if crop.size == 0:
        return None
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).copy()
    r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not r.face_blendshapes:
        return {"blink": 1.0, "down": 1.0, "smile": 0.0}  # no clear face: treat as unusable
    d = {b.category_name: b.score for b in r.face_blendshapes[0]}
    return {"blink": max(d["eyeBlinkLeft"], d["eyeBlinkRight"]),
            "down": (d["eyeLookDownLeft"] + d["eyeLookDownRight"]) / 2,
            "smile": (d["mouthSmileLeft"] + d["mouthSmileRight"]) / 2}


_EYES = []


def eyes_open(cv2, img, f):
    """True when at least one open eye is visible (closed eyes aren't detected by the eye cascade)."""
    if not _EYES:
        try:
            _EYES.append(cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml"))
        except Exception:
            _EYES.append(None)
    cc = _EYES[0]
    if cc is None or cc.empty():
        return True  # can't check on this install: don't block
    x, y, w, h = (int(v) for v in f[:4])
    top = img[max(0, y):max(0, y) + int(h * 0.6), max(0, x):x + w]
    if top.size == 0:
        return False
    g = cv2.equalizeHist(cv2.cvtColor(cv2.resize(top, (200, int(200 * top.shape[0] / max(top.shape[1], 1)))), cv2.COLOR_BGR2GRAY))
    return len(cc.detectMultiScale(g, 1.1, 5, minSize=(22, 22))) >= 1


def face_quality(cv2, img, f):
    """size 0..1, sharpness 0..1, yaw (0 = facing the camera; + = facing image-right)."""
    x, y, w, h = (float(v) for v in f[:4])
    size = min(w, 320) / 320
    crop = img[max(0, int(y)):int(y + h), max(0, int(x)):int(x + w)]
    if crop.size == 0:
        return 0, 0, 9.0
    g = cv2.cvtColor(cv2.resize(crop, (160, int(160 * h / max(w, 1)))), cv2.COLOR_BGR2GRAY)
    sharp = min(1.0, math.log1p(cv2.Laplacian(g, cv2.CV_64F).var()) / math.log1p(900))
    rex, rey, lex, ley, nx, ny = (float(f[k]) for k in (4, 5, 6, 7, 8, 9))
    eye_d = max(abs(lex - rex), 1.0)
    yaw = (nx - (rex + lex) / 2) / eye_d          # 0 = facing the camera
    return size, sharp, yaw


SLOT_SIDE = {"jamar": 1, "enrique": -1, "guest": 0}  # lineup slot: Jamar left (should face right), Enrique right (face left)


def facing_score(role, yaw):
    """1 = facing the camera; facing toward the middle of the lineup is fine; facing away from it = 0 (rejected)."""
    if abs(yaw) <= 0.15:
        return 1.0
    side = SLOT_SIDE.get(role, 0)
    if side == 0:  # the guest sits in the middle: should look at the camera
        return max(0.0, 1 - (abs(yaw) - 0.15) / 0.35)
    toward = yaw * side > 0
    return max(0.45, 1 - (abs(yaw) - 0.15) / 1.5) if toward else 0.0


def build_hq(conn, tenant_id, asset_id, *, faces=None, progress=lambda m: None):
    """Pick the best frame of Jamar, Enrique and the guest from the real video; writes cast.json like cast.build."""
    from growth_os import cast as cm
    fx = faces or cm._Faces()
    cv2 = fx.cv2
    frames = sample_frames(tenant_id, asset_id, progress=progress)
    cands = []  # (role, rank, path, face, score, embedding, expression)
    unknown = []
    for p, _t in frames:
        img = cv2.imread(str(p))
        for f in fx.detect(img):
            if f[2] < MIN_FACE:
                continue
            size, sharp, yaw = face_quality(cv2, img, f)
            if sharp < 0.45:
                continue  # blurry: never a thumbnail photo
            e = fx.embed(img, f)
            role, score = fx.who(e)
            if role == "unsure":
                continue
            frontal = facing_score(role, yaw)
            if frontal < 0.4:
                continue  # looking away from the others
            gz = gaze(cv2, img, f)
            if gz is not None:
                if gz["blink"] > 0.45 or gz["down"] > 0.5:
                    continue  # eyes closed or looking down
            elif not eyes_open(cv2, img, f):
                continue  # mid-blink (fallback check)
            ex = fx.expression(img, f)
            look = 1.0 if gz is None else (1 - gz["blink"]) * (1 - gz["down"]) * (0.8 + 0.4 * gz["smile"])
            rank = (size ** 0.5) * sharp * (frontal ** 1.5) * (0.7 + 0.6 * ex["energy"]) * float(f[14]) * look
            c = (role, rank, str(p), f, round(score, 2), e, ex)
            (unknown if role == "guest" else cands).append(c)
    # The guest = the biggest group of matching unknown faces (ignores a stray crew member or a TV in the back).
    groups = []
    for c in sorted(unknown, key=lambda c: -c[1]):
        for g in groups:
            if fx.sim(c[5], g[0][5]) >= cm.GUEST_MATCH:
                g.append(c)
                break
        else:
            groups.append([c])
    if groups:
        cands += max(groups, key=len)
    best = {}
    for c in cands:
        if c[1] > best.get(c[0], (None, 0))[1]:
            best[c[0]] = c
    if not best:
        raise RuntimeError("no sharp, camera-facing shots found in the video")
    out_dir = DATA_DIR / "cast" / tenant_id / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    flat = DATA_DIR / "frames" / tenant_id
    meta_cast = {}
    for role, (_, rank, path, f, score, _e, ex) in best.items():
        img = cv2.imread(path)
        name = f"{asset_id}_hq_{role}.jpg"  # lineup looks the source frame up in data/frames/<tenant>/
        cv2.imwrite(str(flat / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        focus = cm._crop(img, f, out_dir / f"{role}.jpg", below=1.9)
        meta_cast[role] = {"file": f"{role}.jpg", "cut": None, "focus": focus, "face_px": int(f[2]), "match": score,
                           "expression": max(cm.EMOTIONS, key=lambda k: ex[k]), "energy": ex["energy"],
                           "quality": round(rank, 3), "from": name}
    meta = {"asset_id": asset_id, "built_at": utcnow(), "cast": meta_cast, "source": "hq video frames",
            "frames_scanned": len(frames)}
    (out_dir / "cast.json").write_text(json.dumps(meta, indent=1))
    return meta
