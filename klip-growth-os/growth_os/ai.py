"""AI interpretation layer — the only module that calls a model.

Runs through the owner's existing Claude Code subscription (`claude -p`,
same approach as harvey-agent/harvey/brain.py): no API key, no new billing.
Calls run with no tools and no MCP servers, take compact JSON, are cached by
input hash (unchanged inputs are never re-sent), capped per day, and logged
to usage_log. Every output is stored and shown labelled as AI.
"""

import hashlib
import json
import os
import shutil
import subprocess

from growth_os.db import get_setting, utcnow

DEFAULT_MODEL = "haiku"     # short creative/classification work
STRONG_MODEL = "sonnet"     # strategy, on demand only
DEFAULT_DAILY_CALLS = 25
TIMEOUT_S = 120


class AIUnavailable(Exception):
    pass


def status(conn):
    exe = shutil.which("claude")
    enabled = get_setting(conn, "ai.enabled", True)
    cap = get_setting(conn, "ai.daily_calls", DEFAULT_DAILY_CALLS)
    used = conn.execute("SELECT COUNT(*) FROM usage_log WHERE kind='llm' AND cache_hit=0 AND at>=?",
                        (utcnow()[:10],)).fetchone()[0]
    return {"cli_found": bool(exe), "enabled": bool(enabled), "daily_cap": cap, "used_today": used,
            "reason": None if exe else "Claude Code CLI not found on PATH; AI drafts are off. Deterministic analysis still runs."}


def _run_cli(prompt, model):
    exe = shutil.which("claude")
    if not exe:
        raise AIUnavailable("Claude Code CLI not installed")
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--model", model]
    env = dict(os.environ)
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0:
        raise AIUnavailable((p.stderr or p.stdout)[:300])
    return json.loads(p.stdout)


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return json.loads(text[start:])


def ask(conn, tenant_id, purpose, payload, instructions, *, model=DEFAULT_MODEL, runner=None, force=False):
    """Return (output, meta). payload must already be compact; never pass raw datasets."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    key = hashlib.sha256(f"{purpose}|{model}|{instructions}|{body}".encode()).hexdigest()
    if not force:
        hit = conn.execute("SELECT * FROM ai_cache WHERE key=? AND tenant_id=?", (key, tenant_id)).fetchone()
        if hit:
            conn.execute("""INSERT INTO usage_log (tenant_id, kind, name, cache_hit, at) VALUES (?,?,?,?,?)""",
                         (tenant_id, "llm", f"{purpose}:{hit['model']}", 1, utcnow()))
            return json.loads(hit["output_json"]), {"cached": True, "model": hit["model"], "created_at": hit["created_at"]}
    st = status(conn)
    if not st["enabled"]:
        raise AIUnavailable("AI drafts are switched off in Settings")
    if runner is None and not st["cli_found"]:
        raise AIUnavailable(st["reason"])
    if st["used_today"] >= st["daily_cap"]:
        raise AIUnavailable(f"daily AI cap reached ({st['daily_cap']} calls); raise it in Settings or wait until tomorrow")
    prompt = (f"{instructions}\n\nReturn ONLY valid JSON matching the requested shape. "
              f"Do not invent metrics; use only numbers present in INPUT.\n\nINPUT:\n{body}")
    raw = (runner or _run_cli)(prompt, model)
    out = _extract_json(raw.get("result", ""))
    usage = raw.get("usage", {})
    tin = int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0))
    tout = int(usage.get("output_tokens", 0))
    cost = float(raw.get("total_cost_usd") or 0)
    real_model = next(iter(raw.get("modelUsage", {}) or {}), model)
    now = utcnow()
    conn.execute("INSERT OR REPLACE INTO ai_cache VALUES (?,?,?,?,?,?,?,?,?)",
                 (key, tenant_id, purpose, real_model, json.dumps(out), tin, tout, cost, now))
    conn.execute("""INSERT INTO usage_log (tenant_id, kind, name, tokens_in, tokens_out, cache_hit, duration_ms, at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (tenant_id, "llm", f"{purpose}:{real_model}", tin, tout, 0, int(raw.get("duration_ms", 0)), now))
    return out, {"cached": False, "model": real_model, "created_at": now, "tokens_in": tin, "tokens_out": tout,
                 "cost_estimate_usd": cost}


TITLE_STRATEGIES = ["clear_educational", "curiosity", "expert_authority", "debate", "question_led", "search_driven"]

TITLE_INSTRUCTIONS = (
    "You are a YouTube packaging editor for a podcast/media brand. Write alternative titles for the video in INPUT. "
    "Produce exactly one title per strategy in INPUT.strategies. Max 70 characters each. No clickbait that the "
    "episode cannot deliver, no ALL CAPS words, no made-up facts, names or numbers not present in INPUT. "
    "Use INPUT.search_terms and INPUT.topic_keywords where natural. For each give a one-sentence 'why' tied to "
    "INPUT evidence. Never state a predicted CTR or virality probability. "
    'Shape: {"titles":[{"strategy":"...","title":"...","why":"..."}],"keep_current":true|false,"keep_reason":"..."}'
)

THUMB_INSTRUCTIONS = (
    "You are a thumbnail art director. Using INPUT (measured image features, title, topic, peer comparison), "
    "propose 3 distinct thumbnail concepts to TEST, not guaranteed winners. Each: concept name, composition, "
    "headline text (max 4 words, must not repeat the title verbatim), color direction informed by the measured "
    "features, and which measured weakness it addresses. Also list 2 experiments the owner could run (e.g. "
    "YouTube 'Test & compare' in Studio when available). Do not claim outcomes. "
    'Shape: {"concepts":[{"name":"","composition":"","headline":"","colors":"","addresses":""}],'
    '"experiments":[{"what":"","how":"","measure":""}]}'
)

TREND_INSTRUCTIONS = (
    "You are an editorial producer. For the trend in INPUT and the brand topics, propose: an episode angle, why now "
    "(only from INPUT facts), target audience, 3 title options, 5 interview questions, 3 short-form hooks, and 2 "
    "guest archetypes (roles, not real names). If the item is weakly related to the brand, say so in 'fit'. "
    'Shape: {"fit":"strong|partial|weak","angle":"","why_now":"","audience":"","titles":[],"questions":[],"hooks":[],"guests":[]}'
)
