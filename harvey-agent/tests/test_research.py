"""Lead research records: validation, dedup, history, eligibility, dashboard API."""

import os
import tempfile

import pytest
import pytest_asyncio

from harvey.research import import_records, record_key, score, validate
from harvey.state import StateManager


def V(value, source="https://example.com/src"):
    return {"value": value, "status": "VERIFIED", "source": source}


def rec(**kw):
    base = {
        "business_name": "Glow Med Spa", "industry": "Med spa", "city": "Weston",
        "website": V("https://www.glowmedspa.com/"), "phone": V("(954) 555-0100"),
        "email": {"value": "", "status": "UNKNOWN", "source": ""},
        "observations": [{"text": "No YouTube found", "status": "INFERRED", "source": ""},
                         {"text": "IG 2k followers", "status": "VERIFIED", "source": "https://x"}],
        "recommended_service": "Video production", "outreach_angle": "Doctor FAQ videos",
        "priority": "high", "qualified": True,
    }
    base.update(kw)
    return base


@pytest_asyncio.fixture
async def state():
    with tempfile.TemporaryDirectory() as d:
        sm = StateManager(os.path.join(d, "t.db"))
        await sm.init_db()
        yield sm


def test_validation_rules():
    assert validate(rec()) == []
    unverified = dict(website={"value": "x.com", "status": "INFERRED"}, phone={"status": "UNKNOWN"})
    assert "business identity not verified" in validate(rec(**unverified))[0]
    assert validate(rec(qualified=False, **unverified)) == []   # rejected leads are still recorded
    assert any("without a source" in p for p in validate(rec(phone={"value": "1", "status": "VERIFIED"})))
    assert any("qualified without" in p for p in validate(rec(outreach_angle="")))


def test_key_and_score():
    assert record_key(rec()) == "d:glowmedspa.com"
    assert record_key(rec(website={"status": "UNKNOWN"})) == "n:glowmedspa:weston"
    assert score(rec()) == 6 + 1 + 1          # high priority, phone only, 1 verified obs
    assert score(rec(qualified=False)) == 0


@pytest.mark.asyncio
async def test_import_dedups_and_keeps_history(state):
    r1 = await import_records(state, [rec(), rec(business_name="", city="X")])
    assert r1["inserted"] == 1 and r1["rejected"] == 1
    r2 = await import_records(state, [rec(priority="medium",
                                          email=V("info@glowmedspa.com"))])
    assert r2["updated"] == 1
    rows = await state.list_research_records()
    assert len(rows) == 1
    row = rows[0]
    assert row["email"] == "info@glowmedspa.com" and row["outreach_eligible"] == 1
    assert '"priority": "high"' in row["history_json"]   # previous version kept
    # INFERRED values never reach the flat columns
    await import_records(state, [rec(website=V("https://other.com"),
                                     phone={"value": "999", "status": "INFERRED"})])
    other = await state.get_research_record("d:other.com")
    assert other["phone"] == ""


def test_leads_api(monkeypatch, tmp_path):
    import asyncio
    from fastapi.testclient import TestClient
    import harvey.dashboard as dash

    monkeypatch.setattr(dash, "DB_PATH", tmp_path / "h.db")
    sm = StateManager(str(tmp_path / "h.db"))
    asyncio.run(sm.init_db())
    asyncio.run(import_records(sm, [rec(draft={"subject": "s", "body": "b"})]))
    c = TestClient(dash.app)
    data = c.get("/api/leads").json()
    assert data["summary"]["qualified"] == 1 and data["summary"]["drafted"] == 1
    lead = data["leads"][0]
    detail = c.get("/api/leads/" + lead["id"]).json()
    assert detail["record"]["business_name"] == "Glow Med Spa"
    assert "KLIP" in c.get("/leads").text
