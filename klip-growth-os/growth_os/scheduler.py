"""Persistent background scheduler. Runs inside the app process (no Claude
session needed) whenever the computer and the app are running.

* schedules: what runs when (editable in the dashboard)
* job_runs: every run, with a UNIQUE dedup_key per schedule slot, so a
  restart, a double-click or a second app instance can't run a slot twice
* locks: a lease so only one scheduler instance ticks at a time
* retries with exponential backoff; final failure raises a dashboard alert
* missed slots (computer was off) run once on startup, never N times
"""

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta

from growth_os import db
from growth_os.db import new_id, utcnow

TICK_S = 2
LEASE_S = 60
HOLDER = f"{os.getpid()}-{new_id()}"

DEFAULTS = [
    ("analytics_sync", "analytics_sync", {"every_hours": 6}, "Sync analytics from connected platforms"),
    ("trend_research", "trend_research", {"daily_at": "06:30"}, "Research trends and opportunities"),
    ("daily_review", "daily_review", {"daily_at": "07:00"}, "Daily performance review"),
    ("packaging_check", "packaging_check", {"daily_at": "07:15"}, "Thumbnail and title opportunity check"),
    ("weekly_report", "weekly_report", {"weekly": "MON", "at": "08:00"}, "Weekly Monday report"),
    ("monthly_report", "monthly_report", {"monthly_day": 1, "at": "08:30"}, "Monthly executive report"),
]
DESCRIPTIONS = {name: d for name, _, _, d in DEFAULTS}
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def local_now():
    return datetime.now().astimezone()


def next_slot(spec, after):
    """Next scheduled local datetime strictly after `after`."""
    if "every_hours" in spec:
        h = int(spec["every_hours"])
        base = after.replace(minute=0, second=0, microsecond=0)
        nxt = base.replace(hour=(base.hour // h) * h)
        while nxt <= after:
            nxt += timedelta(hours=h)
        return nxt
    hh, mm = map(int, spec.get("daily_at", spec.get("at", "08:00")).split(":"))
    cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if "daily_at" in spec:
        return cand if cand > after else cand + timedelta(days=1)
    if "weekly" in spec:
        target = DAYS.index(spec["weekly"].upper()[:3])
        cand += timedelta(days=(target - cand.weekday()) % 7)
        return cand if cand > after else cand + timedelta(days=7)
    if "monthly_day" in spec:
        d = int(spec["monthly_day"])
        cand = cand.replace(day=d)
        if cand <= after:
            y, m = (cand.year + (cand.month == 12), cand.month % 12 + 1)
            cand = cand.replace(year=y, month=m)
        return cand
    raise ValueError(f"bad schedule spec {spec}")


def describe(spec):
    if "every_hours" in spec:
        return f"Every {spec['every_hours']} h"
    if "daily_at" in spec:
        return f"Daily {spec['daily_at']}"
    if "weekly" in spec:
        return f"Weekly {spec['weekly'].title()} {spec['at']}"
    if "monthly_day" in spec:
        return f"Monthly day {spec['monthly_day']} {spec['at']}"
    return json.dumps(spec)


def ensure_defaults(conn):
    now = local_now()
    for name, kind, spec, _ in DEFAULTS:
        conn.execute("INSERT OR IGNORE INTO schedules (name, kind, spec_json, next_run_at) VALUES (?,?,?,?)",
                     (name, kind, json.dumps(spec), next_slot(spec, now).isoformat()))


def enqueue(conn, kind, *, schedule_name=None, tenant_id=None, trigger="manual", slot=None):
    """Insert a queued run unless an identical one is already queued/running."""
    if schedule_name is None:  # manual runs still update their schedule's health + retry policy
        row = conn.execute("SELECT name FROM schedules WHERE kind=?", (kind,)).fetchone()
        schedule_name = row[0] if row else None
    if trigger == "manual":
        busy = conn.execute("""SELECT run_id FROM job_runs WHERE kind=? AND COALESCE(tenant_id,'')=COALESCE(?, '')
                               AND state IN ('queued','running','retry')""", (kind, tenant_id)).fetchone()
        if busy:
            return busy[0], False
        dedup = f"manual:{kind}:{tenant_id or '*'}:{new_id()}"
    else:
        dedup = f"sched:{schedule_name}:{slot}"
    run_id = new_id("run_")
    cur = conn.execute("""INSERT OR IGNORE INTO job_runs (run_id, schedule_name, kind, tenant_id, trigger, dedup_key,
                          state, queued_at) VALUES (?,?,?,?,?,?,?,?)""",
                       (run_id, schedule_name, kind, tenant_id, trigger, dedup, "queued", utcnow()))
    return run_id, cur.rowcount == 1


def _lease(conn):
    now = utcnow()
    exp = (datetime.fromisoformat(now) + timedelta(seconds=LEASE_S)).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT holder, expires_at FROM locks WHERE name='scheduler'").fetchone()
        if row and row["holder"] != HOLDER and row["expires_at"] > now:
            conn.execute("ROLLBACK")
            return False
        conn.execute("INSERT OR REPLACE INTO locks VALUES ('scheduler', ?, ?)", (HOLDER, exp))
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def due_schedules(conn):
    now = local_now()
    for s in conn.execute("SELECT * FROM schedules WHERE enabled=1").fetchall():
        nxt = datetime.fromisoformat(s["next_run_at"]) if s["next_run_at"] else None
        if nxt and nxt <= now:
            # Missed slots while off collapse into this one run.
            enqueue(conn, s["kind"], schedule_name=s["name"], trigger="schedule", slot=nxt.isoformat())
            spec = json.loads(s["spec_json"])
            conn.execute("UPDATE schedules SET next_run_at=? WHERE name=?", (next_slot(spec, now).isoformat(), s["name"]))


def run_one(conn, registry, run):
    def progress(p, msg=""):
        conn.execute("UPDATE job_runs SET progress=?, message=? WHERE run_id=?", (int(p), str(msg)[:200], run["run_id"]))

    conn.execute("UPDATE job_runs SET state='running', started_at=?, attempt=attempt+1, progress=0 WHERE run_id=?",
                 (utcnow(), run["run_id"]))
    fn = registry.get(run["kind"])
    try:
        if fn is None:
            raise RuntimeError(f"no handler for {run['kind']}")
        result = fn(conn, run["tenant_id"], progress)
        skipped = isinstance(result, dict) and result.get("skipped") and len(result) == 1
        state = "skipped" if skipped else "succeeded"
        conn.execute("""UPDATE job_runs SET state=?, finished_at=?, progress=100, result_json=?, message=? WHERE run_id=?""",
                     (state, utcnow(), json.dumps(result, default=str)[:20000],
                      (result.get("skipped") if skipped else "ok") if isinstance(result, dict) else "ok", run["run_id"]))
        if run["schedule_name"]:
            conn.execute("""UPDATE schedules SET last_run_at=?, last_status=?, last_error=NULL,
                            last_success_at=CASE WHEN ?='succeeded' THEN ? ELSE last_success_at END WHERE name=?""",
                         (utcnow(), state, state, utcnow(), run["schedule_name"]))
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:500]
        sched = conn.execute("SELECT retry_max FROM schedules WHERE name=?", (run["schedule_name"],)).fetchone()
        retry_max = sched["retry_max"] if sched else 1
        attempt = conn.execute("SELECT attempt FROM job_runs WHERE run_id=?", (run["run_id"],)).fetchone()[0]
        if attempt < retry_max:
            delay = 60 * (2 ** (attempt - 1))
            conn.execute("UPDATE job_runs SET state='retry', message=?, next_retry_at=? WHERE run_id=?",
                         (err, (datetime.fromisoformat(utcnow()) + timedelta(seconds=delay)).isoformat(), run["run_id"]))
        else:
            conn.execute("UPDATE job_runs SET state='failed', finished_at=?, message=?, result_json=? WHERE run_id=?",
                         (utcnow(), err, json.dumps({"traceback": traceback.format_exc()[-2000:]}), run["run_id"]))
            conn.execute("INSERT INTO alerts (tenant_id, level, source, message, created_at) VALUES (?,?,?,?,?)",
                         (run["tenant_id"], "error", run["kind"], err, utcnow()))
        if run["schedule_name"]:
            conn.execute("UPDATE schedules SET last_run_at=?, last_status='failed', last_error=? WHERE name=?",
                         (utcnow(), err, run["schedule_name"]))


def tick(conn, registry):
    if not _lease(conn):
        return 0
    due_schedules(conn)
    now = utcnow()
    runs = conn.execute("""SELECT * FROM job_runs WHERE state='queued' OR (state='retry' AND next_retry_at<=?)
                           ORDER BY queued_at LIMIT 5""", (now,)).fetchall()
    for r in runs:
        run_one(conn, registry, r)
    return len(runs)


def recover(conn):
    """Runs left 'running' by a crash/shutdown go back to the queue once."""
    conn.execute("UPDATE job_runs SET state='retry', next_retry_at=?, message='interrupted; retrying' WHERE state='running'",
                 (utcnow(),))


class Scheduler(threading.Thread):
    def __init__(self, registry, db_path=None):
        super().__init__(daemon=True, name="growth-os-scheduler")
        self.registry = registry
        self.db_path = db_path
        self.stop = threading.Event()

    def run(self):
        conn = db.connect(self.db_path)
        ensure_defaults(conn)
        recover(conn)
        while not self.stop.is_set():
            try:
                tick(conn, self.registry)
            except Exception:
                traceback.print_exc()
            self.stop.wait(TICK_S)
        conn.execute("DELETE FROM locks WHERE name='scheduler' AND holder=?", (HOLDER,))


def wait_for(conn, run_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = conn.execute("SELECT state FROM job_runs WHERE run_id=?", (run_id,)).fetchone()
        if r and r[0] in ("succeeded", "failed", "skipped"):
            return r[0]
        time.sleep(0.2)
    return None
