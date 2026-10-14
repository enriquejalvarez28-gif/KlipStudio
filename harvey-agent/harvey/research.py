"""Lead research records: evidence-backed business research, reviewed by a human.

Records arrive as JSON (from Harvey's research runs or a researcher) in the
shape documented in knowledge/klip-sales-strategy.md. Every fact is an
object {"value", "status": VERIFIED|INFERRED|UNKNOWN, "source"}; only
VERIFIED values reach the flat columns used for listing and outreach.

Deterministic: dedup, scoring, eligibility and history need no model.
"""

import json
import re
from datetime import datetime, timezone

STATUSES = ("VERIFIED", "INFERRED", "UNKNOWN")
PRIORITY_POINTS = {"high": 3, "medium": 2, "low": 1}


def _norm_domain(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0]
    return url[4:] if url.startswith("www.") else url


def record_key(rec: dict) -> str:
    """Dedup identity: website domain, else name + city."""
    domain = _norm_domain(verified(rec.get("website")))
    if domain:
        return "d:" + domain
    name = re.sub(r"[^a-z0-9]+", "", (rec.get("business_name") or "").lower())
    city = re.sub(r"[^a-z0-9]+", "", (rec.get("city") or "").lower())
    return f"n:{name}:{city}"


def verified(field) -> str:
    """The value of a fact only if it is VERIFIED."""
    if isinstance(field, dict):
        if str(field.get("status", "")).upper() == "VERIFIED":
            return str(field.get("value") or "").strip()
        return ""
    return ""


def validate(rec: dict) -> list[str]:
    """Problems that make a record unusable (empty list = fine)."""
    problems = []
    if not (rec.get("business_name") or "").strip():
        problems.append("missing business_name")
    if rec.get("qualified") and not verified(rec.get("website")) and not verified(rec.get("phone")):
        problems.append("business identity not verified (no verified website or phone)")
    for key in ("website", "phone", "email", "address", "decision_maker"):
        f = rec.get(key)
        if isinstance(f, dict):
            st = str(f.get("status", "")).upper()
            if st and st not in STATUSES:
                problems.append(f"{key}: bad status {st}")
            if st == "VERIFIED" and not f.get("source"):
                problems.append(f"{key}: VERIFIED without a source")
    email = verified(rec.get("email"))
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", email, re.I):
        problems.append(f"email looks invalid: {email}")
    if rec.get("qualified") and not (rec.get("recommended_service") and rec.get("outreach_angle")):
        problems.append("qualified without a recommended service and outreach angle")
    return problems


def score(rec: dict) -> int:
    """Simple 0-10 qualification score: priority + reachability + evidence."""
    pts = PRIORITY_POINTS.get(str(rec.get("priority", "")).lower(), 0) * 2   # 0-6
    if verified(rec.get("email")):
        pts += 2
    elif verified(rec.get("phone")):
        pts += 1
    evidence = sum(1 for o in rec.get("observations") or []
                   if str(o.get("status", "")).upper() == "VERIFIED")
    pts += min(evidence, 2)
    return min(pts, 10) if rec.get("qualified") else 0


async def import_records(state, records: list[dict]) -> dict:
    """Upsert research records (+ a Harvey company row). Returns counts."""
    from harvey.models.company import Company

    out = {"inserted": 0, "updated": 0, "rejected": 0, "problems": {}}
    now = datetime.now(timezone.utc).isoformat()
    for rec in records:
        problems = validate(rec)
        name = (rec.get("business_name") or "?").strip()
        if problems:
            out["rejected"] += 1
            out["problems"][name] = problems
            continue
        key = record_key(rec)
        website = verified(rec.get("website"))
        phone = verified(rec.get("phone"))
        email = verified(rec.get("email"))
        company_id = await state.add_company(Company(
            name=name, domain=_norm_domain(website), website=website, phone=phone,
            industry=rec.get("industry", ""), location=rec.get("city", ""),
            source="lead_research", external_id="" if website else key,
        ))
        cols = {
            "company_id": company_id, "business_name": name,
            "industry": rec.get("industry", ""), "specialty": rec.get("specialty", ""),
            "city": rec.get("city", ""), "website": website, "phone": phone,
            "email": email, "email_status": "found_public" if email else "unknown",
            "opportunity": rec.get("opportunity", ""),
            "recommended_service": rec.get("recommended_service", ""),
            "outreach_angle": rec.get("outreach_angle", ""),
            "priority": str(rec.get("priority", "medium")).lower(),
            "score": score(rec), "qualified": 1 if rec.get("qualified") else 0,
            "skip_reason": rec.get("skip_reason", ""),
            # Eligible = qualified + a verified address. Still needs mailbox
            # verification and GoHighLevel's check before any send.
            "outreach_eligible": 1 if rec.get("qualified") and email else 0,
            "draft_subject": (rec.get("draft") or {}).get("subject", ""),
            "draft_body": (rec.get("draft") or {}).get("body", ""),
            "record_json": json.dumps(rec), "researched_at": rec.get("researched_at") or now,
        }
        if cols["draft_body"]:
            cols["draft_status"] = "drafted"
        existing = await state.get_research_record(key)
        if existing:
            history = json.loads(existing.get("history_json") or "[]")
            history.append({"at": existing["updated_at"], "record": json.loads(existing["record_json"])})
            cols["history_json"] = json.dumps(history[-5:])
            await state.update_research_record(key, cols)
            out["updated"] += 1
        else:
            await state.insert_research_record(key, cols)
            out["inserted"] += 1
    return out
