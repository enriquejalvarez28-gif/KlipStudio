# Running Harvey on a server

Harvey runs on a small always-on Linux server, independent of your computer.
Docker restarts it after crashes and reboots, the data folder persists, Caddy
handles HTTPS, and only the GoHighLevel webhook is public.

## 1. Server

Any small Ubuntu VPS with 2 GB RAM (DigitalOcean, Hetzner, Vultr), about
$6–12/month. Install Docker, then:

```bash
git clone <this repo> && cd KlipStudio/harvey-agent
cp .env.example .env && nano .env      # fill in, see below
mkdir -p data
docker compose -f deploy/server/docker-compose.yml up -d --build
docker compose -f deploy/server/docker-compose.yml logs -f agent
```

## 2. Secrets that can't be created on the server

| What | How |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | On your own computer: `claude setup-token`, then paste the token into `.env`. Harvey thinks with your Claude subscription. |
| Gmail login | On your own computer: `harvey gmail auth` (it opens a browser), then copy `data/gmail_token.json` to the server's `data/` folder. |
| `GHL_*` | See [GHL_SETUP.md](../../GHL_SETUP.md). |
| `DASHBOARD_PASSWORD_HASH` | `docker run --rm caddy:2.8 caddy hash-password --plaintext 'pick-one'` |

## 3. DNS for the outreach domain (e.g. growwithklip.com)

Add these at the registrar. All of them are needed before the first real send.

| Type | Name | Value | Why |
|---|---|---|---|
| MX | @ | `smtp.google.com` (priority 1) | Receive replies (Google Workspace) |
| TXT | @ | `v=spf1 include:_spf.google.com ~all` | SPF: only Google may send for the domain |
| TXT | `google._domainkey` | Generated in Google Admin → Apps → Gmail → Authenticate email | DKIM signature |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@growwithklip.com; adkim=r; aspf=r` | DMARC in report-only mode first |
| A | `harvey` | the server's IP | `HARVEY_HOST=harvey.growwithklip.com` for HTTPS and webhooks |
| Redirect | @ / www | → https://theklipstudio.com | A real site behind the domain looks legitimate to filters and people |

After 2–4 weeks of clean reports (SPF and DKIM passing, no surprises),
move DMARC to `p=quarantine`. Don't jump to `p=reject` before mail flow
has been checked. Google Workspace sends over TLS by default.

## 4. Monitoring and backups

- **Health checks:** Docker restarts a dead process, and the agent container has a health check.
- **Uptime alerts:** set `HEARTBEAT_PING_URL` to a free healthchecks.io check, and you'll get an email if Harvey stops pinging (it pings every few minutes, working or resting).
- **Backups:** `deploy/server/backup.sh` makes a daily SQLite backup kept for 14 days. Add it to the crontab, as shown in the file, and copy `data/backups` off the server.
- **Status:**
  ```bash
  docker compose -f deploy/server/docker-compose.yml exec agent python -m harvey.cli status
  ```

## 5. Daily operation

Open `https://harvey.<domain>` (it asks for a password) to approve emails in
the Outbox. The kill switch is `harvey sending pause`, or the button on the
dashboard.
