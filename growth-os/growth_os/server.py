"""Local Manage Accounts server (stdlib only).

Binds to 127.0.0.1. POSTs need the per-process CSRF token embedded in the
page, and the Host header must be local (blocks DNS rebinding). Every API
route is tenant-scoped through brands.get_account / brands.accounts.
Public share links (P9) will be a separate read-only service, not this.
"""

import json
import re
import secrets
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from growth_os import brands, db, vault
from growth_os.connectors import podcast, youtube
from growth_os.http import BudgetExceeded, HttpError

WEB = Path(__file__).parent / "web"
CSRF = secrets.token_urlsafe(24)
OWNER = "owner"

PLATFORM_NOTES = {
    "youtube": "Google OAuth, read-only analytics scopes.",
    "instagram": "Needs a Meta app + Instagram professional account linked to a Facebook Page (P5).",
    "spotify": "No public analytics API: verify the show, then import Spotify for Creators exports.",
    "apple_podcasts": "No public analytics API: verify the show, then import Apple Podcasts Connect exports.",
}


def account_json(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("credential_id", None)
    d.pop("scope_fingerprint", None)
    d["next_action"] = next_action(d)
    return d


def next_action(a: dict) -> str:
    return {
        brands.AUTHORIZED_UNASSIGNED: "Verify identity: is this the brand's account?",
        brands.OWNER_VERIFIED: "Assign to brand",
        brands.ASSIGNED: "Test connection (first small sync)" if a["platform"] in ("youtube", "instagram")
        else "Enable import",
        brands.ACTIVE: "Up to date",
        brands.IMPORT_ONLY: "Import report",
        brands.SYNC_FAILED: "Test connection again",
        brands.NEEDS_REAUTH: "Reconnect",
        brands.PERMISSION_LIMITED: "Reconnect and grant the requested permissions",
        brands.DISCONNECTED: "Connect",
        brands.REVOKED: "Connect",
        brands.REJECTED: "Rejected — not imported",
    }.get(a["state"], "")


def tiles(conn, tenant_id):
    out = []
    for p in brands.PLATFORMS:
        rows = [account_json(r) for r in brands.accounts(conn, tenant_id, p)]
        live = [r for r in rows if r["state"] not in (brands.REJECTED,)]
        bound = next((r for r in live if r["state"] in brands.BOUND), None)
        state = bound["state"] if bound else (live[-1]["state"] if live else brands.NOT_CONNECTED)
        out.append({
            "platform": p, "state": state, "primary": bound, "candidates": [r for r in live if r is not bound],
            "note": PLATFORM_NOTES[p], "client_configured": bool(vault.load_client(p)) if p == "youtube" else None,
        })
    return out


def diagnostics(conn, tenant_id):
    today = db.utcnow()[:10]
    rows = conn.execute(
        """SELECT kind, name, COUNT(*) n, SUM(cache_hit) hits, SUM(quota_units) quota,
           SUM(tokens_in) tin, SUM(tokens_out) tout, SUM(CASE WHEN status>=400 THEN 1 ELSE 0 END) errors
           FROM usage_log WHERE tenant_id=? AND at>=? GROUP BY kind, name ORDER BY n DESC""",
        (tenant_id, today)).fetchall()
    return {"day": today, "rows": [dict(r) for r in rows]}


class Handler(BaseHTTPRequestHandler):
    server_version = "GrowthOS"

    def log_message(self, fmt, *args):  # keep OAuth codes out of logs
        path = args[0].split("?")[0] if args and isinstance(args[0], str) else ""
        print(f"{self.command} {path} -> {args[1] if len(args) > 1 else ''}")

    # ── plumbing ──
    @property
    def conn(self):
        return self.server.conn

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(raw)

    def _local(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _redirect_uri(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/oauth/callback"

    def do_GET(self):
        if not self._local():
            return self._send(403, {"error": "local access only"})
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path == "/":
                html = (WEB / "accounts.html").read_text().replace("__CSRF__", CSRF)
                return self._send(200, html, "text/html")
            if u.path in ("/app.js", "/app.css"):
                ctype = "text/javascript" if u.path.endswith(".js") else "text/css"
                return self._send(200, (WEB / u.path[1:]).read_bytes(), ctype)
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if u.path == "/oauth/callback":
                return self._oauth_callback(q)
            if u.path == "/api/brands":
                return self._send(200, [dict(b) for b in brands.list_brands(self.conn)])
            m = re.fullmatch(r"/api/brands/([a-z0-9-]+)/(tiles|diagnostics|audit)", u.path)
            if m:
                t, what = m.groups()
                brands.get_brand(self.conn, t)
                if what == "tiles":
                    return self._send(200, tiles(self.conn, t))
                if what == "diagnostics":
                    return self._send(200, diagnostics(self.conn, t))
                rows = self.conn.execute(
                    "SELECT actor, event, detail_json, at FROM audit_log WHERE tenant_id=? ORDER BY id DESC LIMIT 50",
                    (t,)).fetchall()
                return self._send(200, [dict(r) for r in rows])
            return self._send(404, {"error": "not found"})
        except brands.BrandError as e:
            return self._send(400, {"error": e.code, "message": str(e)})

    def _oauth_callback(self, q):
        if "error" in q:
            return self._send(400, f"<p>Authorization cancelled: {q['error']}. <a href='/'>Back</a></p>", "text/html")
        client = vault.load_client("youtube")
        try:
            tenant, rows = youtube.finish_auth(self.conn, state=q.get("state", ""), code=q.get("code", ""), client=client)
        except (youtube.ConnectorError, HttpError) as e:
            return self._send(400, f"<p>Connection failed: {e}. <a href='/'>Back</a></p>", "text/html")
        self.send_response(302)
        self.send_header("Location", f"/?brand={tenant}&discovered={len(rows)}")
        self.end_headers()

    def do_POST(self):
        if not self._local() or self.headers.get("X-CSRF") != CSRF:
            return self._send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        path = urllib.parse.urlsplit(self.path).path
        c = self.conn
        try:
            if path == "/api/brands":
                t = brands.create_brand(c, body["display_name"].strip(), OWNER,
                                        timezone=body.get("timezone") or "America/New_York",
                                        contact=body.get("contact", ""))
                return self._send(200, {"tenant_id": t})
            m = re.fullmatch(r"/api/brands/([a-z0-9-]+)/connect/(youtube|spotify|apple_podcasts|instagram)", path)
            if m:
                t, p = m.groups()
                brands.get_brand(c, t)
                if p == "youtube":
                    client = vault.load_client("youtube")
                    if not client:
                        return self._send(400, {"error": "no_client", "message":
                                                "Add your Google OAuth desktop client to data/youtube_client.json first (see README)."})
                    return self._send(200, {"auth_url": youtube.begin_auth(c, t, self._redirect_uri(), client)})
                if p == "spotify":
                    return self._send(200, {"row": podcast.discover_spotify(c, t, body.get("show", ""),
                                                                            name=body.get("name", ""))})
                if p == "apple_podcasts":
                    return self._send(200, {"row": podcast.discover_apple(c, t, body.get("show", "").strip())})
                return self._send(400, {"error": "not_built", "message": PLATFORM_NOTES["instagram"]})
            m = re.fullmatch(r"/api/brands/([a-z0-9-]+)/accounts/(acct_[a-f0-9]+)/([a-z_]+)", path)
            if m:
                t, row, action = m.groups()
                acct = brands.get_account(c, t, row)  # tenant-scoped; 400 if not this brand's
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
                else:
                    return self._send(400, {"error": "bad_action"})
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except brands.BrandError as e:
            return self._send(400, {"error": e.code, "message": str(e)})
        except youtube.ConnectorError as e:
            return self._send(409, {"error": e.code, "message": str(e)})
        except (BudgetExceeded, HttpError) as e:
            return self._send(502, {"error": type(e).__name__, "message": str(e)[:300]})


def serve(port: int = 8765, db_path=None):
    # Single-threaded on purpose: one owner, one SQLite connection, no races.
    srv = HTTPServer(("127.0.0.1", port), Handler)
    srv.conn = db.connect(db_path)
    print(f"Growth OS — Manage Accounts at http://127.0.0.1:{port}/")
    srv.serve_forever()
