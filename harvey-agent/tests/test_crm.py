"""GoHighLevel bridge: pre-send check, contact-before-send, outbound sync,
reply handoff, opt-out, webhooks, failure holds, no duplicates, ramp.

A fake GHL API (httpx.MockTransport) stands in for the real one."""

import json
import os
import tempfile
from datetime import date

import httpx
import pytest
import pytest_asyncio

from harvey.config import CRMConfig
from harvey.crm import CRMBridge, GHLClient
from harvey.integrations.mail_provider import InboundMessage
from harvey.state import StateManager
from tests.test_outbox_native import (
    Cfg, Env, FakeProvider, StubBrain, _now_iso, seed_campaign, seed_prospect,
)


class FakeGHL:
    """In-memory GoHighLevel: contacts keyed by email."""

    def __init__(self):
        self.contacts = {}       # id -> contact dict
        self.notes = []          # (cid, body)
        self.tasks = []
        self.opps = []
        self.pipelines = [{"id": "p1", "name": "KLIP MEDIA — BUSINESS DEVELOPMENT",
                           "stages": [{"id": "s1", "name": "Engaged Lead"}]}]
        self.down = False
        self.calls = []

    def add(self, email, **kw):
        cid = f"c{len(self.contacts) + 1}"
        self.contacts[cid] = {"id": cid, "email": email, "tags": [], **kw}
        return cid

    def by_email(self, email):
        return next((c for c in self.contacts.values() if c["email"] == email), None)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, text="down")
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        body = json.loads(request.content) if request.content else {}
        q = request.url.params
        if path == "/contacts/search/duplicate":
            return httpx.Response(200, json={"contact": self.by_email(q["email"])})
        if path == "/contacts/upsert":
            c = self.by_email(body["email"])
            if c is None:
                cid = self.add(body["email"])
                c = self.contacts[cid]
            c.update({k: v for k, v in body.items() if k not in ("locationId", "tags")})
            return httpx.Response(200, json={"contact": c})
        if path == "/opportunities/search":
            return httpx.Response(200, json={"opportunities": [
                o for o in self.opps if o["contactId"] == q["contact_id"]]})
        if path == "/opportunities/pipelines":
            if method == "POST":
                self.pipelines.append({"id": "p2", "name": body["name"], "stages": body["stages"]})
                return httpx.Response(200, json={"pipeline": {"id": "p2"}})
            return httpx.Response(200, json={"pipelines": self.pipelines})
        if path == "/opportunities/":
            self.opps.append(body)
            return httpx.Response(200, json={"opportunity": {"id": f"o{len(self.opps)}"}})
        parts = path.strip("/").split("/")
        if parts[0] == "contacts" and len(parts) >= 2:
            c = self.contacts[parts[1]]
            if len(parts) == 2 and method == "GET":
                return httpx.Response(200, json={"contact": c})
            if len(parts) == 2 and method == "PUT":
                c.update(body)
                return httpx.Response(200, json={"contact": c})
            if parts[2] == "tags":
                c["tags"] = sorted(set(c["tags"]) | set(body["tags"]))
                return httpx.Response(200, json={"tags": c["tags"]})
            if parts[2] == "notes":
                self.notes.append((c["id"], body["body"]))
                return httpx.Response(200, json={"note": {"id": "n"}})
            if parts[2] == "tasks":
                self.tasks.append((c["id"], body))
                return httpx.Response(200, json={"task": {"id": "t"}})
        return httpx.Response(404, text=f"no route {method} {path}")


class CrmCfg(Cfg):
    crm = CRMConfig(enabled=True, assigned_user_id="u1")


@pytest_asyncio.fixture
async def state():
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = StateManager(os.path.join(tmpdir, "test.db"))
        await sm.init_db()
        yield sm


@pytest.fixture
def ghl():
    return FakeGHL()


def _bridge(state, ghl, cfg=None):
    client = GHLClient("tok", "loc", transport=httpx.MockTransport(ghl.handler))
    return CRMBridge(state, cfg or CrmCfg(), Env(), client=client)


def make_sender(state, ghl, provider, cfg=None):
    from harvey.agents.sender import Sender
    cfg = cfg or CrmCfg()
    cfg.channels.email.require_approval = False
    s = Sender(brain=None, state=state, config=cfg, env=Env())
    s.provider, s.send_pacing = provider, False
    s.crm = _bridge(state, ghl, cfg)
    return s


def make_handler(state, ghl, provider, intent="interested"):
    from harvey.agents.handler import Handler
    h = Handler(brain=StubBrain(intent=intent), state=state, config=CrmCfg(), env=Env())
    h.provider = provider
    h.crm = _bridge(state, ghl)
    return h


async def _send_first_step(state, ghl, provider=None):
    pid = await seed_prospect(state)
    await seed_campaign(state, [pid])
    provider = provider or FakeProvider()
    await make_sender(state, ghl, provider)._run_native()
    return pid, provider


# ── pre-send check / contact before send / outbound sync ──


class OrderProvider(FakeProvider):
    """Records whether the GHL contact existed at the moment of sending."""

    def __init__(self, ghl):
        super().__init__()
        self.ghl = ghl
        self.contact_existed = []

    async def send_email(self, to_email, *a, **k):
        self.contact_existed.append(self.ghl.by_email(to_email) is not None)
        return await super().send_email(to_email, *a, **k)


@pytest.mark.asyncio
async def test_send_creates_contact_first_then_logs_outbound(state, ghl):
    pid, provider = await _send_first_step(state, ghl, OrderProvider(ghl))
    assert len(provider.sent) == 1
    assert provider.contact_existed == [True]   # Gmail sync needs it to exist first
    c = ghl.by_email("jane@acme.com")
    assert c and "harvey-outreach" in c["tags"]
    assert any("Harvey sent cold email" in n and "Message-ID" in n for _, n in ghl.notes)
    assert await state.count_crm_sync("done") == 1


@pytest.mark.asyncio
async def test_existing_crm_contact_is_never_cold_emailed(state, ghl):
    ghl.add("jane@acme.com", tags=["vip"])  # known to Klip, not from Harvey
    pid, provider = await _send_first_step(state, ghl)
    assert provider.sent == []
    assert (await state.get_prospect(pid)).status == "suppressed"
    assert await state.get_outbox(status="approved") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("contact", [
    {"tags": ["harvey-outreach"], "dnd": True},
    {"tags": ["harvey-outreach", "client"]},
    {"tags": ["harvey-outreach"], "dndSettings": {"Email": {"status": "active"}}},
    {"tags": ["harvey-outreach"], "type": "customer"},
])
async def test_suppression_signals_block(state, ghl, contact):
    ghl.add("jane@acme.com", **contact)
    _, provider = await _send_first_step(state, ghl)
    assert provider.sent == []


@pytest.mark.asyncio
async def test_open_opportunity_blocks(state, ghl):
    cid = ghl.add("jane@acme.com", tags=["harvey-outreach"])
    ghl.opps.append({"contactId": cid})
    _, provider = await _send_first_step(state, ghl)
    assert provider.sent == []


@pytest.mark.asyncio
async def test_ghl_down_holds_email_safely(state, ghl):
    ghl.down = True
    pid, provider = await _send_first_step(state, ghl)
    assert provider.sent == []
    assert len(await state.get_outbox(status="approved")) >= 1  # held, not lost
    assert (await state.get_prospect(pid)).status != "suppressed"
    ghl.down = False
    await make_sender(state, ghl, provider)._run_native()
    assert len(provider.sent) == 1


@pytest.mark.asyncio
async def test_failing_sync_backlog_pauses_outreach(state, ghl):
    for i in range(3):
        await state.enqueue_crm_sync(f"x{i}", "outbound", "missing", {})
        await state.finish_crm_sync(f"x{i}", False, "boom")
    bridge = _bridge(state, ghl)
    assert "failing" in await bridge.outreach_blocked()


# ── reply handoff ──


@pytest.mark.asyncio
async def test_reply_stops_and_hands_off(state, ghl):
    pid, provider = await _send_first_step(state, ghl)
    provider.inbound = [InboundMessage(provider_id="in1", from_email="jane@acme.com",
                                       subject="Re: hi Jane", body="Sounds good, tell me more.",
                                       message_id="<r1@x>")]
    handler = make_handler(state, ghl, provider)
    await handler._run_native()

    assert (await state.get_prospect(pid)).status == "handed_off"
    assert await state.get_outbox(status="approved") == []           # follow-up cancelled
    assert await state.get_outbox(status="pending_review") == []      # no Harvey auto-reply
    c = ghl.by_email("jane@acme.com")
    assert {"harvey-replied", "harvey-handoff"} <= set(c["tags"])
    handoff = next(n for _, n in ghl.notes if n.startswith("HANDOFF FROM HARVEY"))
    assert "Sounds good" in handoff and "Email history" in handoff and "hi Jane" in handoff
    assert ghl.tasks and ghl.tasks[0][1]["assignedTo"] == "u1"
    assert len(ghl.opps) == 1 and ghl.opps[0]["pipelineStageId"] == "s1"

    # Same reply delivered twice: no second handoff, task or opportunity.
    handler2 = make_handler(state, ghl, provider)
    await handler2._run_native()
    assert len(ghl.tasks) == 1 and len(ghl.opps) == 1
    # Contact upserted, never duplicated.
    assert sum(1 for c in ghl.contacts.values() if c["email"] == "jane@acme.com") == 1


@pytest.mark.asyncio
async def test_webhook_before_reply_still_gets_full_handoff(state, ghl):
    pid, provider = await _send_first_step(state, ghl)
    # GHL's "customer replied" workflow fires before Harvey reads the mailbox.
    await _bridge(state, ghl).apply_webhook({"event": "contacted", "email": "jane@acme.com"})
    provider.inbound = [InboundMessage(provider_id="in1", from_email="jane@acme.com",
                                       subject="Re", body="Interested.", message_id="<r1@x>")]
    await make_handler(state, ghl, provider)._run_native()
    assert any(n.startswith("HANDOFF FROM HARVEY") for _, n in ghl.notes)
    assert len(ghl.tasks) == 1


@pytest.mark.asyncio
async def test_later_reply_after_handoff_is_logged_not_reprocessed(state, ghl):
    pid, provider = await _send_first_step(state, ghl)
    provider.inbound = [InboundMessage(provider_id="in1", from_email="jane@acme.com",
                                       subject="Re", body="Interested.", message_id="<r1@x>")]
    await make_handler(state, ghl, provider)._run_native()
    provider.inbound = [InboundMessage(provider_id="in2", from_email="jane@acme.com",
                                       subject="Re", body="Tuesday works.", message_id="<r2@x>")]
    h = make_handler(state, ghl, provider, intent="SHOULD_NOT_BE_CALLED")
    await h._run_native()
    assert (await state.get_prospect(pid)).status == "handed_off"
    assert any("Tuesday works" in n for _, n in ghl.notes)
    assert len(ghl.tasks) == 1


@pytest.mark.asyncio
async def test_opt_out_reply_sets_dnd_and_blocks_future(state, ghl):
    pid, provider = await _send_first_step(state, ghl)
    provider.inbound = [InboundMessage(provider_id="in1", from_email="jane@acme.com",
                                       subject="Re", body="Please remove me.", message_id="<r@x>")]
    await make_handler(state, ghl, provider, intent="SHOULD_NOT_BE_CALLED")._run_native()
    c = ghl.by_email("jane@acme.com")
    assert c["dnd"] is True and "harvey-opted-out" in c["tags"]
    assert (await state.get_prospect(pid)).status == "opted_out"
    assert ghl.tasks == []
    check = await _bridge(state, ghl).precheck(await state.get_prospect(pid))
    assert not check.allowed


# ── GHL -> Harvey webhooks ──


@pytest.mark.asyncio
async def test_webhook_meeting_booked_stops_outreach_once(state, ghl):
    pid = await seed_prospect(state, status="contacted")
    await state.add_outbox_item(prospect_id=pid, to_email="jane@acme.com", subject="s",
                                body="b", send_at=_now_iso(), status="approved",
                                campaign_id="c1", step=2)
    bridge = _bridge(state, ghl)
    r = await bridge.apply_webhook({"event": "meeting_booked", "email": "Jane@Acme.com",
                                    "event_id": "e1"})
    assert r["matched"] and r["cancelled"] == 1
    assert (await state.get_prospect(pid)).status == "meeting"
    assert (await bridge.apply_webhook({"event": "meeting_booked", "email": "jane@acme.com",
                                        "event_id": "e1"}))["duplicate"]
    # A weaker status never overrides a stronger one; opt-out always wins.
    await bridge.apply_webhook({"event": "contacted", "email": "jane@acme.com", "event_id": "e2"})
    assert (await state.get_prospect(pid)).status == "meeting"
    await bridge.apply_webhook({"event": "opt_out", "email": "jane@acme.com", "event_id": "e3"})
    assert (await state.get_prospect(pid)).status == "opted_out"
    assert ghl.calls == []  # webhooks never write back to GHL (no loops)


@pytest.mark.asyncio
async def test_webhook_rejects_unknown_event(state, ghl):
    r = await _bridge(state, ghl).apply_webhook({"event": "party", "email": "a@b.co"})
    assert not r["ok"]


def test_webhook_endpoint_requires_secret(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import harvey.dashboard as dash

    monkeypatch.setenv("GHL_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(dash, "DB_PATH", tmp_path / "h.db")
    client = TestClient(dash.app)
    assert client.post("/webhooks/ghl", json={"event": "dnd", "email": "a@b.co"}).status_code == 401
    r = client.post("/webhooks/ghl?secret=s3cret",
                    json={"customData": {"event": "dnd"}, "email": "nobody@b.co"})
    assert r.status_code == 200 and r.json()["matched"] is False


# ── pipeline + ramp ──


@pytest.mark.asyncio
async def test_create_pipeline(ghl):
    client = GHLClient("tok", "loc", transport=httpx.MockTransport(ghl.handler))
    assert await client.create_pipeline("New", ["A", "B"]) == "p2"


def test_ramp_caps_by_week(state):
    from harvey.agents.sender import Sender
    cfg = CrmCfg()
    email = cfg.channels.email
    saved = email.max_daily_sends
    email.max_daily_sends = 50
    email.ramp_start = "2026-10-01"
    email.ramp_weekly_caps = [5, 10, 15, 20]
    s = Sender(brain=None, state=state, config=cfg, env=Env())
    try:
        assert s.daily_cap(date(2026, 9, 30)) == 0
        assert s.daily_cap(date(2026, 10, 1)) == 5
        assert s.daily_cap(date(2026, 10, 8)) == 10
        assert s.daily_cap(date(2026, 10, 22)) == 20
        assert s.daily_cap(date(2027, 1, 1)) == 20
    finally:
        email.max_daily_sends = saved
        del email.ramp_start
        del email.ramp_weekly_caps
