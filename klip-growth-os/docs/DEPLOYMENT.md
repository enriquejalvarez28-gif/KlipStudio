# Future cloud deployment (not built)

Today the app runs on the owner's computer: `127.0.0.1` only, SQLite, a local Fernet key, and jobs that run while the computer is on.
Moving to the cloud makes the dashboard reachable from anywhere and keeps jobs running 24/7. This is the planned shape. **Nothing here is deployed.**

## Target architecture

```
Browser / installed PWA
        │ HTTPS (owner sign-in: passkey or Google SSO + allowlist; later per-client roles)
        ▼
Web app container (same growth_os package: server.py → swap stdlib server for uvicorn/ASGI)
        │                        ▲
        │ SQL                    │ job queue
        ▼                        │
Postgres (managed)      Worker container(s) (scheduler.py, same handlers)
  tenant_id on every    • Postgres advisory lock replaces the `locks` table lease
  row + row-level       • same dedup_key uniqueness, same retry/alert rules
  security policies     │
        │               ▼
        │        Object storage (thumbnails, reports, imports), per-tenant prefixes, signed URLs
        ▼
Secrets manager / KMS: encrypts OAuth refresh tokens (envelope encryption replaces the local Fernet key)
```

## What changes, what stays

| Concern | Local today | Cloud |
|---|---|---|
| HTTP server | stdlib `ThreadingHTTPServer`, Host check + CSRF | ASGI server behind TLS; session auth; same route table and CSRF |
| Database | SQLite (WAL) | Postgres; migrations ported 1:1; RLS by `tenant_id` |
| Scheduler | thread in the app process, lease row | separate worker; advisory lock; same `job_runs` semantics |
| Secrets | Fernet key file (0600) | KMS envelope encryption; key rotation |
| OAuth | Desktop client, loopback redirect | Web client with a fixed HTTPS redirect URI; verified consent screen |
| Files | `data/thumbs`, `data/reports` | object storage, signed URLs, lifecycle policy |
| PDF | local Edge/Chrome | headless Chromium in the worker image |
| AI | owner's Claude Code CLI | Claude API key held server-side with a per-tenant budget (a new billable service: needs owner approval first) |
| Sharing | none (owner only) | expiring, revocable, tenant-scoped read-only report links (spec §8), tested from an unauthenticated browser |

## Preconditions before going live

1. Owner approval for any paid hosting and the AI API key (no automatic upgrades).
2. Auth in front of every route, plus a penetration-style test of cross-tenant access.
3. Google OAuth app verification for a production consent screen.
4. Backups: Postgres point-in-time recovery; reports and thumbnails can be regenerated.
5. Data export and deletion procedure per client brand.
