"""GoHighLevel bridge: who owns a lead, and keeping both systems in step.

Ownership rule: before a genuine reply, Harvey owns cold outreach. After a
reply, GoHighLevel owns the relationship and Harvey only reports into it.

Everything here is deterministic (HTTP + rules). No model calls.

  precheck()        before every cold send: is this person already in a
                    relationship, suppressed, or unknown because GHL is down?
  queue_outbound()  after a send: contact + note in GHL (idempotent)
  queue_handoff()   after a reply: tags, research summary, email history,
                    task, opportunity; GHL workflows trigger on the tags
  queue_opt_out()   DND + tag in GHL
  drain()           runs the queue, retrying failures every cycle
  apply_webhook()   GHL -> Harvey: meeting booked, client, DND, stage moves

Writes to GHL never trigger writes back from Harvey (webhooks only change
local state), so the two systems can't loop.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger("harvey.crm")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_VERSION = "2021-07-28"

# Prospect statuses that mean "cold outreach is over for this person".
HANDED_OFF = "handed_off"
CLIENT = "client"
SUPPRESSED = "suppressed"
OPTED_OUT = "opted_out"
MEETING = "meeting"

# Webhook event -> local prospect status. Every one of these stops outreach.
WEBHOOK_STATUS = {
    "opt_out": OPTED_OUT,
    "dnd": OPTED_OUT,
    "meeting_booked": MEETING,
    "appointment_booked": MEETING,
    "client": CLIENT,
    "won": CLIENT,
    "contacted": HANDED_OFF,
    "call_logged": HANDED_OFF,
    "stage_changed": HANDED_OFF,
    "proposal_sent": HANDED_OFF,
    "lost": SUPPRESSED,
}
# More restrictive wins when both systems disagree.
STATUS_RANK = {OPTED_OUT: 5, CLIENT: 4, MEETING: 3, SUPPRESSED: 3, HANDED_OFF: 2,
               "replied": 1, "lost": 1}


class CRMError(Exception):
    """GHL could not be reached or rejected the call."""


@dataclass
class Precheck:
    allowed: bool
    reason: str = ""
    contact_id: str = ""
    # True when GHL couldn't answer: hold and retry, don't suppress.
    transient: bool = False


class GHLClient:
    """Thin GoHighLevel API v2 client (Private Integration token)."""

    def __init__(self, token: str, location_id: str, transport=None, timeout: float = 20):
        self.token = token
        self.location_id = location_id
        self._transport = transport
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token and self.location_id)

    async def _request(self, method: str, path: str, **kw) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Version": GHL_VERSION,
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                base_url=GHL_BASE, timeout=self._timeout, transport=self._transport
            ) as c:
                r = await c.request(method, path, headers=headers, **kw)
        except httpx.HTTPError as e:
            raise CRMError(f"{method} {path}: {e}") from e
        if r.status_code >= 400:
            raise CRMError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.content else {}

    async def find_contact(self, email: str) -> dict | None:
        data = await self._request(
            "GET", "/contacts/search/duplicate",
            params={"locationId": self.location_id, "email": email},
        )
        contact = data.get("contact")
        if contact and contact.get("id"):
            full = await self._request("GET", f"/contacts/{contact['id']}")
            return full.get("contact") or contact
        return None

    async def opportunities(self, contact_id: str) -> list:
        """All of a contact's opportunities (any status)."""
        data = await self._request(
            "GET", "/opportunities/search",
            params={"location_id": self.location_id, "contact_id": contact_id},
        )
        return data.get("opportunities") or []

    async def open_opportunities(self, contact_id: str) -> list:
        data = await self._request(
            "GET", "/opportunities/search",
            params={"location_id": self.location_id, "contact_id": contact_id,
                    "status": "open"},
        )
        return data.get("opportunities") or []

    async def upsert_contact(self, fields: dict) -> str:
        data = await self._request(
            "POST", "/contacts/upsert",
            json={"locationId": self.location_id, **fields},
        )
        cid = (data.get("contact") or {}).get("id", "")
        if not cid:
            raise CRMError("upsert returned no contact id")
        return cid

    async def add_tags(self, contact_id: str, tags: list[str]):
        await self._request("POST", f"/contacts/{contact_id}/tags", json={"tags": tags})

    async def add_note(self, contact_id: str, body: str):
        await self._request("POST", f"/contacts/{contact_id}/notes", json={"body": body})

    async def create_task(self, contact_id: str, title: str, body: str,
                          due: datetime, assigned_to: str = ""):
        payload = {"title": title, "body": body, "completed": False,
                   "dueDate": due.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if assigned_to:
            payload["assignedTo"] = assigned_to
        await self._request("POST", f"/contacts/{contact_id}/tasks", json=payload)

    async def set_dnd(self, contact_id: str):
        await self._request("PUT", f"/contacts/{contact_id}", json={
            "dnd": True,
            "dndSettings": {"Email": {"status": "active",
                                      "message": "Opted out via cold email reply"}},
        })

    async def create_pipeline(self, name: str, stages: list[str]) -> str:
        data = await self._request("POST", "/opportunities/pipelines", json={
            "locationId": self.location_id, "name": name,
            "stages": [{"name": st, "position": i} for i, st in enumerate(stages)],
        })
        return (data.get("pipeline") or data).get("id", "")

    async def pipelines(self) -> list:
        data = await self._request(
            "GET", "/opportunities/pipelines", params={"locationId": self.location_id}
        )
        return data.get("pipelines") or []

    async def create_opportunity(self, contact_id: str, name: str, pipeline_id: str,
                                 stage_id: str, assigned_to: str = "") -> str:
        payload = {"locationId": self.location_id, "contactId": contact_id,
                   "name": name, "pipelineId": pipeline_id,
                   "pipelineStageId": stage_id, "status": "open"}
        if assigned_to:
            payload["assignedTo"] = assigned_to
        data = await self._request("POST", "/opportunities/", json=payload)
        return (data.get("opportunity") or {}).get("id", "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def contact_blocks_outreach(contact: dict, crm_cfg) -> str:
    """Why this existing GHL contact must not get cold email ('' = fine).

    A contact Harvey didn't create (no outreach tag) is someone Klip already
    knows: never cold-pitch them. A Harvey contact is fine for follow-ups
    until it replies, opts out, becomes a client or gets an opportunity.
    """
    tags = {str(t).strip().lower() for t in contact.get("tags") or []}
    if contact.get("dnd"):
        return "contact is DND in GoHighLevel"
    email_dnd = ((contact.get("dndSettings") or {}).get("Email") or {}).get("status")
    if email_dnd == "active":
        return "email DND active in GoHighLevel"
    hit = tags & {t.lower() for t in crm_cfg.suppression_tags}
    if hit:
        return f"suppression tag {sorted(hit)[0]!r} in GoHighLevel"
    if str(contact.get("type", "")).lower() == "customer":
        return "already a customer in GoHighLevel"
    if crm_cfg.tag_outreach.lower() not in tags:
        return "existing GoHighLevel contact (not created by Harvey)"
    if tags & {crm_cfg.tag_replied.lower(), crm_cfg.tag_handoff.lower()}:
        return "already handed off to GoHighLevel"
    return ""


class CRMBridge:
    def __init__(self, state, config, env, client: GHLClient | None = None):
        from harvey.config import CRMConfig

        self.state = state
        self.cfg = getattr(config, "crm", None) or CRMConfig()
        self.client = client or GHLClient(getattr(env, "ghl_api_token", ""),
                                          getattr(env, "ghl_location_id", ""))
        self.persona = getattr(config, "persona", None)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled)

    # ── Before a send ──

    async def precheck(self, prospect) -> Precheck:
        """Deterministic pre-send check. Errors block (fail safe)."""
        if not self.enabled:
            return Precheck(True)
        if not self.client.configured:
            return Precheck(False, "GoHighLevel enabled but GHL_API_TOKEN/GHL_LOCATION_ID missing",
                            transient=True)
        try:
            contact = await self.client.find_contact(prospect.email)
            if not contact:
                return Precheck(True)
            reason = contact_blocks_outreach(contact, self.cfg)
            if not reason and await self.client.open_opportunities(contact["id"]):
                reason = "has an open opportunity in GoHighLevel"
            return Precheck(not reason, reason, contact.get("id", ""))
        except CRMError as e:
            return Precheck(False, f"GoHighLevel check failed: {e}", transient=True)

    async def prepare_contact(self, prospect) -> str:
        """Create/update the GHL contact BEFORE the first send.

        GoHighLevel's Gmail two-way sync only attaches mail to contacts that
        already exist, so the contact must be there before the email leaves
        or the prospect's reply never shows up in Conversations.
        """
        if not self.enabled:
            return ""
        return await self._ensure_contact(prospect)

    async def outreach_blocked(self) -> str:
        """Hold new outreach while CRM syncs keep failing ('' = clear)."""
        if not self.enabled:
            return ""
        failed = await self.state.count_crm_sync("failed")
        if failed >= self.cfg.max_failed_syncs:
            return f"{failed} GoHighLevel sync(s) failing"
        return ""

    # ── Queueing (idempotent: the key is the dedup) ──

    async def queue_outbound(self, item: dict, prospect):
        if self.enabled:
            await self.state.enqueue_crm_sync(
                f"outbound:{item['id']}", "outbound", prospect.id, {"outbox_id": item["id"]}
            )

    async def queue_handoff(self, prospect, reply_text: str, intent: str, reply_meta: dict):
        if self.enabled:
            await self.state.enqueue_crm_sync(
                f"handoff:{prospect.id}", "handoff", prospect.id,
                {"reply": reply_text[:4000], "intent": intent,
                 "subject": (reply_meta or {}).get("subject", ""),
                 "received_at": _now().isoformat()},
            )

    async def queue_reply_logged(self, prospect, reply_text: str, key: str):
        """A later reply from a handed-off lead: just note it."""
        if self.enabled:
            await self.state.enqueue_crm_sync(
                f"reply:{key}", "reply", prospect.id, {"reply": reply_text[:4000]}
            )

    async def queue_opt_out(self, prospect):
        if self.enabled:
            await self.state.enqueue_crm_sync(f"optout:{prospect.id}", "opt_out", prospect.id, {})

    # ── Running the queue ──

    async def drain(self, limit: int = 50) -> tuple[int, int]:
        """Process pending/failed jobs. Returns (done, failed)."""
        if not self.enabled or not self.client.configured:
            return 0, 0
        done = failed = 0
        for job in await self.state.get_crm_sync_due(limit):
            try:
                cid = await self._run_job(job)
                await self.state.finish_crm_sync(job["id"], True, crm_contact_id=cid)
                done += 1
            except Exception as e:
                await self.state.finish_crm_sync(job["id"], False, str(e))
                failed += 1
                logger.error(f"CRM: {job['id']} failed (attempt {job['attempts'] + 1}): {e}")
        if done or failed:
            logger.info(f"CRM: synced {done}, failing {failed}.")
        return done, failed

    async def _run_job(self, job: dict) -> str:
        payload = json.loads(job.get("payload_json") or "{}")
        prospect = await self.state.get_prospect(job["prospect_id"])
        if prospect is None:
            raise CRMError("prospect missing")
        cid = await self._ensure_contact(prospect)
        kind = job["kind"]
        if kind == "outbound":
            await self._sync_outbound(cid, payload)
        elif kind == "handoff":
            await self._sync_handoff(cid, prospect, payload)
        elif kind == "reply":
            await self.client.add_note(cid, "Prospect replied again (Harvey saw it; "
                                            "GoHighLevel owns this lead):\n\n" + payload["reply"])
        elif kind == "opt_out":
            await self.client.set_dnd(cid)
            await self.client.add_tags(cid, [self.cfg.tag_opted_out])
            await self.client.add_note(cid, "Opted out by replying to Harvey's cold email. "
                                            "Do not contact.")
        else:
            raise CRMError(f"unknown job kind {kind}")
        return cid

    async def _ensure_contact(self, prospect) -> str:
        company = await self.state.get_company(prospect.company_id) if prospect.company_id else None
        fields = {
            "email": prospect.email,
            "firstName": prospect.first_name,
            "lastName": prospect.last_name,
            "companyName": prospect.company or (company.name if company else ""),
            "source": "Harvey cold outreach",
        }
        phone = prospect.phone or (company.phone if company else "")
        website = (company.website or company.domain) if company else ""
        if phone:
            fields["phone"] = phone
        if website:
            fields["website"] = website
        cid = await self.client.upsert_contact({k: v for k, v in fields.items() if v})
        await self.client.add_tags(cid, [self.cfg.tag_outreach])
        return cid

    async def _sync_outbound(self, cid: str, payload: dict):
        item = await self.state.get_outbox_item(payload["outbox_id"])
        if item is None:
            raise CRMError("outbox item missing")
        await self.client.add_note(cid, (
            f"Harvey sent cold email (step {item['step']}, campaign {item['campaign_id'] or '-'})\n"
            f"From: {getattr(self.persona, 'email', '')}\nTo: {item['to_email']}\n"
            f"Sent: {item['sent_at']} UTC\nSubject: {item['subject']}\n"
            f"Message-ID: {item['message_id']}\nThread: {item['thread_ref']}\n"
            f"Status: accepted by mail provider (not proof of inbox delivery)\n\n"
            f"{item['body']}"
        ))

    async def _research_summary(self, prospect) -> str:
        company = await self.state.get_company(prospect.company_id) if prospect.company_id else None
        fields = [
            ("Contact", f"{prospect.first_name} {prospect.last_name}".strip()),
            ("Title", prospect.title),
            ("Company", prospect.company or (company.name if company else "")),
            ("Industry", prospect.industry or (company.industry if company else "")),
            ("Phone", prospect.phone or (company.phone if company else "")),
            ("Website", (company.website or company.domain) if company else ""),
            ("Location", company.location if company else ""),
            ("Harvey score", f"{prospect.score}/10" if prospect.score else ""),
        ]
        lines = [f"{k}: {v}" for k, v in fields if v]
        if prospect.personalization_notes:
            lines += ["", "Research / opportunity:", prospect.personalization_notes[:1500]]
        return "\n".join(lines)

    async def _sync_handoff(self, cid: str, prospect, payload: dict):
        sent = await self.state.get_sent_outbox_for_prospect(prospect.id)
        history = "\n\n".join(
            f"[{s['sent_at']}] Harvey -> {s['to_email']}: {s['subject']}\n{s['body']}" for s in sent
        )
        summary = await self._research_summary(prospect)
        intent = payload.get("intent", "")
        await self.client.add_note(cid, (
            f"HANDOFF FROM HARVEY: prospect replied ({intent}). Harvey has stopped all "
            f"cold follow-ups; GoHighLevel owns this lead now.\n\n"
            f"Their reply ({payload.get('received_at', '')}):\n{payload.get('reply', '')}\n\n"
            f"{summary}\n\nEmail history:\n{history or '(none recorded)'}\n\n"
            f"Suggested opener for a call: reference their reply above and the "
            f"opportunity Harvey noted; offer a 15-minute call."
        ))
        due = _now() + timedelta(hours=self.cfg.task_due_hours)
        await self.client.create_task(
            cid, f"Reply from {prospect.first_name or prospect.email}: follow up",
            f"Harvey handoff ({intent}). Read the handoff note and reply in Conversations.",
            due, self.cfg.assigned_user_id,
        )
        if intent in self.cfg.opportunity_intents:
            await self._maybe_opportunity(cid, prospect)
        # Tags last: GHL workflows fire on them, so everything they show
        # (note, task, opportunity) must already be there.
        await self.client.add_tags(cid, [self.cfg.tag_replied, self.cfg.tag_handoff])

    async def _maybe_opportunity(self, cid: str, prospect):
        if await self.client.open_opportunities(cid):
            return
        pipeline = next((p for p in await self.client.pipelines()
                         if p.get("name", "").strip().lower() == self.cfg.pipeline_name.lower()),
                        None)
        if not pipeline:
            logger.warning(f"CRM: pipeline '{self.cfg.pipeline_name}' not found; "
                           "skipping opportunity (create it in GoHighLevel).")
            return
        stage = next((s for s in pipeline.get("stages") or []
                      if s.get("name", "").strip().lower() == self.cfg.engaged_stage_name.lower()),
                     None)
        if not stage:
            logger.warning(f"CRM: stage '{self.cfg.engaged_stage_name}' not found.")
            return
        name = f"{prospect.company or prospect.email} (Harvey)"
        await self.client.create_opportunity(cid, name, pipeline["id"], stage["id"],
                                             self.cfg.assigned_user_id)

    # ── GHL -> Harvey ──

    async def poll_status(self, limit: int = 25) -> int:
        """Pull GoHighLevel's view of Harvey's active leads (no webhooks needed).

        For running on a laptop with no public URL: each cycle, look up a
        few contacted / handed-off prospects and apply the stricter status.
        Read-only against GHL. Returns how many prospects changed.
        """
        if not self.enabled or not self.client.configured:
            return 0
        changed = 0
        candidates = []
        for st in ("contacted", "queued", HANDED_OFF, "replied", MEETING):
            candidates += await self.state.get_prospects_by_status(st)
        for prospect in candidates[:limit]:
            try:
                contact = await self.client.find_contact(prospect.email)
                if not contact:
                    continue
                event = self._event_from_contact(contact, await self.client.opportunities(contact["id"]))
            except CRMError as e:
                logger.warning(f"CRM poll stopped: {e}")
                break
            if event:
                res = await self.apply_webhook({"event": event, "email": prospect.email,
                                                "event_id": f"poll:{prospect.id}:{event}"})
                changed += 1 if res.get("matched") else 0
        return changed

    def _event_from_contact(self, contact: dict, opps: list) -> str:
        tags = {str(t).lower() for t in contact.get("tags") or []}
        email_dnd = ((contact.get("dndSettings") or {}).get("Email") or {}).get("status")
        if contact.get("dnd") or email_dnd == "active" or self.cfg.tag_opted_out in tags \
                or "do-not-contact" in tags:
            return "opt_out"
        if str(contact.get("type", "")).lower() == "customer" or tags & {"client", "customer"} \
                or any(str(o.get("status", "")).lower() == "won" for o in opps):
            return "client"
        if any("meeting" in str(o.get("pipelineStageName") or o.get("stageName") or "").lower()
               for o in opps):
            return "meeting_booked"
        if any(str(o.get("status", "")).lower() == "lost" for o in opps):
            return "lost"
        return ""

    async def apply_webhook(self, payload: dict) -> dict:
        """Apply a GoHighLevel workflow webhook. Local-only; never writes to GHL."""
        event = str(payload.get("event") or payload.get("harvey_event") or "").strip().lower()
        email = str(payload.get("email") or (payload.get("contact") or {}).get("email") or "")
        email = email.strip().lower()
        event_id = str(payload.get("event_id") or payload.get("id") or "")
        if not event or not email:
            return {"ok": False, "error": "event and email are required"}
        new_status = WEBHOOK_STATUS.get(event)
        if new_status is None:
            return {"ok": False, "error": f"unknown event '{event}'"}
        key = f"ghl:{event_id or event + ':' + email}"
        if await self.state.is_reply_processed(key):
            return {"ok": True, "duplicate": True}
        prospect = await self.state.get_prospect_by_email(email)
        if prospect is None:
            await self.state.mark_reply_processed(key)
            return {"ok": True, "matched": False}
        if STATUS_RANK.get(new_status, 0) >= STATUS_RANK.get(prospect.status, 0):
            await self.state.update_prospect_status(prospect.id, new_status)
        cancelled = await self.state.cancel_pending_outbox_for_prospect(
            prospect.id, reason=f"GoHighLevel: {event}"
        )
        await self.state.log_action(action_type="crm_webhook", agent="crm",
                                    details={"event": event, "email": email,
                                             "cancelled": cancelled})
        await self.state.mark_reply_processed(key)
        return {"ok": True, "matched": True, "status": new_status, "cancelled": cancelled}
