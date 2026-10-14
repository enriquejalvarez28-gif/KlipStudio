"""Brand setup and the SYNTHETIC demo tenant.

RYJ Media gets real configuration only (topics, theme). No metrics are ever
written for it here.

The demo tenant ("Demo Studio") exists so every chart, filter,
lab and report can be exercised before real accounts are connected. Every
row it writes has data_quality='synthetic' and source='synthetic:demo-seed',
its tenant kind is 'demo', and the UI shows a banner on every page.
"""

import json
import math
import random
from datetime import date, datetime, timedelta, timezone

from growth_os import analytics, brands
from growth_os.db import DATA_DIR, utcnow

RYJ_TOPICS = [
    ("youth sports", 1.0), ("coaching", 1.0), ("recruiting", 1.0), ("NIL", 1.2), ("college athletes", 1.0),
    ("sports business", 0.9), ("athlete mental health", 0.9), ("injury prevention", 0.8), ("strength training", 0.7),
    ("women's sports", 0.9), ("sports agents", 0.8), ("transfer portal", 0.9), ("high school sports", 0.8),
    ("athlete development", 1.0),
]
DEMO = "demo-synthetic"


def ensure_ryj(conn):
    if not conn.execute("SELECT 1 FROM tenants WHERE tenant_id='ryj-media'").fetchone():
        brands.create_brand(conn, "RYJ Media", "owner", tenant_id="ryj-media",
                            theme_json=json.dumps({"accent": "#CFB53B", "base": "black"}))
    if not conn.execute("SELECT 1 FROM tenant_topics WHERE tenant_id='ryj-media'").fetchone():
        conn.executemany("INSERT INTO tenant_topics VALUES ('ryj-media',?,?)", RYJ_TOPICS)


TITLES = [
    "How elite coaches build confidence in young athletes", "The truth about NIL deals for high school stars",
    "Inside the transfer portal: what athletes wish they knew", "Recovery habits that prevent ACL injuries",
    "From walk-on to captain: a long road", "What scouts actually look for at showcases",
    "Mental toughness is a skill, here's how to train it", "Why multi-sport kids win later",
    "Building a sports agency from zero", "The parent's guide to recruiting emails",
    "Strength training myths for teenage athletes", "Women's college sports are booming. Now what?",
    "Coaching burnout and how to come back", "The business of youth tournaments",
    "Nutrition on a student-athlete budget", "Film study like a pro: a coach's method",
    "Ep 41 | Talking leadership with a D1 captain", "Ep 44 | Contracts, agents and the first deal",
    "Speed training that actually transfers to games", "When to specialize in one sport",
]
SHORT_TITLES = ["One drill for faster first steps", "The 10-second recruiting email fix", "Coach's halftime speech",
                "NIL in 45 seconds", "Ice bath or no ice bath?", "Captain's pre-game routine"]


def _thumb(path, rng, title):
    from PIL import Image, ImageDraw

    bg = rng.choice([(18, 18, 18), (32, 44, 80), (120, 24, 24), (230, 230, 225), (20, 90, 70), (200, 160, 40)])
    im = Image.new("RGB", (480, 270), bg)
    d = ImageDraw.Draw(im)
    # A "subject" block and a headline bar, with varied contrast.
    sx = rng.randint(20, 260)
    d.ellipse((sx, 40, sx + 170, 250), fill=tuple(min(255, c + rng.randint(40, 140)) for c in bg))
    if rng.random() < 0.7:
        d.rectangle((0, 190, 480, 250), fill=rng.choice([(207, 181, 59), (255, 255, 255), (0, 0, 0), (220, 40, 40)]))
        d.text((16, 205), title[:28].upper(), fill=(0, 0, 0) if rng.random() < 0.5 else (255, 255, 255))
    im.save(path, quality=85)


def seed_demo(conn, *, seed=7, days=365, today=None):
    if conn.execute("SELECT 1 FROM tenants WHERE tenant_id=?", (DEMO,)).fetchone():
        return {"skipped": "demo already seeded"}
    rng = random.Random(seed)
    today = today or date.today()
    brands.create_brand(conn, "Demo Studio", "owner", tenant_id=DEMO,
                        theme_json=json.dumps({"accent": "#7aa2f7", "base": "black"}))
    conn.execute("UPDATE tenants SET kind='demo' WHERE tenant_id=?", (DEMO,))
    conn.executemany(f"INSERT INTO tenant_topics VALUES ('{DEMO}',?,?)", RYJ_TOPICS)
    acct = brands.record_discovered(conn, DEMO, "youtube", platform_account_id="UC_SYNTHETIC_DEMO_CHANNEL",
                                    account_name="Demo Studio (synthetic)", handle="@synthetic-demo",
                                    connected_identity="synthetic seed — not a real account", actor="seed")
    brands.verify_identity(conn, DEMO, acct, confirmed_platform_account_id="UC_SYNTHETIC_DEMO_CHANNEL", owner="seed")
    brands.assign(conn, DEMO, acct, owner="seed")
    now = utcnow()
    src, q, ch = "synthetic:demo-seed", "synthetic", "UC_SYNTHETIC_DEMO_CHANNEL"
    conn.execute("UPDATE platform_accounts SET state='ACTIVE', last_successful_sync=?, data_as_of=? WHERE id=?",
                 (now, (today - timedelta(days=2)).isoformat(), acct))

    def put(asset, metric, value, grain, period, unit=""):
        conn.execute("""INSERT OR REPLACE INTO metrics (tenant_id, platform, platform_account_id, asset_id, episode_id,
                        published_at, metric_name, value, unit, grain, period_start, source, fetched_at, available_through,
                        data_quality) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (DEMO, "youtube", ch, asset, None, None, metric, value, unit or metric, grain, period, src, now,
                      (today - timedelta(days=2)).isoformat(), q))

    thumbs = DATA_DIR / "thumbs" / DEMO
    thumbs.mkdir(parents=True, exist_ok=True)
    vids = []
    for i in range(32):
        is_short = i % 4 == 3
        age = int(4 + i * (days - 10) / 32 + rng.randint(-3, 3))
        pub = datetime.combine(today - timedelta(days=age), datetime.min.time(), timezone.utc).replace(hour=15)
        title = SHORT_TITLES[(i // 4) % len(SHORT_TITLES)] if is_short else TITLES[(i - i // 4) % len(TITLES)]
        if not is_short and i - i // 4 >= len(TITLES):
            title += " (part 2)"
        vid = f"demo{i:03d}"
        dur = rng.randint(30, 59) if is_short else rng.randint(1900, 4200)
        _thumb(thumbs / f"{vid}.jpg", rng, title)
        (thumbs / f"{vid}.url").write_text(f"synthetic://{vid}")
        img_hash = analytics.file_hash(thumbs / f"{vid}.jpg")
        conn.execute("INSERT OR REPLACE INTO thumbnail_features VALUES (?,?,?,?,?)",
                     (DEMO, vid, img_hash, json.dumps(analytics.thumbnail_features(thumbs / f"{vid}.jpg")), now))
        conn.execute("INSERT OR REPLACE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (DEMO, "youtube", ch, vid, title, pub.isoformat().replace("+00:00", "Z"), dur,
                      "short_heuristic" if is_short else "long_form", None, f"etag{i}", now))
        quality = rng.lognormvariate(0, 0.45)
        imp = int((900 if is_short else 2500) * min(age, 120) ** 0.8 * quality)
        ctr = max(0.008, min(0.14, rng.gauss(0.045 if not is_short else 0.03, 0.014) * (quality ** 0.3)))
        views = int(imp * ctr * (3.5 if is_short else 1.2))
        avg_pct = max(8, min(95, rng.gauss(78 if is_short else 34, 9)))
        put(vid, "videoThumbnailImpressions", imp, "video_lifetime", "lifetime")
        put(vid, "videoThumbnailImpressionsClickRate", round(ctr * 100, 2), "video_lifetime", "lifetime")
        put(vid, "views", views, "video_lifetime", "lifetime")
        put(vid, "averageViewPercentage", round(avg_pct, 1), "video_lifetime", "lifetime")
        put(vid, "estimatedMinutesWatched", int(views * dur / 60 * avg_pct / 100), "video_lifetime", "lifetime")
        put(vid, "averageViewDuration", int(dur * avg_pct / 100), "video_lifetime", "lifetime")
        put(vid, "likes", int(views * rng.uniform(0.02, 0.05)), "video_lifetime", "lifetime")
        put(vid, "comments", int(views * rng.uniform(0.001, 0.006)), "video_lifetime", "lifetime")
        mix = {"YT_SEARCH": 0.3, "SUGGESTED": 0.28, "BROWSE": 0.22, "EXT_URL": 0.08, "SUBSCRIBER": 0.08, "SHORTS": 0.04}
        if is_short:
            mix = {"SHORTS": 0.8, "BROWSE": 0.08, "YT_SEARCH": 0.05, "SUGGESTED": 0.07}
        for k, share in mix.items():
            put(vid, "views", int(views * share * rng.uniform(0.7, 1.3)), "traffic_source", k)
        if not is_short:
            words = [w for w in title.lower().replace(":", "").replace("?", "").split() if len(w) > 3][:4]
            for j, term in enumerate([" ".join(words[:2]), " ".join(words[1:3]), words[0] + " tips", "sports podcast"]):
                put(vid, "views", int(views * 0.3 / (j + 1.5)), "search_term", term)
            for b in range(1, 101):
                x = b / 100
                base = 0.92 * math.exp(-1.6 * x) + 0.12 + (0.06 if 0.4 < x < 0.46 and i % 3 == 0 else 0)
                put(vid, "audienceWatchRatio", round(max(0.02, base * (avg_pct / 34) ** 0.4 - (0.12 if x < 0.06 and quality < 0.8 else 0)), 3),
                    "retention_bucket", f"ratio:{x:.2f}")
        for field, val in (("title", title), ("captions", "true" if rng.random() < 0.6 else "false"),
                           ("description", ("00:00 Intro\n03:10 Main topic\n" if rng.random() < 0.5 else "") + "Synthetic description."),
                           ("tags", json.dumps(["sports", "podcast"] if rng.random() < 0.7 else []))):
            conn.execute("INSERT OR IGNORE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",
                         (DEMO, "youtube", vid, field, val, f"{field}{i}", (pub + timedelta(minutes=5)).isoformat(), src))
        vids.append((vid, pub, views, is_short))
    # Two recorded title revisions (to exercise title history).
    for vid, old in (("demo002", "Transfer portal stories"), ("demo009", "Ep 12 | Agency talk")):
        pub = next(p for v, p, _, _ in vids if v == vid)
        conn.execute("INSERT OR IGNORE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",
                     (DEMO, "youtube", vid, "title", old, f"old{vid}", (pub - timedelta(minutes=1)).isoformat(), src))
    # Daily channel series: baseline + weekly cycle + bumps after publishes.
    for d in range(days):
        day = today - timedelta(days=days - 1 - d + 2)
        bump = sum(v * 0.08 * math.exp(-(day - p.date()).days / 4) for _, p, v, _ in vids if 0 <= (day - p.date()).days < 30)
        views = max(0, int((220 + d * 0.9) * (1 + 0.18 * math.sin(2 * math.pi * day.weekday() / 7)) + bump + rng.gauss(0, 25)))
        put(ch, "views", views, "day", day.isoformat())
        put(ch, "estimatedMinutesWatched", int(views * rng.uniform(3.2, 4.4)), "day", day.isoformat())
        put(ch, "averageViewDuration", int(rng.uniform(190, 260)), "day", day.isoformat())
        put(ch, "subscribersGained", max(0, int(views / 120 + rng.gauss(0, 1.5))), "day", day.isoformat())
        put(ch, "subscribersLost", max(0, int(views / 600 + rng.gauss(0, 0.8))), "day", day.isoformat())
    # Synthetic podcast imports (kept on their own platform; never summed with views).
    sp = brands.record_discovered(conn, DEMO, "spotify", platform_account_id="SYNTHETICSPOTIFYSHOW00",
                                  account_name="Demo Studio Podcast (synthetic)", actor="seed")
    brands.verify_identity(conn, DEMO, sp, confirmed_platform_account_id="SYNTHETICSPOTIFYSHOW00", owner="seed")
    brands.assign(conn, DEMO, sp, owner="seed")
    brands.mark(conn, DEMO, sp, brands.IMPORT_ONLY, actor="seed")
    for d in range(120):
        day = (today - timedelta(days=120 - d + 3)).isoformat()
        for metric, base in (("plays", 140), ("listeners", 95)):
            conn.execute("""INSERT OR REPLACE INTO metrics (tenant_id, platform, platform_account_id, asset_id, published_at,
                            metric_name, value, unit, grain, period_start, source, fetched_at, available_through, data_quality)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (DEMO, "spotify", "SYNTHETICSPOTIFYSHOW00", "SYNTHETICSPOTIFYSHOW00", None, metric,
                          int(base + d * 0.6 + rng.gauss(0, 12)), metric, "day", day, src, now, day, q))
    conn.execute("UPDATE platform_accounts SET data_as_of=?, last_successful_sync=? WHERE id=?",
                 ((today - timedelta(days=3)).isoformat(), now, sp))
    return {"seeded": DEMO, "videos": len(vids), "days": days}
