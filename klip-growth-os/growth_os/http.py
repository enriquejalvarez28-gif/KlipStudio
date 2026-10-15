"""Minimal HTTP client with quota logging, budgets, backoff and a response
cache. stdlib only, so no new dependencies (spec 9, "NO EXTRA TOOLS").

The transport is injectable so connectors are testable offline.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from growth_os.db import utcnow

DEFAULT_DAILY_REQUESTS = int(os.environ.get("GROWTH_OS_DAILY_API_REQUESTS", "500"))
MAX_RETRIES = 4


class HttpError(Exception):
    def __init__(self, status: int, body: dict | str):
        super().__init__(f"HTTP {status}: {str(body)[:300]}")
        self.status = status
        self.body = body


class BudgetExceeded(Exception):
    pass


def urllib_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
        # Treat network hiccups like a gateway timeout so the retry/backoff applies.
        return 504, json.dumps({"error": f"network: {str(e)[:200]}"}).encode()


class Client:
    def __init__(self, conn, tenant_id, *, run_id=None, transport=None, sleep=time.sleep,
                 daily_requests=DEFAULT_DAILY_REQUESTS):
        self.conn = conn
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self.daily_requests = daily_requests
        self._cache: dict[str, dict] = {}

    def used_today(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM usage_log WHERE tenant_id=? AND kind='api' AND cache_hit=0 AND at>=?",
            (self.tenant_id, utcnow()[:10]),
        ).fetchone()[0]

    def _log(self, name, status, ms, quota_units, cache_hit):
        self.conn.execute(
            """INSERT INTO usage_log (tenant_id, run_id, kind, name, quota_units, cache_hit, status, duration_ms, at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (self.tenant_id, self.run_id, "api", name, quota_units, int(cache_hit), status, ms, utcnow()),
        )

    def download(self, url, *, headers=None, log_name=None):
        """GET raw bytes (bulk report CSVs). Counts against the same budget."""
        name = log_name or url.split("?")[0]
        if self.used_today() >= self.daily_requests:
            raise BudgetExceeded(f"daily API request budget ({self.daily_requests}) reached; paused")
        for attempt in range(MAX_RETRIES + 1):
            t0 = time.monotonic()
            status, raw = self.transport("GET", url, dict(headers or {}), None)
            self._log(name, status, int((time.monotonic() - t0) * 1000), 1, False)
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                self.sleep(2 ** (attempt + 1))
                continue
            break
        if status >= 400:
            raise HttpError(status, raw[:300].decode(errors="replace") if isinstance(raw, bytes) else str(raw)[:300])
        return raw

    def request(self, method, url, *, params=None, headers=None, form=None, json_body=None,
                quota_units=1, cache=False, log_name=None):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        # Log the endpoint, never the query (it can carry ids we don't need in logs).
        name = log_name or url.split("?")[0]
        if cache and url in self._cache:
            self._log(name, 200, 0, 0, True)
            return self._cache[url]
        if self.used_today() >= self.daily_requests:
            raise BudgetExceeded(f"daily API request budget ({self.daily_requests}) reached; paused")
        headers = dict(headers or {})
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(MAX_RETRIES + 1):
            t0 = time.monotonic()
            status, raw = self.transport(method, url, headers, body)
            ms = int((time.monotonic() - t0) * 1000)
            self._log(name, status, ms, quota_units, False)
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                self.sleep(2 ** (attempt + 1))
                continue
            break
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {"raw": raw[:500].decode(errors="replace") if isinstance(raw, bytes) else str(raw)[:500]}
        if status >= 400:
            raise HttpError(status, data)
        if cache:
            self._cache[url] = data
        return data
