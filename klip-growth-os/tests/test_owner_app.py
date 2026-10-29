"""Owner app acceptance tests (directive §12): scheduler, persistence,
isolation over HTTP, no invented metrics, evidence on suggestions, trends,
AI caching/caps, reports, incremental YouTube sync."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from http.server import ThreadingHTTPServer

import tests  # noqa: F401  (sets GROWTH_OS_DATA before growth_os imports)
from growth_os import ai, analytics, api, brands, db, reports, scheduler, seed, thumbs, trends
from growth_os.connectors import youtube, youtube_reporting, youtube_sync
from growth_os.db import utcnow
from tests.test_brand_manager import CLIENT, RYJ_CH, FakeGoogle, id_token


def fresh(path=None):
    path = path or os.path.join(tempfile.mkdtemp(), "t.db")
    c = db.connect(path)
    seed.ensure_ryj(c)
    return c, path


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.c, self.path = fresh()
        scheduler.ensure_defaults(self.c)

    def test_next_slot(self):
        tz = datetime.now().astimezone().tzinfo
        t = datetime(2026, 10, 14, 7, 30, tzinfo=tz)  # a Wednesday
        self.assertEqual(scheduler.next_slot({"every_hours": 6}, t).hour, 12)
        self.assertEqual(scheduler.next_slot({"daily_at": "07:00"}, t).day, 15)
        self.assertEqual(scheduler.next_slot({"daily_at": "08:00"}, t).hour, 8)
        w = scheduler.next_slot({"weekly": "MON", "at": "08:00"}, t)
        self.assertEqual((w.weekday(), w.day), (0, 19))
        m = scheduler.next_slot({"monthly_day": 1, "at": "08:30"}, t)
        self.assertEqual((m.month, m.day), (11, 1))
        self.assertEqual(scheduler.next_slot({"monthly_day": 1, "at": "08:30"}, datetime(2026, 12, 5, tzinfo=tz)).year, 2027)

    def test_slot_dedup_and_manual_dedup(self):
        a = scheduler.enqueue(self.c, "daily_review", schedule_name="daily_review", trigger="schedule", slot="S1")
        b = scheduler.enqueue(self.c, "daily_review", schedule_name="daily_review", trigger="schedule", slot="S1")
        self.assertTrue(a[1])
        self.assertFalse(b[1])
        m1 = scheduler.enqueue(self.c, "packaging_check", tenant_id="ryj-media")
        m2 = scheduler.enqueue(self.c, "packaging_check", tenant_id="ryj-media")
        self.assertEqual(m1[0], m2[0])
        self.assertFalse(m2[1])

    def test_missed_slots_collapse_and_run(self):
        past = (scheduler.local_now() - timedelta(days=3)).isoformat()
        self.c.execute("UPDATE schedules SET next_run_at=? WHERE name='daily_review'", (past,))
        calls = []
        reg = {"daily_review": lambda c, t, p: calls.append(1) or {"ok": 1}}
        scheduler.tick(self.c, reg)
        scheduler.tick(self.c, reg)
        self.assertEqual(len(calls), 1)
        s = self.c.execute("SELECT * FROM schedules WHERE name='daily_review'").fetchone()
        self.assertEqual(s["last_status"], "succeeded")
        self.assertGreater(s["next_run_at"], scheduler.local_now().isoformat())

    def test_retry_then_alert(self):
        def boom(c, t, p):
            raise RuntimeError("source down")
        reg = {"daily_review": boom}
        run_id, _ = scheduler.enqueue(self.c, "daily_review", schedule_name="daily_review", trigger="schedule", slot="X")
        for _ in range(3):
            scheduler.tick(self.c, reg)
            self.c.execute("UPDATE job_runs SET next_retry_at='2000-01-01' WHERE state='retry'")
        r = self.c.execute("SELECT * FROM job_runs WHERE run_id=?", (run_id,)).fetchone()
        self.assertEqual((r["state"], r["attempt"]), ("failed", 3))
        alert = self.c.execute("SELECT * FROM alerts").fetchone()
        self.assertIn("source down", alert["message"])

    def test_lease_blocks_second_instance(self):
        self.assertTrue(scheduler._lease(self.c))
        other = db.connect(self.path)
        holder = scheduler.HOLDER
        scheduler.HOLDER = "someone-else"
        try:
            self.assertFalse(scheduler._lease(other))
        finally:
            scheduler.HOLDER = holder

    def test_interrupted_run_recovers(self):
        run_id, _ = scheduler.enqueue(self.c, "daily_review")
        self.c.execute("UPDATE job_runs SET state='running' WHERE run_id=?", (run_id,))
        scheduler.recover(self.c)
        self.assertEqual(self.c.execute("SELECT state FROM job_runs WHERE run_id=?", (run_id,)).fetchone()[0], "retry")

    def test_background_thread_executes_and_logs(self):
        sched = scheduler.Scheduler({"daily_review": lambda c, t, p: {"reviewed": True}}, self.path)
        run_id, _ = scheduler.enqueue(self.c, "daily_review")
        sched.start()
        try:
            self.assertEqual(scheduler.wait_for(self.c, run_id, 15), "succeeded")
        finally:
            sched.stop.set()
            sched.join(5)
        res = json.loads(self.c.execute("SELECT result_json FROM job_runs WHERE run_id=?", (run_id,)).fetchone()[0])
        self.assertEqual(res, {"reviewed": True})


class TestPersistenceAndTruth(unittest.TestCase):
    def test_database_survives_restart(self):
        c, path = fresh()
        seed.seed_demo(c)
        scheduler.ensure_defaults(c)
        c.execute("INSERT INTO calendar_items VALUES ('cal_1','ryj-media','2026-11-02','NIL episode','episode','idea','',NULL,'t')")
        nxt = c.execute("SELECT next_run_at FROM schedules WHERE name='weekly_report'").fetchone()[0]
        c.close()
        c2 = db.connect(path)
        scheduler.ensure_defaults(c2)
        self.assertEqual(c2.execute("SELECT title FROM calendar_items").fetchone()[0], "NIL episode")
        self.assertEqual(c2.execute("SELECT next_run_at FROM schedules WHERE name='weekly_report'").fetchone()[0], nxt)
        self.assertGreater(c2.execute("SELECT COUNT(*) FROM metrics WHERE tenant_id='demo-synthetic'").fetchone()[0], 1000)

    def test_no_invented_production_metrics(self):
        c, _ = fresh()
        seed.seed_demo(c)
        analytics.packaging_check(c, "ryj-media")
        analytics.daily_review(c, "ryj-media")
        for table in ("metrics", "assets", "recommendations", "thumbnail_features"):
            self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id='ryj-media'").fetchone()[0], 0, table)
        self.assertEqual({r[0] for r in c.execute("SELECT DISTINCT data_quality FROM metrics")}, {"synthetic"})
        self.assertEqual({r[0] for r in c.execute("SELECT DISTINCT source FROM metrics")}, {"synthetic:demo-seed"})
        h = api.home(c, "ryj-media")
        self.assertEqual((h["kpis"]["28"], h["best"], h["recommendations"]), ([], [], []))
        self.assertEqual(api.video_list(c, "ryj-media"), [])
        rep = reports.generate(c, "ryj-media", "manual")
        with open(rep["path"]) as f:
            html = f.read()
        self.assertIn("No platform data yet", html)
        self.assertNotIn("synthetic", html.lower().replace("synthetic demo", ""))

    def test_suggestions_carry_evidence(self):
        c, _ = fresh()
        seed.seed_demo(c)
        self.assertGreater(analytics.packaging_check(c, "demo-synthetic"), 0)
        self.assertEqual(analytics.packaging_check(c, "demo-synthetic"), 0)  # fingerprint dedup
        for r in c.execute("SELECT * FROM recommendations"):
            ev = json.loads(r["evidence_json"])
            self.assertEqual(r["basis"], "derived")
            self.assertTrue(any(e.get("peer_median") is not None and e.get("percentile") is not None for e in ev))
            self.assertTrue(any("peers" in e for e in ev))
        th = api.thumbnails(c, "demo-synthetic")
        self.assertGreaterEqual(th["association_n"], 8)
        self.assertTrue(th["association"])
        d = api.video_detail(c, "demo-synthetic", "demo005")
        self.assertTrue(d["peers"]["basis"])
        self.assertTrue(d["thumbnail"]["features"]["unavailable"])


class TestHttpIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from growth_os import server
        cls.c, cls.path = fresh()
        seed.seed_demo(cls.c)
        scheduler.ensure_defaults(cls.c)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.srv.db_path = cls.path
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.csrf = server.CSRF

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, path, body=None, headers=None, method=None):
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pages_and_static(self):
        for p in ("/", "/app.js", "/charts.js", "/app.css", "/manifest.webmanifest", "/sw.js", "/icon-192.png"):
            self.assertEqual(self.req(p)[0], 200, p)
        for page in ("home", "overview?days=28", "videos", "thumbnails", "titles", "seo", "trends", "recommendations",
                     "calendar", "podcasts", "settings", "tiles", "reports"):
            for t in ("ryj-media", "demo-synthetic"):
                self.assertEqual(self.req(f"/api/t/{t}/{page}")[0], 200, f"{t}/{page}")
        self.assertEqual(self.req("/api/jobs")[0], 200)

    def test_cross_tenant_access_is_not_found(self):
        self.assertEqual(self.req("/api/t/demo-synthetic/video/demo005")[0], 200)
        self.assertEqual(self.req("/api/t/demo-synthetic/thumb/demo005.jpg")[0], 404)
        self.assertEqual(self.req("/thumb/demo-synthetic/demo005.jpg")[0], 200)
        self.assertEqual(self.req("/api/t/ryj-media/video/demo005")[0], 404)
        self.assertEqual(self.req("/thumb/ryj-media/demo005.jpg")[0], 404)
        rec = self.c.execute("SELECT id FROM recommendations WHERE tenant_id='demo-synthetic' LIMIT 1").fetchone()
        if not rec:
            analytics.packaging_check(self.c, "demo-synthetic")
            rec = self.c.execute("SELECT id FROM recommendations WHERE tenant_id='demo-synthetic' LIMIT 1").fetchone()
        code, _ = self.req(f"/api/t/ryj-media/recommendations/{rec[0]}/status", {"status": "dismissed"}, {"X-CSRF": self.csrf})
        self.assertEqual(code, 404)
        rid = reports.generate(self.c, "demo-synthetic", "manual")["report_id"]
        self.assertEqual(self.req(f"/api/t/ryj-media/reports/{rid}.html")[0], 404)
        self.assertEqual(self.req(f"/api/t/demo-synthetic/reports/{rid}.html")[0], 200)
        csv_body = self.req("/api/t/ryj-media/export/videos.csv")[1].decode()
        self.assertNotIn("demo0", csv_body)

    def test_csrf_and_host_checks(self):
        self.assertEqual(self.req("/api/jobs/daily_review/run", {})[0], 403)
        self.assertEqual(self.req("/api/app", headers={"Host": "evil.example"})[0], 403)
        code, body = self.req("/api/jobs/daily_review/run", {"tenant_id": "ryj-media"}, {"X-CSRF": self.csrf})
        self.assertEqual(code, 200)
        self.assertIn(b"run_id", body)

    def test_calendar_roundtrip(self):
        code, body = self.req("/api/t/ryj-media/calendar", {"day": "2026-11-03", "title": "Transfer portal deep dive"}, {"X-CSRF": self.csrf})
        self.assertEqual(code, 200)
        cal = json.loads(self.req("/api/t/ryj-media/calendar?month=2026-11")[1])
        self.assertEqual([i["title"] for i in cal["items"]], ["Transfer portal deep dive"])
        self.assertEqual(json.loads(self.req("/api/t/demo-synthetic/calendar?month=2026-11")[1])["items"], [])


NEWS = b"""<?xml version="1.0"?><rss><channel>
<item><title>NIL collectives reshape college athletes recruiting</title><link>https://ex.com/a</link>
<pubDate>Tue, 13 Oct 2026 12:00:00 GMT</pubDate><source url="https://ex.com">Example Sports</source></item>
<item><title>NIL collectives reshape recruiting for college athletes, report says</title><link>https://ex2.com/b</link>
<pubDate>Tue, 13 Oct 2026 15:00:00 GMT</pubDate><source url="https://ex2.com">Other Wire</source></item>
<item><title>Stock market closes higher</title><link>https://ex.com/c</link><pubDate>Tue, 13 Oct 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""
TRENDS = b"""<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
<item><title>transfer portal</title><link>https://trends.google.com/x</link><ht:approx_traffic>20000+</ht:approx_traffic>
<pubDate>Wed, 14 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>celebrity wedding</title><link>https://trends.google.com/y</link><pubDate>Wed, 14 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


class TestTrends(unittest.TestCase):
    def transport(self, method, url, headers, body):
        if url.startswith(trends.NEWS_RSS):
            return 200, NEWS
        if url.startswith(trends.TRENDS_RSS):
            return 200, TRENDS
        return 404, b""

    def test_research_scores_with_sources_and_filters_unrelated(self):
        c, _ = fresh()
        now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        res = trends.research(c, "ryj-media", transport=self.transport, now=now)
        self.assertFalse(res["errors"])
        rows = {r["title"]: r for r in c.execute("SELECT * FROM trends WHERE tenant_id='ryj-media'")}
        self.assertIn("transfer portal", rows)
        self.assertNotIn("celebrity wedding", rows)
        self.assertNotIn("Stock market closes higher", rows)
        a = rows["NIL collectives reshape college athletes recruiting"]
        parts = json.loads(a["score_json"])
        self.assertEqual(set(trends.WEIGHTS) - set(parts), set())
        self.assertTrue(a["url"].startswith("https://") and a["published_at"] and a["source"] == "Example Sports")
        self.assertTrue(a["uncertainty"].startswith("medium"), a["uncertainty"])  # 2 outlets, counted once each
        self.assertEqual(parts["sources_in_cluster"], 2)
        self.assertEqual(json.loads(rows["transfer portal"]["score_json"])["google_trends_approx_traffic"], "20000+")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM trends WHERE tenant_id='demo-synthetic'").fetchone()[0], 0)

    def test_no_topics_skips(self):
        c, _ = fresh()
        brands.create_brand(c, "Empty", "owner", tenant_id="empty")
        self.assertIn("skipped", trends.research(c, "empty", transport=self.transport))


class TestAI(unittest.TestCase):
    def runner(self, prompt, model):
        self.calls += 1
        return {"result": '```json\n{"titles":[{"strategy":"curiosity","title":"X","why":"y"}]}\n```',
                "usage": {"input_tokens": 100, "output_tokens": 20}, "total_cost_usd": 0.001,
                "modelUsage": {"claude-haiku-5-5": {}}}

    def test_cache_cap_and_disable(self):
        self.calls = 0
        c, _ = fresh()
        out, meta = ai.ask(c, "ryj-media", "titles:v1", {"title": "a"}, "inst", runner=self.runner)
        self.assertEqual(out["titles"][0]["title"], "X")
        self.assertFalse(meta["cached"])
        _, meta2 = ai.ask(c, "ryj-media", "titles:v1", {"title": "a"}, "inst", runner=self.runner)
        self.assertTrue(meta2["cached"])
        self.assertEqual(self.calls, 1)
        with self.assertRaises(Exception):  # cache never crosses tenants: other tenant must call again
            db.set_setting(c, "ai.daily_calls", 1)
            ai.ask(c, "demo-synthetic", "titles:v1", {"title": "a"}, "inst", runner=self.runner)
        db.set_setting(c, "ai.enabled", False)
        with self.assertRaises(ai.AIUnavailable):
            ai.ask(c, "ryj-media", "titles:v2", {"title": "b"}, "inst", runner=self.runner)
        row = c.execute("SELECT * FROM usage_log WHERE kind='llm' AND cache_hit=0").fetchone()
        self.assertEqual((row["tokens_in"], row["tokens_out"]), (100, 20))


class SyncGoogle(FakeGoogle):
    def __init__(self):
        super().__init__([(RYJ_CH, "Respect Your Journey")])
        self.title = "Ep 12 | Talking NIL"
        self.etag = "e1"

    def __call__(self, method, url, headers, body):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if "/videos" in url and "status" in q.get("part", ""):
            return 200, json.dumps({"items": [{"id": "vLong", "etag": self.etag,
                                               "snippet": {"title": self.title, "publishedAt": "2026-09-01T00:00:00Z", "description": "00:00 Intro"},
                                               "contentDetails": {"duration": "PT48M", "caption": "true"}}]}).encode()
        if url.startswith(youtube.ANALYTICS_API) and q.get("dimensions") == "video":
            return 200, json.dumps({"columnHeaders": [{"name": n} for n in ("video", "views", "averageViewPercentage")],
                                    "rows": [["vLong", 900, 41.0]]}).encode()
        if url.startswith(youtube.ANALYTICS_API) and q.get("dimensions") == "insightTrafficSourceType":
            return 200, json.dumps({"rows": [["YT_SEARCH", 500], ["SUGGESTED", 400]]}).encode()
        if url.startswith(youtube.ANALYTICS_API) and q.get("dimensions") == "insightTrafficSourceDetail":
            return 200, json.dumps({"rows": [["nil podcast", 120]]}).encode()
        return super().__call__(method, url, headers, body)


class TestIncrementalSync(unittest.TestCase):
    def test_sync_history_and_delta(self):
        c, _ = fresh()
        g = SyncGoogle()
        url = youtube.begin_auth(c, "ryj-media", "http://127.0.0.1/cb", CLIENT)
        st = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        [row] = youtube.finish_auth(c, state=st, code="x", client=CLIENT, transport=g)[1]
        brands.verify_identity(c, "ryj-media", row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        brands.assign(c, "ryj-media", row, owner="owner")
        r1 = youtube_sync.sync(c, "ryj-media", row, client=CLIENT, transport=g, today=date(2026, 10, 14))
        self.assertEqual((r1["metadata_changed"], r1["breakdowns_for"]), (1, ["vLong"]))
        r2 = youtube_sync.sync(c, "ryj-media", row, client=CLIENT, transport=g, today=date(2026, 10, 14))
        self.assertEqual((r2["metadata_changed"], r2["breakdowns_for"]), (0, []))  # etag + unchanged views skipped
        g.title, g.etag = "How NIL deals really work for athletes", "e2"
        youtube_sync.sync(c, "ryj-media", row, client=CLIENT, transport=g, today=date(2026, 10, 14))
        titles = [r[0] for r in c.execute("SELECT value FROM asset_history WHERE field='title' ORDER BY observed_at")]
        self.assertEqual(titles, ["Ep 12 | Talking NIL", "How NIL deals really work for athletes"])
        cur = c.execute("SELECT value FROM sync_cursors WHERE name='daily_through'").fetchone()[0]
        self.assertEqual(cur, "2026-10-11")
        d = api.video_detail(c, "ryj-media", "vLong")
        self.assertEqual(d["search_terms"], [{"term": "nil podcast", "views": 120.0}])
        self.assertEqual(d["video"]["quality"], "verified")


class ReachGoogle(SyncGoogle):
    """SyncGoogle plus the Reporting API (reach report type, job, one daily CSV)."""

    def __init__(self):
        super().__init__()
        self.jobs, self.posts, self.downloads = [], 0, 0

    def __call__(self, method, url, headers, body):
        R = youtube_reporting.REPORTING_API
        if url.startswith(R + "/reportTypes"):
            return 200, json.dumps({"reportTypes": [{"id": "channel_basic_a2"}, {"id": "channel_reach_basic_a1"}]}).encode()
        if url.startswith(R + "/jobs") and "/reports" in url:
            return 200, json.dumps({"reports": [{"id": "r1", "startTime": "2026-10-10T07:00:00Z",
                                                 "createTime": "2026-10-12T00:00:00Z",
                                                 "downloadUrl": "https://youtubereporting.googleapis.com/v1/media/r1"}]}).encode()
        if url.startswith(R + "/jobs") and method == "POST":
            self.posts += 1
            self.jobs.append({"id": "job1", "reportTypeId": json.loads(body)["reportTypeId"]})
            return 200, json.dumps(self.jobs[-1]).encode()
        if url.startswith(R + "/jobs"):
            return 200, json.dumps({"jobs": self.jobs}).encode()
        if url.startswith(R + "/media/"):
            self.downloads += 1
            csv_text = ("date,channel_id,video_id,traffic_source_type,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
                        "20261010,UCx,vLong,1,3000,0.05\n20261010,UCx,vLong,2,1000,0.01\n20261010,UCx,vShort,1,0,0\n")
            return 200, csv_text.encode()
        return super().__call__(method, url, headers, body)


class TestReachReports(unittest.TestCase):
    def test_parse_weights_ctr_by_impressions(self):
        rows = youtube_reporting.parse_reach_csv(
            "date,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
            "20261010,v1,3000,0.05\n20261010,v1,1000,0.01\n")
        imp, ctr = rows[("2026-10-10", "v1")]
        self.assertEqual(imp, 4000)
        self.assertAlmostEqual(ctr, 0.04)

    def test_sync_creates_job_once_and_stores_impressions(self):
        c, _ = fresh()
        g = ReachGoogle()
        url = youtube.begin_auth(c, "ryj-media", "http://127.0.0.1/cb", CLIENT)
        st = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        [row] = youtube.finish_auth(c, state=st, code="x", client=CLIENT, transport=g)[1]
        brands.verify_identity(c, "ryj-media", row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        brands.assign(c, "ryj-media", row, owner="owner")
        r1 = youtube_sync.sync(c, "ryj-media", row, client=CLIENT, transport=g, today=date(2026, 10, 14))
        self.assertEqual((r1["reach"]["report_type"], r1["reach"]["job_created"], r1["reach"]["reports_downloaded"]),
                         ("channel_reach_basic_a1", True, 1))
        r2 = youtube_sync.sync(c, "ryj-media", row, client=CLIENT, transport=g, today=date(2026, 10, 14))
        self.assertEqual((g.posts, g.downloads, r2["reach"]["reports_downloaded"]), (1, 1, 0))  # reused, not re-downloaded
        v = {x["asset_id"]: x for x in analytics.videos(c, "ryj-media")}["vLong"]["metrics"]
        self.assertEqual(v["videoThumbnailImpressions"], 4000)
        self.assertAlmostEqual(v["videoThumbnailImpressionsClickRate"], 4.0)
        self.assertFalse(any(u.startswith("impressions/CTR not returned") for u in r2["unavailable"]))


class MoneyGoogle(ReachGoogle):
    """Adds the Shorts/long-form split and retention curves."""

    def __call__(self, method, url, headers, body):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if url.startswith(youtube.ANALYTICS_API) and q.get("dimensions") == "day,creatorContentType":
            rows = []
            for i in range(30):
                d = (date(2026, 10, 11) - timedelta(days=i)).isoformat()
                rows += [[d, "videoOnDemand", 100, 600], [d, "shorts", 1000, 300]]  # API casing
            return 200, json.dumps({"columnHeaders": [{"name": n} for n in ("day", "creatorContentType", "views", "estimatedMinutesWatched")],
                                    "rows": rows}).encode()
        dims = q.get("dimensions")
        if url.startswith(youtube.ANALYTICS_API) and dims == "day,insightTrafficSourceType":
            return 200, json.dumps({"columnHeaders": [{"name": n} for n in ("day", "insightTrafficSourceType", "views", "estimatedMinutesWatched")],
                                    "rows": [["2026-10-05", "SHORTS", 500, 100], ["2026-10-05", "YT_SEARCH", 20, 30],
                                             ["2026-10-12", "SHORTS", 700, 150]]}).encode()
        if url.startswith(youtube.ANALYTICS_API) and dims == "ageGroup,gender":
            return 200, json.dumps({"columnHeaders": [{"name": n} for n in ("ageGroup", "gender", "viewerPercentage")],
                                    "rows": [["age18-24", "male", 40.0], ["age25-34", "male", 35.0], ["age25-34", "female", 25.0]]}).encode()
        if url.startswith(youtube.ANALYTICS_API) and dims in ("country", "deviceType", "subscribedStatus"):
            vals = {"country": ["US", "CA"], "deviceType": ["MOBILE", "DESKTOP"], "subscribedStatus": ["UNSUBSCRIBED", "SUBSCRIBED"]}[dims]
            return 200, json.dumps({"columnHeaders": [{"name": n} for n in (dims, "views", "estimatedMinutesWatched", "averageViewDuration")],
                                    "rows": [[vals[0], 900, 1200, 60], [vals[1], 100, 600, 300]]}).encode()
        if url.startswith(youtube.ANALYTICS_API) and q.get("dimensions") == "elapsedVideoTimeRatio":
            return 200, json.dumps({"columnHeaders": [{"name": n} for n in ("elapsedVideoTimeRatio", "audienceWatchRatio", "relativeRetentionPerformance")],
                                    "rows": [[0.0, 1.0, 0.5], [0.1, 0.7, 0.5], [0.5, 1.2, 0.6], [1.0, 0.3, 0.5]]}).encode()
        return super().__call__(method, url, headers, body)


class TestMonetizationAndRewatch(unittest.TestCase):
    def test_sync_feeds_monetization_and_retention(self):
        c, _ = fresh()
        g = MoneyGoogle()
        url = youtube.begin_auth(c, "ryj-media", "http://127.0.0.1/cb", CLIENT)
        st = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        [row] = youtube.finish_auth(c, state=st, code="x", client=CLIENT, transport=g)[1]
        brands.verify_identity(c, "ryj-media", row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        brands.assign(c, "ryj-media", row, owner="owner")
        r = youtube_sync.sync(c, "ryj-media", row, client=CLIENT, transport=g, today=date(2026, 10, 14))
        self.assertEqual(r["content_type_days"], 60)
        self.assertIn("vLong", r["retention_fetched"])
        m = analytics.monetization(c, "ryj-media")
        self.assertEqual(m["long_form_watch_hours_365d"], 300.0)  # 30 days x 600 min / 60
        self.assertEqual(m["shorts_views_90d"], 30000)
        self.assertEqual(m["subscribers"], 1200)
        full = next(t for t in m["tiers"] if t["id"] == "full")
        self.assertTrue(full["subs_ok"])
        self.assertEqual(full["watch_hours_gap"], 3700.0)
        self.assertEqual(full["days_to_watch_hours_at_pace"], 370)  # 10 h/day pace
        self.assertFalse(full["eligible_by_numbers"])
        d = api.video_detail(c, "ryj-media", "vLong")
        self.assertEqual((d["rewatch"]["peak_ratio"], d["rewatch"]["peak_at_pct"]), (1.2, 50))
        self.assertEqual(d["rewatch"]["biggest_drop_at_pct"], 50)
        self.assertEqual(r["traffic_days"], 3)
        tt = analytics.traffic_over_time(c, "ryj-media")
        self.assertEqual(tt["series"][0]["source"], "SHORTS")
        self.assertEqual(sum(p["v"] for p in tt["series"][0]["points"]), 1200)
        fc = {x["label"]: x for x in analytics.formats_compare(c, "ryj-media", 28)["types"]}
        self.assertEqual((fc["Long-form"]["views"], fc["Shorts"]["watch_hours"]), (2800, 140.0))
        a = analytics.audience(c, "ryj-media")
        self.assertEqual(r["audience"], {"age_gender": 3, "country": 2, "device": 2, "subscribed": 2})
        self.assertEqual(a["age"], [{"label": "18-24", "pct": 40.0}, {"label": "25-34", "pct": 60.0}])
        self.assertEqual(a["gender"][0], {"label": "male", "pct": 75.0})
        self.assertEqual((a["device"][0]["label"], a["device"][0]["share_pct"], a["device"][0]["watch_hours"]), ("MOBILE", 90.0, 20.0))
        self.assertEqual(a["subscribed"][1]["avg_view_s"], 300)
        self.assertEqual([(e["kind"], e["x"]) for e in d["retention_events"]], [("replay", 0.5)])
        vl = {v["asset_id"]: v for v in api.video_list(c, "ryj-media")}
        self.assertEqual(vl["vLong"]["rewatch_peak"], 1.2)

    def test_short_loops_and_no_data(self):
        self.assertEqual(analytics.rewatch_summary([], 117.5, "short_heuristic")["loops_pct"], 17.5)
        c, _ = fresh()
        self.assertFalse(analytics.monetization(c, "ryj-media")["available"])


class TestGrowthEngine(unittest.TestCase):
    def test_review_ranks_caps_and_workflow(self):
        c, _ = fresh()
        seed.seed_demo(c)
        # Regression (2026-10-15 07:00 run): a video with no CTR among peers that have one
        # produced percentile=None and crashed the daily review.
        vid = c.execute("SELECT asset_id FROM assets WHERE tenant_id='demo-synthetic' LIMIT 1").fetchone()[0]
        c.execute("DELETE FROM metrics WHERE tenant_id='demo-synthetic' AND asset_id=? AND metric_name LIKE 'videoThumbnail%'", (vid,))
        r = analytics.growth_review(c, "demo-synthetic")
        self.assertGreater(r["candidates"], 0)
        self.assertLessEqual(r["new"], analytics.DAILY_NEW_LIMIT)
        again = analytics.growth_review(c, "demo-synthetic")
        self.assertEqual(again["new"], 0)  # fingerprints: no duplicates on rerun
        items = api.recommendations(c, "demo-synthetic")["items"]
        rec = next(i for i in items if i["steps"])
        self.assertTrue(rec["evidence"] and rec["hypotheses"] and rec["test_plan"]["metric"])
        self.assertIn(rec["diagnosis"], ("content", "packaging", "distribution", "opportunity"))
        for to in ("awaiting_approval", "approved", "executed"):
            analytics.move_rec(c, "demo-synthetic", rec["id"], to)
        row = c.execute("SELECT * FROM recommendations WHERE id=?", (rec["id"],)).fetchone()
        self.assertEqual((row["workflow"], row["status"]), ("executed", "done"))
        self.assertIn("views_per_day", json.loads(row["baseline_json"]))
        b = json.loads(row["baseline_json"])
        b["at"] = (date.today() - timedelta(days=10)).isoformat()
        c.execute("UPDATE recommendations SET evaluate_after='2000-01-01', baseline_json=? WHERE id=?", (json.dumps(b), rec["id"]))
        self.assertEqual(analytics.evaluate_executed(c, "demo-synthetic"), 0)  # day 10: only the 7-day checkpoint
        row = c.execute("SELECT * FROM recommendations WHERE id=?", (rec["id"],)).fetchone()
        self.assertEqual(list(json.loads(row["result_json"])["checkpoints"]), ["7"])
        b["at"] = (date.today() - timedelta(days=30)).isoformat()
        c.execute("UPDATE recommendations SET evaluate_after='2000-01-01', baseline_json=? WHERE id=?", (json.dumps(b), rec["id"]))
        self.assertEqual(analytics.evaluate_executed(c, "demo-synthetic"), 1)
        row = c.execute("SELECT * FROM recommendations WHERE id=?", (rec["id"],)).fetchone()
        self.assertEqual(sorted(json.loads(row["result_json"])["checkpoints"]), ["14", "28", "7"])
        led = [l["to_state"] for l in api.recommendations(c, "demo-synthetic")["items"] if False] or \
            [r[0] for r in c.execute("SELECT to_state FROM action_ledger WHERE rec_id=? ORDER BY id", (rec["id"],))]
        self.assertEqual(led, ["awaiting_approval", "approved", "executed", "evaluated"])
        with self.assertRaises(ValueError):
            analytics.move_rec(c, "demo-synthetic", rec["id"], "published")
        with self.assertRaises(LookupError):
            analytics.move_rec(c, "ryj-media", rec["id"], "approved")  # other tenant can't touch it

    def test_retention_events_skip_intro_and_outro(self):
        curve = [{"x": 0.0, "v": 1.0}, {"x": 0.02, "v": 0.6}, {"x": 0.3, "v": 0.55}, {"x": 0.31, "v": 0.4},
                 {"x": 0.5, "v": 0.5}, {"x": 0.97, "v": 0.45}, {"x": 1.0, "v": 0.1}]
        ev = analytics.retention_events(curve, None, 1000, 5000)
        kinds = [(e["kind"], e["x"]) for e in ev]
        self.assertIn(("drop", 0.31), kinds)
        self.assertIn(("replay", 0.5), kinds)
        self.assertNotIn(("drop", 1.0), kinds)
        self.assertNotIn(("drop", 0.02), kinds)
        self.assertTrue(all(e["confidence"] == "high" for e in ev))


class TestThumbnailStrategy(unittest.TestCase):
    def _video(self, c):
        c.execute("INSERT INTO assets VALUES ('ryj-media','youtube','UCx','vT','When Should Kids Start Lifting? | Coach Ray',"
                  "'2026-09-01T00:00:00Z',3000,'long_form','',NULL,'2026-10-01')")
        from PIL import Image, ImageDraw
        d = db.DATA_DIR / "thumbs" / "ryj-media"
        d.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (1280, 720), (5, 5, 5))
        dr = ImageDraw.Draw(im)
        dr.rectangle([60, 250, 560, 450], fill=(255, 255, 255))  # old headline block on the black panel
        for x in range(700, 1280):
            for y in range(0, 720, 4):
                dr.line([(x, y), (x, y + 3)], fill=((x * 7) % 255, (y * 3) % 255, 120))  # "photo"
        im.save(d / "vT.jpg", quality=95)
        return d / "vT.jpg"

    def test_formats_and_headlines(self):
        self.assertEqual(thumbs.suggest_format("Is Maxx Crosby the BEST Pass Rusher in the NFL?")[0], "host_led")
        self.assertEqual(thumbs.suggest_format("Gymnastics Teaches Girls to Get Back Up | Ivanka Victory")[0], "guest")
        self.assertEqual(thumbs.suggest_format("Coach X vs Coach Y: Who's Right? | Coach X")[0], "host_guest")
        self.assertEqual(thumbs.parse_headline("Pay to play / is hurting / *U.S. soccer*"),
                         [[("PAY", False), ("TO", False), ("PLAY", False)], [("IS", False), ("HURTING", False)],
                          [("U.S.", True), ("SOCCER", True)]])
        self.assertTrue(all(g for _, g in thumbs.parse_headline("are athletes more than their medals?")[-1]))

    def test_render_keeps_the_photo_untouched_and_isolated(self):
        c, _ = fresh()
        src = self._video(c)
        from PIL import Image
        out = thumbs.previews(c, "ryj-media", "vT", ["When should kids *start lifting?*", "Too young / *to lift?*"])
        self.assertEqual(len(out["variants"]), 2)
        a = Image.open(db.DATA_DIR / "previews" / "ryj-media" / "vT" / out["variants"][0]["file"]).convert("RGB")
        self.assertEqual(a.size, (1280, 720))
        orig = Image.open(src).convert("RGB")
        # Far-right photo region is copied, not altered (JPEG tolerance only).
        diffs = [abs(p - q) for x in range(1100, 1270, 17) for y in range(20, 700, 37)
                 for p, q in zip(a.getpixel((x, y)), orig.getpixel((x, y)))]
        self.assertLess(max(diffs), 24)
        # No frames of the hosts from THIS episode → host layouts fall back to the guest, never faked/borrowed.
        self.assertEqual(thumbs.previews(c, "ryj-media", "vT", ["X"], fmt="host_led")["variants"][0]["format"], "guest")
        self.assertEqual(thumbs.fit_format("trio", {"guest": 1, "jamar": 1}), "host_guest")
        self.assertEqual(thumbs.fit_format("trio", {"guest": 1, "jamar": 1, "enrique": 1}), "trio")
        self.assertEqual(thumbs.fit_format("host_led", {}), "guest")
        cast_dir = db.DATA_DIR / "castimgs"
        cast_dir.mkdir(exist_ok=True)
        cast = {}
        for role, col in (("jamar", (200, 0, 0)), ("guest", (0, 200, 0)), ("enrique", (0, 0, 200))):
            Image.new("RGB", (300, 400), col).save(cast_dir / f"{role}.jpg")
            cast[role] = (cast_dir / f"{role}.jpg", 0.5)
        trio = thumbs.render(src, "Who is *best*?", fmt="trio", cast=cast).convert("RGB")
        r, g, b = trio.getpixel((700, 360)), trio.getpixel((960, 360)), trio.getpixel((1200, 360))
        self.assertTrue(r[0] > 150 and g[1] > 150 and b[2] > 150)  # Jamar | guest | Enrique, left to right
        with self.assertRaises(LookupError):
            thumbs.set_tag(c, "demo-synthetic", "vT", "guest")
        thumbs.set_tag(c, "ryj-media", "vT", "guest")
        self.assertEqual(thumbs.tags(c, "ryj-media"), {"vT": "guest"})
        e = thumbs.save_experiment(c, "ryj-media", {"asset_id": "vT", "method": "sequential", "winner": "A",
                                                     "variants": [{"label": "A"}, {"label": "B"}]})
        ex = thumbs.experiments(c, "ryj-media")
        self.assertEqual((ex[0]["id"], ex[0]["result"]["winner"]), (e["id"], "A"))
        self.assertIn("confounded", ex[0]["result"]["caveat"])
        st = api.thumb_studio(c, "ryj-media", "vT")
        self.assertEqual((st["recommended"], st["current_format"]), ("guest", "guest"))
        self.assertGreaterEqual(len(st["previews"]), 1)  # two renders in the same second share a stamp


class TestReports(unittest.TestCase):
    def test_reuse_and_csv(self):
        c, _ = fresh()
        seed.seed_demo(c)
        a = reports.generate(c, "demo-synthetic", "weekly")
        b = reports.generate(c, "demo-synthetic", "weekly")
        self.assertTrue(b["reused"])
        self.assertEqual(a["report_id"], b["report_id"])
        with open(a["path"]) as f:
            html = f.read()
        self.assertIn("Synthetic demo data", html)
        self.assertIn("<svg", html)
        self.assertIn("data:image/jpeg;base64", html)
        self.assertTrue(reports.csv_export(c, "demo-synthetic", "videos").startswith("asset_id,title"))
        s, e = reports.period_for("weekly", date(2026, 10, 14))
        self.assertEqual((s.isoformat(), e.isoformat()), ("2026-10-05", "2026-10-11"))


if __name__ == "__main__":
    unittest.main()


class TestSpecV5(unittest.TestCase):
    D = "demo-synthetic"

    def setUp(self):  # never call a real model from tests
        p = mock.patch.object(ai, "status", return_value={"enabled": True, "cli_found": False, "daily_cap": 9,
                                                          "used_today": 0, "reason": "no CLI in tests"})
        p.start()
        self.addCleanup(p.stop)

    def _rec(self, c):
        seed.seed_demo(c)
        analytics.growth_review(c, self.D)
        return c.execute("SELECT * FROM recommendations WHERE tenant_id=? AND asset_id IS NOT NULL AND diagnosis!='' "
                         "ORDER BY kind IN ('double_down','funnel') LIMIT 1",
                         (self.D,)).fetchone()

    def test_prepare_pack_and_states(self):
        from growth_os import prep
        c, _ = fresh()
        rec = self._rec(c)
        self.assertLessEqual(c.execute("SELECT COUNT(*) FROM recommendations WHERE tenant_id=? AND diagnosis!=''",
                                       (self.D,)).fetchone()[0], 3)
        pack = prep.prepare_rec(c, self.D, rec["id"])  # no CLI here: rule-based titles
        self.assertEqual([t["strategy"] for t in pack["titles"]], ["search_driven", "curiosity", "hybrid"])
        self.assertTrue(all(len(t["title"]) <= 70 for t in pack["titles"]))
        self.assertIn("first_lines", pack["seo"])
        item = next(i for i in api.recommendations(c, self.D)["items"] if i["id"] == rec["id"])
        self.assertEqual((item["workflow"], item["state_label"]), ("prepared", "PREVIEW_READY"))
        self.assertEqual(item["prepared"]["keyword"], pack["keyword"])
        fake = lambda prompt, model: {"result": json.dumps({"titles": [{"strategy": s, "title": f"T {s}", "why": "w"}
                                                                     for s in prep.PREP_STRATEGIES]})}
        with mock.patch.object(ai, "status", return_value={"enabled": True, "cli_found": True, "daily_cap": 9, "used_today": 0}):
            pack2 = prep.prepare_rec(c, self.D, rec["id"], runner=fake)
        self.assertTrue(pack2["titles"][0]["source"].startswith("AI draft"))

    def test_transcript_windows_and_chapters(self):
        from growth_os import prep
        srt = "1\n00:00:01,000 --> 00:00:04,000\nWelcome to the show\n\n2\n00:01:30,500 --> 00:01:33,000\n<i>Lifting at 12?</i>\n\n" \
              "3\n00:03:10,000 --> 00:03:14,000\nHere's what the research says\n"
        segs = prep.parse_captions(srt)
        self.assertEqual(len(segs), 3)
        self.assertEqual(segs[1]["text"], "Lifting at 12?")
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nWelcome to the show\n"
        self.assertEqual(prep.parse_captions(vtt)[0]["start"], 1.0)
        w = prep.window(segs, 100)
        self.assertIn("Lifting", w["text"])
        self.assertNotIn("research", w["text"])
        self.assertEqual(prep.chapters(segs, 240, n=2)[1]["t"], 190)
        self.assertEqual(prep.chapters(segs, 50), [])

    def test_cohorts_points(self):
        from growth_os import prep
        c, _ = fresh()
        pub = date.today() - timedelta(days=40)
        c.execute("INSERT INTO assets VALUES ('ryj-media','youtube','UCx','vC','Cohort test',?,600,'long_form','',NULL,?)",
                  (pub.isoformat() + "T00:00:00Z", utcnow()))
        for i in range(29):
            c.execute("""INSERT INTO metrics (tenant_id, platform, platform_account_id, asset_id, metric_name, value, unit, grain,
                         period_start, source, fetched_at, data_quality) VALUES ('ryj-media','youtube','UCx','vC','views',10,'',
                         'video_day',?,'t',?, 'verified')""", ((pub + timedelta(days=i)).isoformat(), utcnow()))
        it = prep.cohorts(c, "ryj-media")["items"][0]
        self.assertEqual({k: v["views"] for k, v in it["points"].items()}, {"1": 10, "3": 30, "7": 70, "28": 280})

    def test_discovery_distribution_samples_plan(self):
        from growth_os import discovery
        c, _ = fresh()
        seed.seed_demo(c)

        def transport(method, url, headers, body):
            if "itunes" in url:
                return 200, json.dumps({"results": [{"collectionName": "Demo Studio Podcast (synthetic)",
                                                     "feedUrl": "https://feeds.example/x.xml", "trackCount": 3}]}).encode()
            return 200, (b"<rss><channel><title>Demo</title><description>d</description><item><pubDate>Mon, 12 Oct 2026"
                         b"</pubDate></item></channel></rss>")
        st = {d["platform"]: d["status"] for d in discovery.check_distribution(c, self.D, transport=transport)}
        self.assertEqual(st["youtube"], "Connected analytics")
        self.assertEqual(st["apple_podcasts"], "Verified listing only")
        self.assertEqual(st["rss"], "Verified listing only")
        self.assertEqual(st["instagram"], "Needs authorization")
        self.assertTrue(set(st.values()) <= set(discovery.STATUSES))
        down = discovery.check_distribution(c, self.D, transport=lambda *a: (503, b"x"))
        self.assertEqual({d["platform"]: d["status"] for d in down}["apple_podcasts"], "Unavailable")
        discovery.add_ai_sample(c, self.D, {"query": "q1", "engine": "Claude.ai (free)", "mentioned": True})
        discovery.add_ai_sample(c, self.D, {"query": "q1", "engine": "ChatGPT", "mentioned": False})
        self.assertEqual(discovery.ai_samples(c, self.D)["summary"], [{"query": "q1", "samples": 2, "mentioned": 1}])
        with self.assertRaises(ValueError):
            discovery.add_ai_sample(c, self.D, {"query": "", "engine": "x"})
        p = discovery.plan_episode(c, self.D, "When should young athletes start lifting?")
        self.assertIn("_unavailable", p["plan"])  # no CLI: honest, no invented plan
        self.assertEqual(len(discovery.page(c, self.D)["plans"]), 1)
        self.assertIn("search_terms", discovery.keywords(c, self.D))

    def test_operator_dry_run_refuses_and_blocks(self):
        from growth_os import discovery
        c, _ = fresh()
        rec = self._rec(c)
        self.assertEqual(discovery.operator_dry_run(c, self.D, rec["id"], "UC_SYNTHETIC_DEMO_CHANNEL")["result"], "REFUSED")
        analytics.move_rec(c, self.D, rec["id"], "approved")
        self.assertEqual(discovery.operator_dry_run(c, self.D, rec["id"], "UC_SOMEONE_ELSE")["result"], "REFUSED")
        r = discovery.operator_dry_run(c, self.D, rec["id"], "UC_SYNTHETIC_DEMO_CHANNEL")
        self.assertEqual(r["result"], "BLOCKED")
        self.assertIn("awaiting authorization", r["reason"])
        row = c.execute("SELECT workflow FROM recommendations WHERE id=?", (rec["id"],)).fetchone()
        self.assertEqual(row[0], "blocked")
        data = reports.build_data(c, self.D, date.today() - timedelta(days=7), date.today())
        self.assertIn("BLOCKED", [a["state"] for a in data["actions"]])


class TestGrowthBrief(unittest.TestCase):
    D = "demo-synthetic"

    def test_rule_brief_then_ai_brief(self):
        from growth_os import brief
        c, _ = fresh()
        seed.seed_demo(c)
        off = {"enabled": True, "cli_found": False, "daily_cap": 9, "used_today": 0, "reason": "no CLI in tests"}
        with mock.patch.object(ai, "status", return_value=off):
            d = brief.generate(c, self.D)
        self.assertTrue(d["brief"]["_rule_based"])
        self.assertTrue(d["source"].startswith("Rule-based"))
        f = d["facts"]
        self.assertTrue(f["kpis"] and f["top"] and f["formats"])
        self.assertTrue(d["brief"]["whats_happening"] and d["brief"]["next_episode"]["opening"])
        for rows in f["title_words"].values():  # only over-represented words, with real counts
            self.assertTrue(all(r["in_top"] >= 2 and r["lift"] >= 1.5 for r in rows))
        out = {"headline": "h", "whats_happening": ["a"], "whats_working": [], "where_viewers_leave": [],
               "next_episode": {"title_words": ["coach"]}, "this_week": ["x", "y", "z"], "watch_next": "w"}
        on = dict(off, cli_found=True)
        with mock.patch.object(ai, "status", return_value=on):
            d2 = brief.generate(c, self.D, runner=lambda p, m: {"result": json.dumps(out)})
        self.assertEqual(d2["brief"]["headline"], "h")
        self.assertIn("AI synthesis", d2["source"])
        self.assertEqual(len(d2["history"]), 2)
        self.assertIsNone(brief.latest(c, "ryj-media")["brief"])  # tenant isolation

    def test_title_words_lift(self):
        from growth_os import brief
        mk = lambda i, t, vpd: {"asset_id": str(i), "title": t, "format": "long_form", "views_per_day": vpd, "age_days": 30,
                                "metrics": {}}
        vids = [mk(i, "Coach Secrets Revealed", 100 + i) for i in range(3)] + [mk(10 + i, "Weekly Update Show", 5) for i in range(9)]
        words = {r["word"] for r in brief.title_words(vids)["long_form"]}
        self.assertIn("coach", words)
        self.assertNotIn("weekly", words)


class WriteGoogle(FakeGoogle):
    """Token grants write scope; /videos snippet is stateful so writes and read-back can be checked."""

    def __init__(self, channel=RYJ_CH):
        super().__init__([(RYJ_CH, "Respect Your Journey")])
        self.owner_channel = channel
        self.snip = {"title": "Old Title", "description": "Original description with links", "tags": ["old"],
                     "categoryId": "17", "channelId": channel, "publishedAt": "2026-09-01T00:00:00Z",
                     "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/vW/hqdefault.jpg"}}}
        self.puts, self.thumb_posts = [], 0

    def __call__(self, method, url, headers, body):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if url.startswith(youtube.TOKEN_URL):
            return 200, json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                                    "scope": youtube.READ_SCOPES + " " + youtube.WRITE_SCOPE,
                                    "id_token": id_token("owner@ryj.example")}).encode()
        if "/videos" in url and q.get("part") == "snippet":
            if method == "PUT":
                self.puts.append(json.loads(body))
                self.snip.update(json.loads(body)["snippet"])
                return 200, body
            return 200, json.dumps({"items": [{"id": "vW", "snippet": self.snip}]}).encode()
        if "thumbnails/set" in url:
            self.thumb_posts += 1
            return 200, b"{}"
        if "ytimg.com" in url:
            return 200, b"\xff\xd8jpeg"
        return super().__call__(method, url, headers, body)


class TestAutopilot(unittest.TestCase):
    T = "ryj-media"

    def _setup(self, g):
        from growth_os import autopilot
        c, _ = fresh()
        url = youtube.begin_auth(c, self.T, "http://127.0.0.1/cb", CLIENT, write=True)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertIn(youtube.WRITE_SCOPE, q["scope"])
        [row] = youtube.finish_auth(c, state=q["state"], code="x", client=CLIENT, transport=g)[1]
        brands.verify_identity(c, self.T, row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        brands.assign(c, self.T, row, owner="owner")
        c.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (self.T, "youtube", RYJ_CH, "vW", "Old Title | Coach Ray", "2026-09-01T00:00:00Z", 3000, "long_form", "", None, "2026-10-01"))
        youtube_sync.record_history(c, self.T, "youtube", "vW", "description", "", "test")
        youtube_sync.record_history(c, self.T, "youtube", "vW", "tags", "[]", "test")
        p = mock.patch.object(autopilot.vault, "load_client", return_value=CLIENT)
        p.start()
        self.addCleanup(p.stop)
        off = mock.patch.object(ai, "status", return_value={"enabled": True, "cli_found": False, "daily_cap": 9,
                                                             "used_today": 0, "reason": "no CLI in tests"})
        off.start()
        self.addCleanup(off.stop)
        return c, autopilot

    def test_draft_approve_apply_verify_undo(self):
        g = WriteGoogle()
        c, ap = self._setup(g)
        self.assertTrue(ap.write_status(c, self.T)["has_write"])
        r = ap.daily_run(c, self.T, transport=g)
        self.assertEqual((r["proposed"], r["auto_applied"]), (1, 0))  # approve mode: nothing written
        self.assertEqual(g.puts, [])
        [chg] = ap.page(c, self.T)["pending"]
        self.assertEqual(chg["reason"], "missing")
        self.assertIsNone(chg["chosen"]["title"])  # missing-info packages keep the title
        ap.decide(c, self.T, chg["id"], "approve")
        out = ap.apply(c, self.T, chg["id"], transport=g)
        self.assertEqual(out["status"], "verified")
        sent = g.puts[-1]["snippet"]
        self.assertEqual(sent["title"], "Old Title")
        self.assertEqual(sent["categoryId"], "17")  # untouched fields preserved
        self.assertTrue(sent["description"].endswith("Original description with links"))
        self.assertIn("old", sent["tags"])
        self.assertNotIn("channelId", sent)  # read-only fields never sent
        ap.rollback(c, self.T, chg["id"], transport=g)
        self.assertEqual(g.snip["description"], "Original description with links")
        self.assertEqual(g.snip["tags"], ["old"])
        self.assertEqual(ap.daily_run(c, self.T, transport=g)["proposed"], 0)  # cooldown

    def test_auto_missing_mode_and_refusals(self):
        g = WriteGoogle(channel="UC_SOMEONE_ELSE")
        c, ap = self._setup(g)
        ap.set_mode(c, self.T, "auto_missing")
        r = ap.daily_run(c, self.T, transport=g)
        self.assertEqual(r["auto_applied"], 0)
        self.assertIn("different channel", r["errors"][0])  # video must belong to the bound channel
        self.assertEqual(g.puts, [])
        c.execute("UPDATE platform_accounts SET access_level='READ_ANALYTICS' WHERE tenant_id=?", (self.T,))
        self.assertFalse(ap.write_status(c, self.T)["has_write"])
        cid = c.execute("SELECT id FROM channel_changes WHERE tenant_id=?", (self.T,)).fetchone()[0]
        c.execute("UPDATE channel_changes SET status='approved' WHERE id=?", (cid,))
        with self.assertRaises(brands.BrandError):  # preflight: read-only scope can't write
            ap.apply(c, self.T, cid, transport=g)
        seed.seed_demo(c)
        self.assertIn("skipped", ap.daily_run(c, "demo-synthetic"))


class CompGoogle(WriteGoogle):
    def __call__(self, method, url, headers, body):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if "/search" in url:
            return 200, json.dumps({"items": [{"snippet": {"channelId": c}} for c in ("UC_COMP1", "UC_TINY", RYJ_CH)]}).encode()
        if "/channels" in url and "statistics" in q.get("part", "") and "id" in q:
            subs = {"UC_COMP1": "50000", "UC_TINY": "40"}
            return 200, json.dumps({"items": [{"id": c, "snippet": {"title": c}, "statistics": {"subscriberCount": subs.get(c, "0"), "videoCount": "100"},
                                               "contentDetails": {"relatedPlaylists": {"uploads": "UU" + c}}} for c in q["id"].split(",") if c in subs]}).encode()
        if "/playlistItems" in url and q.get("playlistId", "").startswith("UUUC_"):
            return 200, json.dumps({"items": [{"contentDetails": {"videoId": "cv1"}}]}).encode()
        if "/videos" in url and q.get("id") == "cv1":
            return 200, json.dumps({"items": [{"id": "cv1", "snippet": {"title": "Why Kids Quit Sports", "publishedAt": "2026-10-01T00:00:00Z"},
                                               "statistics": {"viewCount": "27000"}, "contentDetails": {"duration": "PT41M"}}]}).encode()
        return super().__call__(method, url, headers, body)


class TestDeepDiveAndTitles(TestAutopilot):
    def test_competition_research_and_brief_sections(self):
        from growth_os import brief, discovery
        g = CompGoogle()
        c, ap = self._setup(g)
        with mock.patch("growth_os.vault.load_client", return_value=CLIENT):
            r = discovery.research_competitors(c, self.T, transport=g, queries=["youth sports podcast"])
        self.assertEqual(r["channels"], ["UC_COMP1"])  # own channel and tiny channels excluded
        comp = discovery.competition_facts(c, self.T)
        self.assertEqual(comp["top_videos"][0]["title"], "Why Kids Quit Sports")
        f = brief.facts(c, self.T)
        self.assertEqual(f["seo_audit"]["missing_description"], 1)
        self.assertIn("long_form", f["title_audit"])
        rb = brief.rule_brief(f)
        self.assertTrue(rb["competition"] and rb["seo"] and rb["title_rules"])

    def test_long_title_gets_short_title_and_thumbnail_request(self):
        g = WriteGoogle()
        c, ap = self._setup(g)
        long_t = "This Is A Very Long Episode Title About Youth Sports Development And Parents | Coach Ray"
        c.execute("UPDATE assets SET title=? WHERE asset_id='vW'", (long_t,))
        youtube_sync.record_history(c, self.T, "youtube", "vW", "description", "A real description that is long enough to count here.", "t")
        youtube_sync.record_history(c, self.T, "youtube", "vW", "tags", '["x"]', "t2")
        [cand] = ap.candidates(c, self.T)
        self.assertEqual(cand["reason"], "long_title")
        on = {"enabled": True, "cli_found": True, "daily_cap": 9, "used_today": 0}
        titles = [{"strategy": s, "title": t, "why": "w"} for s, t in
                  (("search_driven", "Youth Sports Development: What Parents Get Wrong About It All Day Long"),
                   ("curiosity", "What Parents Get Wrong in Youth Sports"), ("hybrid", "Youth Sports: Parents' Biggest Mistake"))]
        with mock.patch.object(ai, "status", return_value=on):
            prop, chosen = ap._proposal(c, self.T, cand, runner=lambda p, m: {"result": json.dumps({"titles": titles})})
        self.assertEqual(chosen["title"], "Youth Sports: Parents' Biggest Mistake")  # hook-style option first, under 60 chars
        self.assertTrue(all(len(x) <= 60 for x in [chosen["title"]]))
        ap.set_cap(c, self.T, 5)
        self.assertEqual(ap.cap(c, self.T), 5)
        with self.assertRaises(ValueError):
            ap.set_cap(c, self.T, 50)


class TestViralThumbnail(unittest.TestCase):
    def test_layout_sharp_faces_only_and_inside_frame(self):
        from PIL import Image, ImageDraw
        from growth_os import viral
        d = db.DATA_DIR / "viraltest"
        d.mkdir(exist_ok=True)
        src = d / "orig.jpg"
        Image.new("RGB", (1280, 720), (30, 30, 30)).save(src)
        cuts = {}
        for role, col, face in (("jamar", (220, 0, 0), 150), ("guest", (0, 220, 0), 260), ("enrique", (0, 0, 220), 80)):
            im = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse([60, 40, 340, 500], fill=col + (255,))
            im.save(d / f"{role}.png")
            cuts[role] = (d / f"{role}.png", {"face_px": face})
        out = viral.render(src, "IS HE THE *BEST?*", cuts)
        px = [out.getpixel((x, y)) for x in range(520, 1280, 8) for y in range(200, 720, 8)]
        self.assertTrue(any(p[1] > 180 and p[0] < 80 for p in px))       # guest (green) is in
        self.assertTrue(any(p[0] > 180 and p[1] < 80 for p in px))       # sharp host (red) is in
        self.assertFalse(any(p[2] > 180 and p[0] < 80 and p[1] < 80 for p in px))  # blurry wide-shot host left out
        self.assertEqual(out.size, (1280, 720))


class TestThumbnailsFrozen(TestAutopilot):
    def test_autopilot_never_touches_thumbnails(self):
        g = WriteGoogle()
        c, ap = self._setup(g)
        c.execute("UPDATE assets SET title=? WHERE asset_id='vW'", ("A Very Long Episode Title About Youth Sports Development And Parents | Coach Ray",))
        [cand] = [x for x in ap.candidates(c, self.T)]
        prop, chosen = ap._proposal(c, self.T, cand)
        self.assertIsNone(prop["thumbnail"])
        self.assertIsNone(chosen["thumbnail"])
        # even an older draft that still carries a thumbnail can't change it
        cid = "chg_" + "a" * 16
        prop["thumbnail"] = {"file": "x.jpg"}
        c.execute("INSERT INTO channel_changes (id, tenant_id, asset_id, reason, proposal_json, chosen_json, status, decided_at, created_at) "
                  "VALUES (?,?,?,?,?,?,'approved',?,?)", (cid, self.T, "vW", "low_ctr", json.dumps(prop),
                                                        json.dumps(dict(chosen, thumbnail="x.jpg", description=True)), utcnow(), utcnow()))
        ap.apply(c, self.T, cid, transport=g)
        self.assertEqual(g.thumb_posts, 0)


class TestTitleMatchesThumbnail(TestAutopilot):
    def test_thumbnail_text_reaches_title_draft_and_swap_triggers_recheck(self):
        from growth_os import thumbtext
        g = WriteGoogle()
        c, ap = self._setup(g)
        seen = {}

        def runner(prompt, model):
            seen.setdefault("prompts", []).append(prompt)
            return {"result": json.dumps({"titles": [{"strategy": "curiosity", "title": "Why Coach Ray Says Kids Quit", "why": "w"}]})}
        on = {"enabled": True, "cli_found": True, "daily_cap": 99, "used_today": 0}
        c.execute("UPDATE assets SET title=? WHERE asset_id='vW'", ("A Very Long Episode Title About Youth Sports Development And Parents | Coach Ray",))
        with mock.patch.object(thumbtext, "read", return_value="stop calling kidssoft"), \
                mock.patch.object(ai, "status", return_value=on):
            [cand] = ap.candidates(c, self.T)
            prop, chosen = ap._proposal(c, self.T, cand, runner=runner)
        self.assertEqual(prop["thumbnail_text"], "stop calling kidssoft")
        self.assertTrue(any('"thumbnail_text":"stop calling kidssoft"' in p for p in seen["prompts"]))
        # our title went live, then the other agent swapped the thumbnail → re-check queued despite cooldown
        cid = "chg_" + "b" * 16
        c.execute("INSERT INTO channel_changes (id, tenant_id, asset_id, reason, proposal_json, chosen_json, status, applied_at, created_at) "
                  "VALUES (?,?,?,?,?,?,'verified','2026-10-01T00:00:00+00:00',?)", (cid, self.T, "vW", "long_title", json.dumps(prop),
                                                                                   json.dumps({"title": "Why Coach Ray Says Kids Quit"}), utcnow()))
        youtube_sync.record_history(c, self.T, "youtube", "vW", "thumbnail", "newhash", "thumbnail bytes")
        reasons = [x["reason"] for x in ap.candidates(c, self.T)]
        self.assertEqual(reasons, ["thumb_changed"])
