"""High-quality cast photos: scan the episode's real 1080p video (not YouTube's 3 random auto-frames) and keep
the best shot of each person: sharp, big, facing the camera, eyes open, animated. Same quality for every episode.

Frames come from the channel's own public video stream (yt-dlp gives the URL; OpenCV reads single frames, nothing
is downloaded in full). Faces are never edited.
"""

import json
import math

from growth_os.db import DATA_DIR, utcnow

SAMPLES = 40
MIN_FACE = 110          # px in a 1080p frame; smaller = wide shot, not thumbnail quality
FORMAT = "bv*[vcodec^=avc1][height<=1080]/bv*[height<=1080]/best[height<=1080]"


def stream_url(video_id):
    import yt_dlp
    with yt_dlp.YoutubeDL({"format": FORMAT, "quiet": True, "no_warnings": True, "noplaylist": True}) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    return info["url"], float(info.get("duration") or 0)


def sample_frames(tenant_id, video_id, n=SAMPLES, progress=lambda m: None):
    """Save ~n frames spread over the episode (5%–95%); cached on disk. Returns [(path, seconds)]."""
    import cv2
    d = DATA_DIR / "frames" / tenant_id / "hq" / video_id
    d.mkdir(parents=True, exist_ok=True)
    have = sorted(d.glob("*.jpg"))
    if len(have) >= n * 0.8:
        return [(p, int(p.stem)) for p in have]
    url, dur = stream_url(video_id)
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        raise RuntimeError("couldn't open the video stream")
    if not dur:
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS) or 30, 1)
    out = []
    for i in range(n):
        t = int(dur * (0.05 + 0.90 * i / max(n - 1, 1)))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if ok and img is not None:
            p = d / f"{t:05d}.jpg"
            cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            out.append((p, t))
        progress(f"frame {i + 1}/{n}")
    cap.release()
    return out


def face_quality(cv2, img, f):
    """0..1 parts: size, sharpness, frontal (looking at camera / not turned away)."""
    x, y, w, h = (float(v) for v in f[:4])
    size = min(w, 320) / 320
    crop = img[max(0, int(y)):int(y + h), max(0, int(x)):int(x + w)]
    if crop.size == 0:
        return 0, 0, 0
    g = cv2.cvtColor(cv2.resize(crop, (160, int(160 * h / max(w, 1)))), cv2.COLOR_BGR2GRAY)
    sharp = min(1.0, math.log1p(cv2.Laplacian(g, cv2.CV_64F).var()) / math.log1p(900))
    rex, rey, lex, ley, nx, ny = (float(f[k]) for k in (4, 5, 6, 7, 8, 9))
    eye_d = max(abs(lex - rex), 1.0)
    yaw = (nx - (rex + lex) / 2) / eye_d          # 0 = facing the camera
    frontal = max(0.0, 1 - abs(yaw) / 0.38)
    return size, sharp, frontal


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
            size, sharp, frontal = face_quality(cv2, img, f)
            if frontal < 0.45 or sharp < 0.35:
                continue  # turned away or blurry: never a thumbnail photo
            e = fx.embed(img, f)
            role, score = fx.who(e)
            if role == "unsure":
                continue
            ex = fx.expression(img, f)
            rank = (size ** 0.5) * sharp * (frontal ** 1.5) * (0.7 + 0.6 * ex["energy"]) * float(f[14])
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
