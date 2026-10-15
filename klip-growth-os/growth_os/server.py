"""Klip Growth OS owner app server (stdlib only).

* Binds to 127.0.0.1 only; Host header must be local (blocks DNS rebinding).
* POSTs need the per-process CSRF token embedded in the page.
* Every /api/t/<tenant>/... route is tenant-scoped; ids from another tenant
  are simply not found.
* The background scheduler runs in the same process (see scheduler.py).
"""

import json
import re
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from growth_os import ai, analytics, api, brands, db, reports, scheduler, vault
from growth_os.connectors import podcast, youtube
from growth_os.db import DATA_DIR, new_id, set_setting, utcnow
from growth_os.http import BudgetExceeded, HttpError
from growth_os.jobs import REGISTRY

WEB = Path(__file__).parent / "web"
CSRF = secrets.token_urlsafe(24)
OWNER = "owner"
STATIC = {"app.js": "text/javascript", "charts.js": "text/javascript", "app.css": "text/css",
          "manifest.webmanifest": "application/manifest+json", "sw.js": "text/javascript",
          "icon-192.png": "image/png", "icon-512.png": "image/png", "icon.svg": "image/svg+xml",
          "favicon.ico": "image/x-icon"}
TENANT = r"([a-z0-9-]{1,40})"


class Handler(BaseHTTPRequestHandler):
    server_version = "KlipGrowthOS"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # quiet; OAuth codes must never reach a log

    def _send(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        raw = body if isinstance(body, bytes) else str(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store" if ctype == "application/json" else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _local(self):
        return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

    def _redirect(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle(self, method):
        if not self._local():
            return self._send(403, {"error": "local access only"})
        if method == "POST" and self.headers.get("X-CSRF") != CSRF:
            return self._send(403, {"error": "forbidden"})
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        conn = db.connect(self.server.db_path)
        try:
            return self.route(conn, method, u.path, q, body)
        except brands.BrandError as e:
            return self._send(404 if e.code in ("not_found", "no_brand") else 400, {"error": e.code, "message": str(e)})
        except youtube.ConnectorError as e:
            return self._send(409, {"error": e.code, "message": str(e)})
        except ai.AIUnavailable as e:
            return self._send(503, {"error": "ai_unavailable", "message": str(e)})
        except (BudgetExceeded, HttpError) as e:
            return self._send(502, {"error": type(e).__name__, "message": str(e)[:300]})
        except (KeyError, ValueError) as e:
            return self._send(400, {"error": "bad_request", "message": str(e)[:200]})
        except Exception as e:  # never drop the connection; show the reason in the UI
            import traceback
            traceback.print_exc()
            return self._send(500, {"error": "server_error", "message": f"{type(e).__name__}: {e}"[:300]})
        finally:
            conn.close()

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    # ── routing ──
    def route(self, c, method, path, q, body):
        if method == "GET":
            if path in ("/", "/index.html"):
                html = (WEB / "index.html").read_text(encoding="utf-8").replace("__CSRF__", CSRF)
                return self._send(200, html, "text/html")
            name = path.lstrip("/")
            if name in STATIC:
                f = WEB / name
                if f.exists():
                    return self._send(200, f.read_bytes(), STATIC[name],
                                      {"Service-Worker-Allowed": "/"} if name == "sw.js" else None)
                return self._send(404, {"error": "not found"})
            if path == "/oauth/callback":
                return self._oauth_callback(c, q)
            m = re.fullmatch(rf"/thumb/{TENANT}/([A-Za-z0-9_-]{{1,64}})\.jpg", path)
            if m:
                brands.get_brand(c, m.group(1))
                f = DATA_DIR / "thumbs" / m.group(1) / f"{m.group(2)}.jpg"
                if not f.exists():
                    return self._send(404, {"error": "no thumbnail cached"})
                return self._send(200, f.read_bytes(), "image/jpeg")
            if path == "/api/app":
                return self._send(200, api.app_info(c))
            if path == "/api/jobs":
                return self._send(200, api.jobs(c))
            m = re.fullmatch(rf"/api/t/{TENANT}/(.+)", path)
            if m:
                t, rest = m.groups()
                brands.get_brand(c, t)
                return self.tenant_get(c, t, rest, q)
            return self._send(404, {"error": "not found"})

        # POST
        if path == "/api/brands":
            name = (body.get("display_name") or "").strip()
            if not name:
                raise ValueError("display_name required")
            return self._send(200, {"tenant_id": brands.create_brand(c, name, OWNER)})
        m = re.fullmatch(r"/api/jobs/([a-z_]+)/run", path)
        if m:
            kind = m.group(1)
            if kind not in REGISTRY:
                raise ValueError("unknown job")
            t = body.get("tenant_id")
            if t:
                brands.get_brand(c, t)
            run_id, created = scheduler.enqueue(c, kind, tenant_id=t, trigger="manual")
            return self._send(200, {"run_id": run_id, "queued": created})
        m = re.fullmatch(r"/api/schedules/([a-z_]+)", path)
        if m:
            s = c.execute("SELECT * FROM schedules WHERE name=?", (m.group(1),)).fetchone()
            if not s:
                raise brands.BrandError("not_found", "no such schedule")
            spec = body.get("spec") or json.loads(s["spec_json"])
            scheduler.next_slot(spec, scheduler.local_now())  # validates
            c.execute("UPDATE schedules SET enabled=?, spec_json=?, next_run_at=? WHERE name=?",
                      (int(body.get("enabled", s["enabled"])), json.dumps(spec),
                       scheduler.next_slot(spec, scheduler.local_now()).isoformat(), s["name"]))
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"/api/alerts/(\d+)/ack", path)
        if m:
            c.execute("UPDATE alerts SET acked_at=? WHERE id=?", (utcnow(), int(m.group(1))))
            return self._send(200, {"ok": True})
        if path == "/api/settings":
            if "ai_enabled" in body:
                set_setting(c, "ai.enabled", bool(body["ai_enabled"]))
            if "ai_daily_calls" in body:
                set_setting(c, "ai.daily_calls", max(0, min(500, int(body["ai_daily_calls"]))))
            return self._send(200, {"ok": True})
        m = re.fullmatch(rf"/api/t/{TENANT}/(.+)", path)
        if m:
            t, rest = m.groups()
            brands.get_brand(c, t)
            return self.tenant_post(c, t, rest, body)
        return self._send(404, {"error": "not found"})

    def tenant_get(self, c, t, rest, q):
        simple = {
            "home": lambda: api.home(c, t),
            "videos": lambda: api.video_list(c, t),
            "thumbnails": lambda: api.thumbnails(c, t),
            "titles": lambda: api.titles(c, t),
            "seo": lambda: api.seo(c, t),
            "recommendations": lambda: api.recommendations(c, t),
            "podcasts": lambda: api.podcasts(c, t),
            "monetization": lambda: analytics.monetization(c, t),
            "settings": lambda: api.settings(c, t),
            "tiles": lambda: tiles(c, t),
            "accounts": lambda: api.accounts_summary(c, t),
            "audit": lambda: [dict(r) for r in c.execute(
                "SELECT actor, event, detail_json, at FROM audit_log WHERE tenant_id=? ORDER BY id DESC LIMIT 60", (t,))],
            "reports": lambda: [dict(r) for r in c.execute(
                "SELECT id, kind, title, period_start, period_end, created_at FROM reports WHERE tenant_id=? ORDER BY created_at DESC", (t,))],
        }
        if rest in simple:
            return self._send(200, simple[rest]())
        if rest == "overview":
            return self._send(200, api.overview(c, t, int(q.get("days", 90))))
        if rest == "trends":
            return self._send(200, api.trend_page(c, t, q.get("status")))
        if rest == "calendar":
            return self._send(200, api.calendar(c, t, q.get("month") or date.today().isoformat()[:7]))
        m = re.fullmatch(r"video/([A-Za-z0-9_-]{1,64})", rest)
        if m:
            return self._send(200, api.video_detail(c, t, m.group(1)))
        m = re.fullmatch(r"reports/(rep_[a-f0-9]+)(\.pdf|\.html)?", rest)
        if m:
            r = c.execute("SELECT * FROM reports WHERE id=? AND tenant_id=?", (m.group(1), t)).fetchone()
            if not r:
                raise brands.BrandError("not_found", "report not found")
            if m.group(2) == ".pdf":
                pdf = reports.to_pdf(r["html_path"])
                return self._send(200, pdf.read_bytes(), "application/pdf",
                                  {"Content-Disposition": f'attachment; filename="{t}-{r["kind"]}-{r["period_end"]}.pdf"'})
            return self._send(200, Path(r["html_path"]).read_text(encoding="utf-8"), "text/html")
        m = re.fullmatch(r"export/(videos|daily|trends|recommendations)\.csv", rest)
        if m:
            return self._send(200, reports.csv_export(c, t, m.group(1)), "text/csv",
                              {"Content-Disposition": f'attachment; filename="{t}-{m.group(1)}-{date.today()}.csv"'})
        return self._send(404, {"error": "not found"})

    def tenant_post(self, c, t, rest, body):
        m = re.fullmatch(r"connect/(youtube|spotify|apple_podcasts|instagram)", rest)
        if m:
            p = m.group(1)
            if p == "youtube":
                client = vault.load_client("youtube")
                if not client:
                    return self._send(400, {"error": "no_client", "message":
                                            "YouTube isn't set up yet: save your Google OAuth desktop client as "
                                            f"{DATA_DIR / 'youtube_client.json'} (see README → Connect YouTube)."})
                redirect = f"http://127.0.0.1:{self.server.server_address[1]}/oauth/callback"
                return self._send(200, {"auth_url": youtube.begin_auth(c, t, redirect, client)})
            if p == "spotify":
                return self._send(200, {"row": podcast.discover_spotify(c, t, body.get("show", ""), name=body.get("name", ""))})
            if p == "apple_podcasts":
                return self._send(200, {"row": podcast.discover_apple(c, t, body.get("show", "").strip())})
            return self._send(400, {"error": "not_built", "message": api.PLATFORM_NOTES["instagram"]})
        m = re.fullmatch(r"accounts/(acct_[a-f0-9]+)/([a-z_]+)", rest)
        if m:
            row, action = m.groups()
            acct = brands.get_account(c, t, row)
            if action == "verify":
                brands.verify_identity(c, t, row, confirmed_platform_account_id=body.get("confirm_id", ""), owner=OWNER)
            elif action == "reject":
                brands.reject(c, t, row, owner=OWNER)
            elif action == "assign":
                brands.assign(c, t, row, owner=OWNER)
            elif action == "enable_import":
                podcast.enable_import(c, t, row, owner=OWNER)
            elif action == "disconnect":
                brands.disconnect(c, t, row, owner=OWNER)
            elif action == "revoke" and acct["platform"] == "youtube":
                youtube.revoke(c, t, row, owner=OWNER)
            elif action == "test" and acct["platform"] == "youtube":
                return self._send(200, youtube.sync_sample(c, t, row, client=vault.load_client("youtube")))
            elif action == "import" and acct["platform"] in ("spotify", "apple_podcasts"):
                tmp = DATA_DIR / "imports" / t
                tmp.mkdir(parents=True, exist_ok=True)
                name = re.sub(r"[^A-Za-z0-9._-]", "_", body.get("filename") or "import.csv")[:80]
                f = tmp / f"{new_id()}-{name}"
                f.write_text(body.get("csv") or "", encoding="utf-8")
                return self._send(200, podcast.import_csv(c, t, row, f, owner=OWNER))
            else:
                raise ValueError("bad action")
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"(trends|recommendations)/([a-z]{2,4}_[a-f0-9]+)/status", rest)
        if m:
            table, rid = m.groups()
            allowed = {"trends": ("new", "saved", "dismissed", "calendar"),
                       "recommendations": ("open", "accepted", "dismissed", "done")}[table]
            if body.get("status") not in allowed:
                raise ValueError("bad status")
            cur = c.execute(f"UPDATE {table} SET status=? WHERE id=? AND tenant_id=?", (body["status"], rid, t))
            if not cur.rowcount:
                raise brands.BrandError("not_found", "item not found")
            return self._send(200, {"ok": True})
        if rest == "calendar":
            if body.get("delete"):
                c.execute("DELETE FROM calendar_items WHERE id=? AND tenant_id=?", (body["id"], t))
                return self._send(200, {"ok": True})
            day = date.fromisoformat(body["day"]).isoformat()
            title = (body.get("title") or "").strip()[:200]
            if not title:
                raise ValueError("title required")
            if body.get("id"):
                c.execute("UPDATE calendar_items SET day=?, title=?, kind=?, status=?, notes=? WHERE id=? AND tenant_id=?",
                          (day, title, body.get("kind", "episode"), body.get("status", "idea"), body.get("notes", ""), body["id"], t))
                return self._send(200, {"id": body["id"]})
            cid = new_id("cal_")
            c.execute("INSERT INTO calendar_items VALUES (?,?,?,?,?,?,?,?,?)",
                      (cid, t, day, title, body.get("kind", "episode"), body.get("status", "idea"), body.get("notes", ""),
                       body.get("trend_id"), utcnow()))
            if body.get("trend_id"):
                c.execute("UPDATE trends SET status='calendar' WHERE id=? AND tenant_id=?", (body["trend_id"], t))
            return self._send(200, {"id": cid})
        if rest == "reports/generate":
            kind = body.get("kind", "manual")
            if kind not in ("manual", "weekly", "monthly"):
                raise ValueError("bad kind")
            start = date.fromisoformat(body["start"]) if body.get("start") else None
            end = date.fromisoformat(body["end"]) if body.get("end") else None
            if (start is None) != (end is None):
                raise ValueError("give both start and end")
            return self._send(200, reports.generate(c, t, kind, start=start, end=end))
        if rest == "settings":
            if "topics" in body:
                c.execute("DELETE FROM tenant_topics WHERE tenant_id=?", (t,))
                for x in body["topics"][:60]:
                    k = str(x.get("keyword", "")).strip()[:60]
                    if k:
                        c.execute("INSERT OR REPLACE INTO tenant_topics VALUES (?,?,?)", (t, k, float(x.get("weight", 1))))
            if "competitors" in body:
                c.execute("DELETE FROM competitors WHERE tenant_id=? AND platform='youtube'", (t,))
                for x in body["competitors"][:30]:
                    ref = str(x.get("ref", "")).strip()
                    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", ref):
                        c.execute("INSERT OR REPLACE INTO competitors VALUES (?,?,?,?)", (t, "youtube", ref, str(x.get("name", ""))[:80]))
                    elif ref:
                        raise ValueError(f"competitor must be a YouTube channel ID starting with UC: {ref}")
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"ai/(titles|thumbnail|trend)/([A-Za-z0-9_-]{1,64})", rest)
        if m:
            return self._send(200, ai_action(c, t, m.group(1), m.group(2), force=bool(body.get("refresh"))))
        return self._send(404, {"error": "not found"})

    def _oauth_callback(self, c, q):
        if "error" in q:
            return self._send(400, f"<p>Authorization cancelled ({q['error']}). <a href='/#/accounts'>Back</a></p>", "text/html")
        try:
            tenant, rows = youtube.finish_auth(c, state=q.get("state", ""), code=q.get("code", ""),
                                               client=vault.load_client("youtube"))
        except (youtube.ConnectorError, HttpError) as e:
            return self._send(400, f"<p>Connection failed: {e}. <a href='/#/accounts'>Back</a></p>", "text/html")
        return self._redirect(f"/?brand={tenant}&discovered={len(rows)}#/accounts")


def tiles(c, t):
    out = []
    for p in brands.PLATFORMS:
        rows = []
        for r in brands.accounts(c, t, p):
            d = dict(r)
            d.pop("credential_id", None)
            d.pop("scope_fingerprint", None)
            rows.append(d)
        live = [r for r in rows if r["state"] != brands.REJECTED]
        bound = next((r for r in live if r["state"] in brands.BOUND), None)
        out.append({"platform": p, "state": bound["state"] if bound else (live[-1]["state"] if live else brands.NOT_CONNECTED),
                    "primary": bound, "candidates": [r for r in live if r is not bound], "note": api.PLATFORM_NOTES[p],
                    "client_configured": bool(vault.load_client(p)) if p == "youtube" else None})
    return out


def ai_action(c, t, what, ref, force=False):
    from growth_os import analytics
    if what == "trend":
        tr = c.execute("SELECT * FROM trends WHERE id=? AND tenant_id=?", (ref, t)).fetchone()
        if not tr:
            raise brands.BrandError("not_found", "trend not found")
        payload = {"trend": {"title": tr["title"], "source": tr["source"], "published_at": tr["published_at"],
                             "matched_keywords": tr["matched_keywords"]},
                   "brand_topics": [k for k, _ in analytics.topic_keywords(c, t)][:12]}
        out, meta = ai.ask(c, t, f"trend:{ref}", payload, ai.TREND_INSTRUCTIONS, force=force)
        c.execute("UPDATE trends SET ai_json=? WHERE id=? AND tenant_id=?", (json.dumps(out | {"_meta": meta}), ref, t))
        return {"output": out, "meta": meta}
    d = api.video_detail(c, t, ref)
    v = d["video"]
    peers = {k: {"value": x["value"], "peer_median": x["peer_median"], "percentile": x["percentile"]}
             for k, x in d["peers"]["metrics"].items()}
    base = {"title": v["title"], "format": v["format"], "duration_min": round((v["duration_s"] or 0) / 60),
            "age_days": v["age_days"], "ctr_pct": v["ctr"], "avg_pct_viewed": v["avg_pct_viewed"],
            "peer_comparison": peers, "peer_basis": d["peers"]["basis"],
            "topic_keywords": [k for k, _ in analytics.topic_keywords(c, t)][:10]}
    if what == "titles":
        payload = base | {"search_terms": [s["term"] for s in d["search_terms"][:8]], "strategies": ai.TITLE_STRATEGIES,
                          "previous_titles": [h["value"] for h in d["history"] if h["field"] == "title"][:-1]}
        out, meta = ai.ask(c, t, f"titles:{ref}", payload, ai.TITLE_INSTRUCTIONS, force=force)
    else:
        f = d["thumbnail"]["features"]
        if not f:
            raise ValueError("no thumbnail analysed for this video yet")
        payload = base | {"measured_thumbnail": {k: f[k] for k in ("luminance", "contrast", "colorfulness", "saturation",
                                                                    "edge_density", "focal_contrast")},
                          "dominant_colors": [x["hex"] for x in f["dominant_colors"]]}
        out, meta = ai.ask(c, t, f"thumbnail:{ref}", payload, ai.THUMB_INSTRUCTIONS, force=force)
    return {"output": out, "meta": meta}


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/app", timeout=2) as r:
            return r.status == 200 and b"brands" in r.read()
    except Exception:
        return False


def serve(port=8765, db_path=None, open_browser=False, with_scheduler=True):
    url = f"http://127.0.0.1:{port}/"
    import sys
    if sys.stdout is None or sys.stderr is None:  # pythonw (Windows shortcut): log to a file instead
        logs = DATA_DIR / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(logs / "server.log", "a", buffering=1, encoding="utf-8")
    if already_running(port):
        print(f"Klip Growth OS is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return
    conn = db.connect(db_path)
    from growth_os import seed
    seed.ensure_ryj(conn)
    scheduler.ensure_defaults(conn)
    conn.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    srv.db_path = db_path
    sched = None
    if with_scheduler:
        sched = scheduler.Scheduler(REGISTRY, db_path)
        sched.start()
    print(f"Klip Growth OS running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if sched:
            sched.stop.set()
        srv.server_close()
