"""Klip Growth OS owner app server (stdlib only).

* Binds to 127.0.0.1 only; Host header must be local (blocks DNS rebinding).
* POSTs need the per-process CSRF token embedded in the page.
* Every /api/t/<tenant>/... route is tenant-scoped; ids from another tenant
  are simply not found.
* The background scheduler runs in the same process (see scheduler.py).
"""

import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from growth_os import ai, analytics, api, autopilot, brands, brief, concepts, insights, db, discovery, prep, reports, scheduler, thumbs, vault
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
            m = re.fullmatch(rf"/preview/{TENANT}/([A-Za-z0-9_-]{{1,64}})/([0-9TZ]{{8,16}}-[a-z_]+-(?:A|B|sheet)\.jpg)", path)
            if m:
                brands.get_brand(c, m.group(1))
                f = DATA_DIR / "previews" / m.group(1) / m.group(2) / m.group(3)
                if not f.exists():
                    return self._send(404, {"error": "no such preview"})
                return self._send(200, f.read_bytes(), "image/jpeg")
            m = re.fullmatch(rf"/concept/{TENANT}/([A-Za-z0-9_-]{{1,64}})/([0-9TZ]{{8,16}}-[1-5]-[a-z_]+\.jpg)", path)
            if m:
                brands.get_brand(c, m.group(1))
                f = DATA_DIR / "concepts" / m.group(1) / m.group(2) / m.group(3)
                if not f.exists():
                    return self._send(404, {"error": "no such concept"})
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
        if path == "/api/restart":
            RESTART.set()
            return self._send(200, {"ok": True, "message": "restarting; the page reloads in a few seconds"})
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
            "audience": lambda: analytics.audience(c, t),
            "discovery": lambda: discovery.page(c, t),
            "brief": lambda: brief.latest(c, t),
            "autopilot": lambda: autopilot.page(c, t),
            "insights": lambda: insights.page(c, t),
            "cohorts": lambda: prep.cohorts(c, t, q.get("format") or None),
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
        m = re.fullmatch(r"concepts/([A-Za-z0-9_-]{1,64})", rest)
        if m:
            return self._send(200, {"latest": concepts.latest(c, t, m.group(1))})
        m = re.fullmatch(r"thumbs/([A-Za-z0-9_-]{1,64})", rest)
        if m:
            try:
                return self._send(200, api.thumb_studio(c, t, m.group(1)))
            except LookupError as e:
                raise brands.BrandError("not_found", str(e))
        if rest == "experiments":
            return self._send(200, thumbs.experiments(c, t))
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
        m = re.fullmatch(r"autopilot/(?:(run|mode|cap|approve-all)|(chg_[a-f0-9]+)/(approve|skip|undo|retry|redraft))", rest)
        if m:
            try:
                if m.group(1) == "run":
                    return self._send(200, autopilot.daily_run(c, t))
                if m.group(1) == "cap":
                    return self._send(200, autopilot.set_cap(c, t, body.get("cap", 0)))
                if m.group(1) == "mode":
                    return self._send(200, autopilot.set_mode(c, t, str(body.get("mode", ""))))
                if m.group(1) == "approve-all":
                    res = []
                    for r in autopilot.page(c, t)["pending"]:
                        try:
                            if r["status"] == "proposed":
                                autopilot.decide(c, t, r["id"], "approve")
                            res.append(autopilot.apply(c, t, r["id"]))
                        except Exception as e:  # keep going; each result is reported
                            res.append({"id": r["id"], "status": "failed", "error": str(e)[:200]})
                    return self._send(200, {"results": res})
                cid, act = m.group(2), m.group(3)
                if act == "skip":
                    return self._send(200, autopilot.decide(c, t, cid, "skip"))
                if act == "redraft":
                    return self._send(200, autopilot.redraft(c, t, cid))
                if act == "undo":
                    return self._send(200, autopilot.rollback(c, t, cid))
                if act == "approve":
                    autopilot.decide(c, t, cid, "approve", chosen=body.get("chosen") or None)
                if act == "retry":
                    c.execute("UPDATE channel_changes SET status='approved', error='' WHERE id=? AND tenant_id=? "
                              "AND status='failed'", (cid, t))
                return self._send(200, autopilot.apply(c, t, cid))
            except LookupError as e:
                raise brands.BrandError("not_found", str(e))
            except (ValueError, autopilot.AutopilotError, brands.BrandError) as e:
                return self._send(400, {"error": "autopilot", "message": str(e)[:400]})
        if rest == "brief":
            return self._send(200, brief.generate(c, t, force=bool(body.get("force"))))
        m = re.fullmatch(r"concepts/([A-Za-z0-9_-]{1,64})", rest)
        if m:
            try:
                return self._send(200, {"latest": concepts.generate(c, t, m.group(1))})
            except LookupError as e:
                raise brands.BrandError("not_found", str(e))
            except ValueError as e:
                return self._send(400, {"error": "bad_request", "message": str(e)})
        m = re.fullmatch(r"recommendations/(rec_[a-f0-9]+)/(prepare|dry-run)", rest)
        if m or rest in ("discovery/distribution", "discovery/ai-sample", "discovery/plan", "discovery/competitors"):
            try:
                if rest == "discovery/competitors":
                    return self._send(200, discovery.research_competitors(c, t))
                if rest == "discovery/distribution":
                    return self._send(200, discovery.check_distribution(c, t, term=(body.get("term") or None)))
                if rest == "discovery/ai-sample":
                    return self._send(200, discovery.add_ai_sample(c, t, body))
                if rest == "discovery/plan":
                    return self._send(200, discovery.plan_episode(c, t, str(body.get("topic", "")), str(body.get("guest", ""))[:120]))
                if m.group(2) == "prepare":
                    return self._send(200, prep.prepare_rec(c, t, m.group(1)))
                return self._send(200, discovery.operator_dry_run(c, t, m.group(1), str(body.get("channel_id", ""))))
            except LookupError as e:
                raise brands.BrandError("not_found", str(e))
            except ValueError as e:
                return self._send(400, {"error": "bad_request", "message": str(e)})
        m = re.fullmatch(r"thumbs/([A-Za-z0-9_-]{1,64})/(format|previews)", rest)
        if m or rest == "experiments":
            try:
                if rest == "experiments":
                    return self._send(200, thumbs.save_experiment(c, t, body))
                if m.group(2) == "format":
                    return self._send(200, thumbs.set_tag(c, t, m.group(1), str(body.get("format", ""))))
                hl = [str(x)[:90] for x in (body.get("headlines") or [])][:2]
                return self._send(200, thumbs.previews(c, t, m.group(1), hl, str(body.get("format", "guest")),
                                                       str(body.get("credential", ""))[:48]))
            except LookupError as e:
                raise brands.BrandError("not_found", str(e))
            except ValueError as e:
                return self._send(400, {"error": "bad_request", "message": str(e)})
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
                return self._send(200, {"auth_url": youtube.begin_auth(c, t, redirect, client, write=bool(body.get("write")))})
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
        m = re.fullmatch(r"recommendations/(rec_[a-f0-9]+)/workflow", rest)
        if m:
            try:
                return self._send(200, analytics.move_rec(c, t, m.group(1), str(body.get("to", "")), "owner",
                                                          str(body.get("note", ""))[:500]))
            except LookupError as e:
                raise brands.BrandError("not_found", str(e))
            except ValueError as e:
                return self._send(400, {"error": "bad_state", "message": str(e)})
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


# ── Self-update: relaunch when the code on disk changes ─────────────────
CODE_DIR = Path(__file__).resolve().parent
RESTART = threading.Event()  # set by POST /api/restart or the code watcher


def code_fingerprint():
    h = []
    for f in sorted(CODE_DIR.rglob("*")):
        if f.is_file() and f.suffix in (".py", ".js", ".css", ".html") and "__pycache__" not in f.parts:
            st = f.stat()
            h.append(f"{f.relative_to(CODE_DIR)}:{st.st_mtime_ns}:{st.st_size}")
    return hashlib.sha256("|".join(h).encode()).hexdigest()


def _jobs_running(db_path):
    try:
        c = db.connect(db_path)
        n = c.execute("SELECT COUNT(*) FROM job_runs WHERE state='running'").fetchone()[0]
        c.close()
        return n > 0
    except Exception:
        return False


def _relaunch(srv, sched, port, with_scheduler, db_path):
    """Start a fresh copy of the app, then exit this one. The new process waits
    for the port to free up, so there is no 'already running' race."""
    import subprocess
    import sys
    deadline = time.time() + 600
    while _jobs_running(db_path) and time.time() < deadline:  # never cut a sync in half
        time.sleep(5)
    args = [sys.executable, "-m", "growth_os", "serve", "--port", str(port)] + ([] if with_scheduler else ["--no-scheduler"])
    env = dict(os.environ, GROWTH_OS_RESTARTED="1")
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    print(f"{utcnow()} code changed or restart requested: relaunching")
    subprocess.Popen(args, cwd=str(CODE_DIR.parent), env=env, creationflags=flags, close_fds=True)
    if sched:
        sched.stop.set()
    threading.Thread(target=srv.shutdown, daemon=True).start()
    time.sleep(1)
    srv.server_close()
    os._exit(0)


def _watch(srv, sched, port, with_scheduler, db_path, every=20):
    base = code_fingerprint()
    while True:
        if RESTART.wait(every):
            return _relaunch(srv, sched, port, with_scheduler, db_path)
        try:
            fp = code_fingerprint()
        except Exception:
            continue
        if fp != base:
            time.sleep(5)  # let a multi-file copy finish
            return _relaunch(srv, sched, port, with_scheduler, db_path)


OPTIONAL_DEPS = {"cv2": "opencv-python-headless>=4.9"}  # face finding for per-episode thumbnails (free, local)


def ensure_optional_deps():
    """Install free optional packages once, in the background; the app works without them."""
    import importlib
    import subprocess
    import sys
    for mod, spec in OPTIONAL_DEPS.items():
        try:
            importlib.import_module(mod)
            continue
        except ImportError:
            pass
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", spec],
                               capture_output=True, text=True, timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            msg = "installed" if r.returncode == 0 else f"failed: {(r.stderr or r.stdout)[-300:]}"
        except Exception as e:
            msg = f"failed: {e}"
        (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "logs" / "deps.log", "a", encoding="utf-8") as f:
            f.write(f"{db.utcnow()} {spec}: {msg}\n")


def serve(port=8765, db_path=None, open_browser=False, with_scheduler=True, watch=True):
    url = f"http://127.0.0.1:{port}/"
    import sys
    if sys.stdout is None or sys.stderr is None:  # pythonw (Windows shortcut): log to a file instead
        logs = DATA_DIR / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(logs / "server.log", "a", buffering=1, encoding="utf-8")
    if os.environ.pop("GROWTH_OS_RESTARTED", None):
        for _ in range(60):  # previous copy is shutting down
            if not already_running(port):
                break
            time.sleep(0.5)
    elif already_running(port):
        print(f"Klip Growth OS is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return
    conn = db.connect(db_path)
    from growth_os import seed
    seed.ensure_ryj(conn)
    scheduler.ensure_defaults(conn)
    conn.close()
    threading.Thread(target=ensure_optional_deps, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    srv.db_path = db_path
    sched = None
    if with_scheduler:
        sched = scheduler.Scheduler(REGISTRY, db_path)
        sched.start()
    print(f"Klip Growth OS running at {url}  (Ctrl+C to stop) · code {code_fingerprint()[:10]}")
    if watch:
        threading.Thread(target=_watch, args=(srv, sched, port, with_scheduler, db_path), daemon=True).start()
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
