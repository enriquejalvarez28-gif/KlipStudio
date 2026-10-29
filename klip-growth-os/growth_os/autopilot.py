"""YouTube autopilot (the Operator role): a daily pass that drafts packaging
changes from the analytics and, once approved (or in an auto mode the owner
switched on), applies them to YouTube with read-back verification and undo.

Changes it can make: title, description (new first lines + chapters, the old
description kept underneath), tags, and a custom thumbnail (long-form only;
Shorts use frames picked in the app). Never: privacy, deleting, publishing.

Safety rails
- Write access needs the owner's Google sign-in with youtube.force-ssl; every
  write goes through brands.preflight_public_action (bound channel + scope +
  approval record).
- Max DAILY_CAP new packages a day; COOLDOWN_DAYS between changes to one video;
  winners (top quarter by views/day) keep their title and thumbnail.
- Before each write the live snippet and thumbnail are saved; undo restores them.
- If someone (or another bot) changes the video after us, we log it and don't fight.
"""

import json
from datetime import date, datetime, timedelta, timezone

from growth_os import analytics, brands, prep, vault
from growth_os.connectors import youtube
from growth_os.db import DATA_DIR, audit, get_setting, new_id, set_setting, utcnow
from growth_os.http import Client, HttpError

MODES = {
    "approve": "Drafts every day; nothing changes on YouTube until you approve.",
    "auto_missing": "Fills only what's missing (empty description, no tags) automatically; everything else waits for approval.",
    "auto_all": "Applies its daily changes automatically (titles, descriptions, tags, thumbnails). You get a log and undo.",
}
DAILY_CAP = 3          # default; the owner can raise it (CAP_CHOICES)
CAP_CHOICES = (3, 5, 10)
LONG_TITLE = 60        # YouTube cuts titles off around here on phones and in search
COOLDOWN_DAYS = 14
MIN_IMPRESSIONS = 500
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
SNIPPET_KEYS = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
OPEN = ("proposed", "approved")


class AutopilotError(Exception):
    pass


def mode(conn, tenant_id):
    m = get_setting(conn, f"autopilot.mode.{tenant_id}", "approve")
    return m if m in MODES else "approve"


def set_mode(conn, tenant_id, m):
    if m not in MODES:
        raise ValueError("unknown mode")
    set_setting(conn, f"autopilot.mode.{tenant_id}", m)
    audit(conn, tenant_id, "owner", "autopilot.mode", {"mode": m})
    return {"mode": m}


def cap(conn, tenant_id):
    n = get_setting(conn, f"autopilot.cap.{tenant_id}", DAILY_CAP)
    return n if n in CAP_CHOICES else DAILY_CAP


def set_cap(conn, tenant_id, n):
    n = int(n)
    if n not in CAP_CHOICES:
        raise ValueError("daily limit must be 3, 5 or 10")
    set_setting(conn, f"autopilot.cap.{tenant_id}", n)
    audit(conn, tenant_id, "owner", "autopilot.cap", {"cap": n})
    return {"cap": n}


def _account(conn, tenant_id):
    return conn.execute("SELECT * FROM platform_accounts WHERE tenant_id=? AND platform='youtube' AND state!=? "
                        "ORDER BY updated_at DESC LIMIT 1", (tenant_id, brands.REJECTED)).fetchone()


def write_status(conn, tenant_id):
    a = _account(conn, tenant_id)
    if not a:
        return {"has_write": False, "note": "No YouTube channel connected."}
    bound = a["state"] in (brands.ASSIGNED, brands.ACTIVE, brands.SYNCING)
    has = bound and a["access_level"] == "WRITE_METADATA"
    note = None if has else (
        "Read-only: the channel owner must click “Grant write access” and approve in Google." if bound
        else f"Channel is {a['state'].replace('_', ' ').lower()}; reconnect it first.")
    return {"has_write": has, "channel": a["account_name"], "channel_id": a["platform_account_id"],
            "access": a["access_level"], "state": a["state"], "authorized_by": a["connected_identity"], "note": note}


def _latest(conn, tenant_id, asset_id, field):
    r = conn.execute("SELECT value FROM asset_history WHERE tenant_id=? AND asset_id=? AND field=? "
                     "ORDER BY observed_at DESC LIMIT 1", (tenant_id, asset_id, field)).fetchone()
    return r[0] if r else None


# ── daily drafting ────────────────────────────────────────────────────

def candidates(conn, tenant_id):
    vids = analytics.videos(conn, tenant_id)
    since = (date.today() - timedelta(days=COOLDOWN_DAYS)).isoformat()
    busy = {r[0] for r in conn.execute(
        """SELECT asset_id FROM channel_changes WHERE tenant_id=? AND (status IN ('proposed','approved')
           OR (created_at>=? AND status NOT IN ('skipped')))""", (tenant_id, since))}
    packaging = {r[0] for r in conn.execute("SELECT asset_id FROM recommendations WHERE tenant_id=? AND status='open' "
                                            "AND kind='thumbnail_title_review'", (tenant_id,))}
    out = []
    pending = {r[0] for r in conn.execute("SELECT asset_id FROM channel_changes WHERE tenant_id=? AND status IN "
                                          "('proposed','approved')", (tenant_id,))}
    # Thumbnails belong to the other agent. If it replaced a thumbnail after we changed that video's title,
    # re-check that the title still reads as one message with the new picture (this skips the cooldown).
    by_id = {v["asset_id"]: v for v in vids}
    for r in conn.execute("""SELECT asset_id, MAX(applied_at) at FROM channel_changes WHERE tenant_id=?
                             AND status IN ('verified','partial') AND chosen_json LIKE '%"title": "%' GROUP BY asset_id""",
                          (tenant_id,)):
        thumb_at = conn.execute("SELECT MAX(observed_at) FROM asset_history WHERE tenant_id=? AND asset_id=? AND field='thumbnail'",
                                (tenant_id, r["asset_id"])).fetchone()[0]
        if r["asset_id"] in by_id and r["asset_id"] not in pending and thumb_at and r["at"] and thumb_at > r["at"]:
            out.append({"v": by_id[r["asset_id"]], "reason": "thumb_changed", "score": 2.8, "missing": [], "shorten": True,
                        "evidence": ["The thumbnail was replaced after our title change; re-checking the title fits the new image"]})
            busy.add(r["asset_id"])
    for v in vids:
        a = v["asset_id"]
        if a in busy or (_latest(conn, tenant_id, a, "privacy") or "public") != "public":
            continue
        desc = _latest(conn, tenant_id, a, "description") or ""
        tags = json.loads(_latest(conn, tenant_id, a, "tags") or "[]")
        pm = analytics.peer_stats(vids, v)["metrics"]
        vpd, ctr, imp = pm.get("views_per_day") or {}, pm.get("ctr") or {}, pm.get("impressions") or {}
        winner = (vpd.get("percentile") or 0) >= 75
        missing = [k for k, bad in (("description", len(desc.strip()) < 40), ("tags", not tags)) if bad]
        shorten = len(v["title"] or "") > LONG_TITLE and not winner
        low_ctr = (v["format"] == "long_form" and not winner and (v["age_days"] or 0) >= 14
                   and (imp.get("value") or 0) >= MIN_IMPRESSIONS and ctr.get("value") is not None
                   and ((ctr.get("percentile") is not None and ctr["percentile"] <= 25)
                        or (a in packaging and ctr["value"] < (ctr.get("peer_median") or 0))))
        if low_ctr:
            out.append({"v": v, "reason": "low_ctr", "score": 3 + (imp.get("value") or 0) / 1e4, "missing": missing,
                        "evidence": [f"CTR {ctr['value']:.2f}% vs {ctr.get('peer_median'):.2f}% for similar videos, on "
                                     f"{int(imp.get('value') or 0):,} impressions"]})
        elif len(v["title"] or "") > LONG_TITLE and not winner:
            out.append({"v": v, "reason": "long_title", "score": 2.5, "missing": missing, "shorten": True,
                        "evidence": [f"Title is {len(v['title'])} characters; phones and search cut it off around {LONG_TITLE}"]})
        elif missing:
            out.append({"v": v, "reason": "missing", "score": 2, "missing": missing, "shorten": shorten,
                        "evidence": [f"Missing: {', '.join(missing)}"]})
        elif (v["age_days"] or 99) <= 3:
            out.append({"v": v, "reason": "new_upload", "score": 1, "missing": [],
                        "evidence": ["New upload: add search keywords while YouTube is first testing it"]})
    return sorted(out, key=lambda c: -c["score"])


def _proposal(conn, tenant_id, c, runner=None):
    v = c["v"]
    repackage = c["reason"] in ("low_ctr", "long_title", "thumb_changed")
    want_thumb = False  # owner rule (2026-10-29): keep the current thumbnails; Autopilot never drafts or changes them
    pack = prep.asset_pack(conn, tenant_id, v["asset_id"], diagnosis="packaging" if repackage else "", runner=runner,
                           thumbnails_wanted=want_thumb, title_max=LONG_TITLE)
    old_tags = json.loads(_latest(conn, tenant_id, v["asset_id"], "tags") or "[]")
    merged = list(dict.fromkeys(old_tags + pack["seo"]["tags"]))
    while len(",".join(merged)) > 480:  # YouTube caps tags at 500 characters
        merged.pop()
    th = (pack.get("thumbnails") or {}).get("variants") or []
    lines = pack["seo"]["first_lines"] + ("\n\n" + "\n".join(pack["seo"]["chapters"]) if pack["seo"]["chapters"] else "")
    prop = {"current_title": v["title"], "titles": pack.get("titles", []), "description_lines": lines,
            "tags": merged, "added_tags": [t for t in merged if t not in old_tags],
            "thumbnail": ({"file": th[0]["file"], "url": th[0]["url"], "headline": th[0]["headline"], "options": th}
                          if th else None),
            "keyword": pack["keyword"], "notes": pack["notes"], "format": v["format"],
            "keep_current": pack.get("keep_current"), "keep_reason": pack.get("keep_reason"),
            "thumbnail_text": pack.get("thumbnail_text"),
            "fills_missing_only": c["reason"] in ("missing", "new_upload")}
    # Prefer hook-style titles (question/curiosity) over keyword-first ones: clicks come from the hook.
    order = {"hybrid_search_plus_curiosity": 0, "hybrid": 0, "curiosity": 1, "search_driven": 2}
    fits = [t["title"] for t in sorted(pack.get("titles", []), key=lambda t: order.get(t.get("strategy"), 3))
            if len(t.get("title") or "") <= LONG_TITLE]
    too_long = len(v["title"] or "") > LONG_TITLE
    want_title = (repackage or (too_long and c.get("shorten"))) and not (pack.get("keep_current") and not too_long)
    chosen = {"title": (fits[0] if want_title and fits else None),
              "description": True, "tags": bool(prop["added_tags"]),
              "thumbnail": th[0]["file"] if th else None}
    return prop, chosen


def daily_run(conn, tenant_id, *, transport=None, runner=None, limit=None):
    if conn.execute("SELECT kind FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()[0] == "demo":
        return {"skipped": "demo brand: never written"}
    today_n = conn.execute("SELECT COUNT(*) FROM channel_changes WHERE tenant_id=? AND created_at>=?",
                           (tenant_id, date.today().isoformat())).fetchone()[0]
    made, applied, errors = [], [], []
    limit = limit or cap(conn, tenant_id)
    for c in candidates(conn, tenant_id)[:max(0, limit - today_n)]:
        try:
            prop, chosen = _proposal(conn, tenant_id, c, runner=runner)
        except Exception as e:  # one video must not stop the run
            errors.append(f"{c['v']['asset_id']}: {str(e)[:120]}")
            continue
        cid = new_id("chg_")
        conn.execute("""INSERT INTO channel_changes (id, tenant_id, asset_id, reason, evidence_json, proposal_json,
                        chosen_json, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                     (cid, tenant_id, c["v"]["asset_id"], c["reason"], json.dumps(c["evidence"]), json.dumps(prop),
                      json.dumps(chosen), utcnow()))
        made.append(cid)
    m, ws = mode(conn, tenant_id), write_status(conn, tenant_id)
    if m != "approve" and ws["has_write"]:
        waiting = [r[0] for r in conn.execute("SELECT id FROM channel_changes WHERE tenant_id=? AND status='proposed' "
                                              "ORDER BY created_at", (tenant_id,))]
        for cid in waiting:  # includes drafts made before auto mode / write access was switched on
            prop = json.loads(conn.execute("SELECT proposal_json FROM channel_changes WHERE id=?", (cid,)).fetchone()[0])
            if m == "auto_all" or prop["fills_missing_only"]:
                try:
                    decide(conn, tenant_id, cid, "approve", actor=f"autopilot:{m}", auto=True)
                    applied.append(apply(conn, tenant_id, cid, transport=transport, actor=f"autopilot:{m}"))
                except Exception as e:
                    errors.append(f"{cid}: {str(e)[:160]}")
    drift = check_drift(conn, tenant_id)
    return {"proposed": len(made), "auto_applied": len(applied), "mode": m, "write_access": ws["has_write"],
            "overridden_since": drift, "errors": errors}


def redraft(conn, tenant_id, cid, runner=None):
    """Rebuild a waiting draft with the current data and drafting rules."""
    r = conn.execute("SELECT * FROM channel_changes WHERE id=? AND tenant_id=?", (cid, tenant_id)).fetchone()
    if not r:
        raise LookupError("change not found")
    if r["status"] not in OPEN:
        raise ValueError(f"change is already {r['status']}")
    v = next((x for x in analytics.videos(conn, tenant_id) if x["asset_id"] == r["asset_id"]), None)
    if not v:
        raise LookupError("video not found")
    winner = (analytics.peer_stats(analytics.videos(conn, tenant_id), v)["metrics"].get("views_per_day") or {}).get("percentile") or 0
    prop, chosen = _proposal(conn, tenant_id, {"v": v, "reason": r["reason"],
                                               "shorten": len(v["title"] or "") > LONG_TITLE and winner < 75}, runner=runner)
    conn.execute("UPDATE channel_changes SET proposal_json=?, chosen_json=?, status='proposed' WHERE id=?",
                 (json.dumps(prop), json.dumps(chosen), cid))
    return {"id": cid, "status": "proposed"}


def decide(conn, tenant_id, cid, action, *, chosen=None, actor="owner", auto=False):
    r = conn.execute("SELECT * FROM channel_changes WHERE id=? AND tenant_id=?", (cid, tenant_id)).fetchone()
    if not r:
        raise LookupError("change not found")
    if r["status"] not in OPEN:
        raise ValueError(f"change is already {r['status']}")
    if action == "skip":
        conn.execute("UPDATE channel_changes SET status='skipped', decided_at=? WHERE id=?", (utcnow(), cid))
    elif action == "approve":
        ch = json.loads(r["chosen_json"] or "{}")
        if chosen:
            for k in ("title", "description", "tags", "thumbnail"):
                if k in chosen:
                    ch[k] = chosen[k]
            if ch.get("title") is not None:
                ch["title"] = str(ch["title"]).strip()[:100] or None
        conn.execute("UPDATE channel_changes SET status='approved', chosen_json=?, decided_at=?, auto=? WHERE id=?",
                     (json.dumps(ch), utcnow(), 1 if auto else 0, cid))
    else:
        raise ValueError("action must be approve or skip")
    audit(conn, tenant_id, actor, f"autopilot.{action}", {"change": cid, "asset": r["asset_id"]})
    return {"id": cid, "status": "skipped" if action == "skip" else "approved"}


# ── writing to YouTube ────────────────────────────────────────────────

def _session(conn, tenant_id, transport=None):
    a = _account(conn, tenant_id)
    if not a:
        raise AutopilotError("no YouTube channel connected")
    client = vault.load_client("youtube")
    http = Client(conn, tenant_id, transport=transport)

    def call(method, url, **kw):
        for attempt in (0, 1):
            tok = youtube._access_token(http, conn, tenant_id, a["credential_id"], client, force=attempt == 1)
            try:
                return http.request(method, url, headers={"Authorization": f"Bearer {tok}"}, **kw)
            except HttpError as e:
                if e.status == 401 and attempt == 0:
                    continue
                raise
    return a, http, call


def _snippet(call, video_id, quota=1):
    items = call("GET", f"{youtube.DATA_API}/videos", params={"part": "snippet", "id": video_id}, quota_units=quota).get("items", [])
    if not items:
        raise AutopilotError("video not found on YouTube")
    return items[0]["snippet"]


def _thumb_error(e):
    body = json.dumps(e.body)[:300] if isinstance(e, HttpError) else str(e)
    if isinstance(e, HttpError) and e.status == 403:
        return ("YouTube refused the custom thumbnail. The channel may need phone verification: YouTube Studio → "
                "Settings → Channel → Feature eligibility. " + body[:120])
    return body


def apply(conn, tenant_id, cid, *, transport=None, actor="owner"):
    r = conn.execute("SELECT * FROM channel_changes WHERE id=? AND tenant_id=?", (cid, tenant_id)).fetchone()
    if not r:
        raise LookupError("change not found")
    if r["status"] != "approved":
        raise ValueError("approve the change first")
    a, http, call = _session(conn, tenant_id, transport)
    brands.preflight_public_action(conn, tenant_id=tenant_id, platform="youtube", platform_account_id=a["platform_account_id"],
                                   required_permission="WRITE_METADATA",
                                   approval={"approved_by": actor, "approval_timestamp": r["decided_at"] or utcnow(),
                                             "tenant_id": tenant_id, "platform_account_id": a["platform_account_id"]})
    prop, ch = json.loads(r["proposal_json"]), json.loads(r["chosen_json"] or "{}")
    vid = r["asset_id"]
    try:
        sn = _snippet(call, vid)
        if sn.get("channelId") != a["platform_account_id"]:
            raise AutopilotError("video belongs to a different channel; refusing")
        before = {k: sn[k] for k in SNIPPET_KEYS if k in sn}
        # Save the live thumbnail for undo.
        rb = DATA_DIR / "rollback" / tenant_id
        rb.mkdir(parents=True, exist_ok=True)
        turl = next((sn.get("thumbnails", {}).get(k, {}).get("url") for k in ("maxres", "standard", "high")
                     if sn.get("thumbnails", {}).get(k)), None)
        if ch.get("thumbnail") and turl:
            (rb / f"{vid}-{cid}.jpg").write_bytes(http.download(turl, log_name="youtube.thumbnail.backup"))
            before["_thumbnail_backup"] = f"{vid}-{cid}.jpg"
        conn.execute("UPDATE channel_changes SET before_json=? WHERE id=?", (json.dumps(before), cid))
        new = {k: v for k, v in before.items() if not k.startswith("_")}
        if ch.get("title"):
            new["title"] = ch["title"]
        if ch.get("description"):
            first = prop["description_lines"].split("\n")[0].strip()
            old = before.get("description", "")
            if ch.get("only_if_empty") and len(old.strip()) >= 40:
                pass  # someone added a description since our last sync: leave it alone
            elif first and first not in old:
                new["description"] = (prop["description_lines"] + ("\n\n" + old if old.strip() else ""))[:4900]
        if ch.get("tags") and ch.get("only_if_empty") and before.get("tags"):
            pass  # tags were added since our last sync: leave them alone
        elif ch.get("tags"):  # merge with the LIVE tags (they may have changed since the last sync)
            tags = list(dict.fromkeys(list(before.get("tags", [])) + prop["tags"]))
            while len(",".join(tags)) > 480:
                tags.pop()
            new["tags"] = tags
        changed = [k for k in ("title", "description", "tags") if new.get(k) != before.get(k)]
        if changed:
            call("PUT", f"{youtube.DATA_API}/videos", params={"part": "snippet"},
                 json_body={"id": vid, "snippet": new}, quota_units=50, log_name="youtube.videos.update")
        thumb_err = None
        if False and ch.get("thumbnail"):  # thumbnails are off by owner rule; older drafts can't change them either
            p = DATA_DIR / "previews" / tenant_id / vid / ch["thumbnail"]
            try:
                call("POST", UPLOAD_URL, params={"videoId": vid, "uploadType": "media"}, data=p.read_bytes(),
                     content_type="image/jpeg", quota_units=50, log_name="youtube.thumbnails.set")
                changed.append("thumbnail")
            except (HttpError, OSError) as e:
                thumb_err = _thumb_error(e)
        def norm(k, x):  # YouTube trims/normalises: compare the meaning, not the bytes
            if k == "tags":
                return sorted({str(t).strip().lower() for t in (x or [])})
            return " ".join(str(x or "").split())
        mismatch = []
        for wait in (0, 3, 8):  # YouTube can take a few seconds to show the update
            if wait:
                import time
                time.sleep(wait)
            after = _snippet(call, vid)  # read-back
            mismatch = [k for k in ("title", "description", "tags") if k in changed and norm(k, after.get(k)) != norm(k, new.get(k))]
            if not mismatch:
                break
        status = "failed" if mismatch else ("partial" if thumb_err else "verified")
        err = (f"read-back mismatch on {', '.join(mismatch)}" if mismatch else "") + (thumb_err or "")
        now = utcnow()
        conn.execute("UPDATE channel_changes SET status=?, error=?, applied_at=?, verified_at=? WHERE id=?",
                     (status, err[:500], now, now if status != "failed" else None, cid))
        audit(conn, tenant_id, actor, "autopilot.apply", {"change": cid, "asset": vid, "changed": changed, "status": status})
        return {"id": cid, "status": status, "changed": changed, "error": err or None}
    except (HttpError, AutopilotError, youtube.ConnectorError) as e:
        msg = json.dumps(e.body)[:400] if isinstance(e, HttpError) else str(e)
        conn.execute("UPDATE channel_changes SET status='failed', error=?, applied_at=? WHERE id=?", (msg, utcnow(), cid))
        audit(conn, tenant_id, actor, "autopilot.failed", {"change": cid, "asset": vid, "error": msg[:200]})
        raise AutopilotError(msg) from None


def rollback(conn, tenant_id, cid, *, transport=None, actor="owner"):
    r = conn.execute("SELECT * FROM channel_changes WHERE id=? AND tenant_id=?", (cid, tenant_id)).fetchone()
    if not r:
        raise LookupError("change not found")
    if r["status"] not in ("verified", "partial", "failed"):
        raise ValueError(f"nothing to undo ({r['status']})")
    before = json.loads(r["before_json"] or "{}")
    if not before.get("title"):
        raise ValueError("no saved original for this change")
    a, http, call = _session(conn, tenant_id, transport)
    brands.preflight_public_action(conn, tenant_id=tenant_id, platform="youtube", platform_account_id=a["platform_account_id"],
                                   required_permission="WRITE_METADATA",
                                   approval={"approved_by": actor, "approval_timestamp": utcnow(), "tenant_id": tenant_id,
                                             "platform_account_id": a["platform_account_id"]})
    call("PUT", f"{youtube.DATA_API}/videos", params={"part": "snippet"},
         json_body={"id": r["asset_id"], "snippet": {k: v for k, v in before.items() if not k.startswith("_")}},
         quota_units=50, log_name="youtube.videos.update")
    note = ""
    if before.get("_thumbnail_backup"):
        p = DATA_DIR / "rollback" / tenant_id / before["_thumbnail_backup"]
        try:
            call("POST", UPLOAD_URL, params={"videoId": r["asset_id"], "uploadType": "media"}, data=p.read_bytes(),
                 content_type="image/jpeg", quota_units=50, log_name="youtube.thumbnails.set")
        except (HttpError, OSError) as e:
            note = "Title/description restored; thumbnail restore failed: " + _thumb_error(e)
    conn.execute("UPDATE channel_changes SET status='rolled_back', rolled_back_at=?, error=? WHERE id=?",
                 (utcnow(), note[:500], cid))
    audit(conn, tenant_id, actor, "autopilot.rollback", {"change": cid, "asset": r["asset_id"]})
    return {"id": cid, "status": "rolled_back", "note": note or None}


def check_drift(conn, tenant_id):
    """Count our applied titles that were changed again afterwards (by a person or another tool). We don't fight it."""
    n = 0
    for r in conn.execute("SELECT * FROM channel_changes WHERE tenant_id=? AND status IN ('verified','partial') "
                          "AND applied_at>=?", (tenant_id, (date.today() - timedelta(days=30)).isoformat())):
        ch = json.loads(r["chosen_json"] or "{}")
        live = conn.execute("SELECT value, observed_at FROM asset_history WHERE tenant_id=? AND asset_id=? AND field='title' "
                            "ORDER BY observed_at DESC LIMIT 1", (tenant_id, r["asset_id"])).fetchone()
        if ch.get("title") and live and live["observed_at"] > r["applied_at"] and live["value"] != ch["title"]:
            conn.execute("UPDATE channel_changes SET status='overridden', error=? WHERE id=?",
                         (f"Changed again after us to “{live['value'][:80]}” — left as is.", r["id"]))
            n += 1
    return n


def page(conn, tenant_id):
    rows = [dict(r) for r in conn.execute("SELECT * FROM channel_changes WHERE tenant_id=? ORDER BY created_at DESC LIMIT 80",
                                          (tenant_id,))]
    titles = {r[0]: r[1] for r in conn.execute("SELECT asset_id, title FROM assets WHERE tenant_id=?", (tenant_id,))}
    for r in rows:
        for k in ("evidence", "proposal", "chosen", "before"):
            r[k] = json.loads(r.pop(f"{k}_json") or "{}")
        r["video_title"] = titles.get(r["asset_id"])
        r["current_thumb"] = f"/thumb/{tenant_id}/{r['asset_id']}.jpg"
    return {"mode": mode(conn, tenant_id), "modes": MODES, "write": write_status(conn, tenant_id),
            "daily_cap": cap(conn, tenant_id), "cap_choices": CAP_CHOICES, "cooldown_days": COOLDOWN_DAYS,
            "title_max": LONG_TITLE,
            "pending": [r for r in rows if r["status"] in OPEN],
            "done": [r for r in rows if r["status"] not in OPEN],
            "hosts_available": [p.stem for p in prep.thumbs.host_photos()],
            "rules": ["Winners (top quarter by views/day) keep their title and thumbnail.",
                      f"At most {cap(conn, tenant_id)} new changes a day and one change per video every {COOLDOWN_DAYS} days.",
                      f"New titles stay under {LONG_TITLE} characters so they aren't cut off.",
                      "Descriptions keep your existing text underneath the new first lines.",
                      "Thumbnails are never changed (owner rule): only titles, descriptions and tags.",
                      "Every change saves the original first; Undo restores it.",
                      "If someone else changes a video after us, it is logged and left alone."]}


# ── One-off owner-approved batch: fill missing descriptions and tags ──

def fill_missing(conn, tenant_id, *, actor="owner", transport=None, runner=None, progress=lambda p, m: None, limit=None):
    """Add descriptions where there are none and tags where there are none, highest search views first.
    Never touches titles or thumbnails. Each change is checked live first, applied, read back, and has Undo."""
    vids = analytics.videos(conn, tenant_id)
    search = {r[0]: r[1] for r in conn.execute("SELECT asset_id, value FROM metrics WHERE tenant_id=? AND grain='traffic_source' "
                                               "AND period_start='YT_SEARCH'", (tenant_id,))}
    todo = []
    for v in vids:
        a = v["asset_id"]
        if (_latest(conn, tenant_id, a, "privacy") or "public") != "public":
            continue
        no_desc = len((_latest(conn, tenant_id, a, "description") or "").strip()) < 40
        no_tags = json.loads(_latest(conn, tenant_id, a, "tags") or "[]") == []
        if no_desc or no_tags:
            todo.append((search.get(a, 0), v.get("metrics", {}).get("views") or 0, v, no_desc, no_tags))
    todo.sort(key=lambda x: (-x[0], -x[1]))
    if limit:
        todo = todo[:limit]
    done = {"descriptions": 0, "tags": 0, "verified": 0, "failed": [], "skipped_live": 0, "order": []}
    for i, (sv, _, v, no_desc, no_tags) in enumerate(todo):
        a = v["asset_id"]
        progress(int(100 * i / max(len(todo), 1)), f"{i + 1}/{len(todo)} {v['title'][:40]}")
        for r in conn.execute("SELECT id FROM channel_changes WHERE tenant_id=? AND asset_id=? AND status IN ('proposed','approved')",
                              (tenant_id, a)).fetchall():  # this batch replaces older drafts for the same video
            conn.execute("UPDATE channel_changes SET status='skipped', error='superseded by the fill-missing batch' WHERE id=?",
                         (r["id"],))
        try:
            pack = prep.asset_pack(conn, tenant_id, a, runner=runner, thumbnails_wanted=False, skip_titles=True)
            if pack.get("seo_source") != "ai":  # never publish thin rule-based text in this batch
                done["failed"].append(f"{v['title'][:40]}: AI draft unavailable ({'; '.join(pack['notes'])[:120]}) — stopped")
                break
            old_tags = json.loads(_latest(conn, tenant_id, a, "tags") or "[]")
            lines = pack["seo"]["first_lines"] + ("\n\n" + "\n".join(pack["seo"]["chapters"]) if pack["seo"]["chapters"] else "")
            prop = {"current_title": v["title"], "titles": [], "description_lines": lines,
                    "tags": list(dict.fromkeys(old_tags + pack["seo"]["tags"])), "added_tags": pack["seo"]["tags"],
                    "thumbnail": None, "keyword": pack["keyword"], "notes": pack["notes"], "format": v["format"],
                    "fills_missing_only": True, "search_views": int(sv)}
            chosen = {"title": None, "description": no_desc, "only_if_empty": True, "tags": no_tags, "thumbnail": None}
            cid = new_id("chg_")
            conn.execute("""INSERT INTO channel_changes (id, tenant_id, asset_id, reason, evidence_json, proposal_json,
                            chosen_json, status, decided_at, created_at) VALUES (?,?,?,?,?,?,?,'approved',?,?)""",
                         (cid, tenant_id, a, "missing", json.dumps([f"Missing: {', '.join(k for k, b in (('description', no_desc), ('tags', no_tags)) if b)}",
                                                                   f"{int(sv)} views from YouTube search"]),
                          json.dumps(prop), json.dumps(chosen), utcnow(), utcnow()))
            audit(conn, tenant_id, actor, "autopilot.approve", {"change": cid, "asset": a, "batch": "fill_missing"})
            r = apply(conn, tenant_id, cid, transport=transport, actor=actor)
            done["descriptions"] += "description" in r["changed"]
            done["tags"] += "tags" in r["changed"]
            done["verified"] += r["status"] == "verified"
            if no_desc and "description" not in r["changed"]:
                done["skipped_live"] += 1
            done["order"].append({"title": v["title"][:60], "search_views": int(sv), "changed": r["changed"], "status": r["status"]})
        except Exception as e:  # keep going; report every failure
            done["failed"].append(f"{v['title'][:40]}: {str(e)[:160]}")
    progress(100, "done")
    return done


def clean_batch_tags(conn, tenant_id, *, since, actor="owner", transport=None, runner=None, progress=lambda p, m: None):
    """Replace tags we added in a fill-missing batch with the clean (relevance-checked) set. Logged as 'tag_cleanup'."""
    rows = conn.execute("""SELECT * FROM channel_changes WHERE tenant_id=? AND reason='missing' AND created_at>=?
                           AND status IN ('verified','failed') ORDER BY created_at""", (tenant_id, since)).fetchall()
    a, http, call = _session(conn, tenant_id, transport)
    brands.preflight_public_action(conn, tenant_id=tenant_id, platform="youtube", platform_account_id=a["platform_account_id"],
                                   required_permission="WRITE_METADATA",
                                   approval={"approved_by": actor, "approval_timestamp": utcnow(), "tenant_id": tenant_id,
                                             "platform_account_id": a["platform_account_id"]})
    out = {"cleaned": 0, "unchanged": 0, "failed": [], "removed": {}}
    for i, r in enumerate(rows):
        progress(int(100 * i / max(len(rows), 1)), f"cleaning tags {i + 1}/{len(rows)}")
        vid, prop = r["asset_id"], json.loads(r["proposal_json"])
        before_batch = json.loads(r["before_json"] or "{}").get("tags", [])
        try:
            pack = prep.asset_pack(conn, tenant_id, vid, runner=runner, skip_titles=True, thumbnails_wanted=False)
            if pack.get("seo_source") != "ai":
                out["failed"].append(f"{vid}: AI tags unavailable, left as is")
                continue
            sn = _snippet(call, vid)
            if sn.get("channelId") != a["platform_account_id"]:
                raise AutopilotError("video belongs to a different channel; refusing")
            before = {k: sn[k] for k in SNIPPET_KEYS if k in sn}
            live = list(before.get("tags", []))
            ours = {t.lower() for t in prop.get("added_tags", [])}
            keep = [t for t in live if t.lower() not in ours or t in before_batch]  # tags someone else added stay
            tags = list(dict.fromkeys(keep + pack["seo"]["tags"]))
            while len(",".join(tags)) > 480:
                tags.pop()
            if sorted(t.lower() for t in tags) == sorted(t.lower() for t in live):
                out["unchanged"] += 1
                continue
            cid = new_id("chg")
            conn.execute("""INSERT INTO channel_changes (id, tenant_id, asset_id, reason, evidence_json, proposal_json, chosen_json,
                            before_json, status, auto, created_at, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (cid, tenant_id, vid, "tag_cleanup",
                          json.dumps([f"Removed unrelated search-term tags added on {since[:10]}"]),
                          json.dumps({"title": before.get("title"), "tags": tags, "added_tags": tags, "description_lines": ""}),
                          json.dumps({"tags": True}), json.dumps(before), "approved", 0, utcnow(), utcnow()))
            new = dict(before, tags=tags)
            call("PUT", f"{youtube.DATA_API}/videos", params={"part": "snippet"}, json_body={"id": vid, "snippet": new},
                 quota_units=50, log_name="youtube.videos.update")
            now = utcnow()
            conn.execute("UPDATE channel_changes SET status='verified', applied_at=?, verified_at=? WHERE id=?", (now, now, cid))
            out["removed"][before.get("title", vid)[:50]] = [t for t in live if t not in tags]
            out["cleaned"] += 1
            audit(conn, tenant_id, actor, "autopilot.tag_cleanup", {"change": cid, "asset": vid})
        except (HttpError, AutopilotError, youtube.ConnectorError, ValueError, KeyError) as e:
            out["failed"].append(f"{vid}: {str(e)[:120]}")
    return out
