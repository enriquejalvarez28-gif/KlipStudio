# Harvey for The Klip Studio

Harvey is an autonomous email sales agent (open source, MIT, from
github.com/ethanplusai/harvey) set up here to sell The Klip Studio and Klip
Media. It finds South Florida businesses, reads their websites, writes
short personal cold emails in Klip's voice, sends them from Gmail, reads the
replies and works each conversation toward a 15-minute call.

It thinks with your Claude subscription (no API bill), and **nothing is sent
until you approve it** in the Outbox.

## The full system (Harvey + GoHighLevel)

- **Harvey** finds, researches, writes and sends cold email from a separate
  outreach domain, and follows up. **GoHighLevel** takes over the moment
  someone replies. The details are in [GHL_SETUP.md](GHL_SETUP.md).
- **Server:** it runs on a small always-on server, not your computer. See
  [deploy/server/README.md](deploy/server/README.md), which also covers the
  DNS records (SPF, DKIM, DMARC).
- **Sending ramp:** 5 emails a day in week 1, then 10, 15 and 20
  (`channels.email.ramp_start`).
- **Approvals:** every email, first or follow-up, waits for your approval.

## What's customized for Klip

| | |
|---|---|
| `harvey.yaml` | Persona (Enrique, The Klip Studio), offers, prices from theklipstudio.com, target industries (medical, legal, real estate, mortgage, advisors, coaches, fitness), South Florida cities, work schedule, compliance footer |
| `skills/product_knowledge.md` | Rooms, packages, Klip Media services, buyers, triggers, objections |
| `skills/klip_brand_voice.md` | Voice, bilingual rules, sign-off, one-ask rule, never-do list, regulated-industry rules |
| `skills/klip_copywriting.md` | Klip's copy system: 3 hook types, lead-reply formula, 3-touch re-engage, subject lines, repurposing angle |
| `skills/klip_signal_angles.md` | Each website signal (no site, stale blog, running ads, agency, hiring...) mapped to an angle and a Klip offer |
| `skills/email_marketing.md` | What to do with "not now" replies: consent-first nurture, newsletter, segments, metrics |
| Work schedule | New `usage.work_schedule`: Harvey works only inside your shifts and sleeps the rest |
| Compliance footer | New `channels.email.footer`: your address + opt-out appended to every cold email (CAN-SPAM) |

Which agent reads which skill is in `harvey/brain.py` (`skill_map`).

## When it works

Recommended and already set in `harvey.yaml`:

- **Two short blocks on weekdays: 09:00 to 11:00 and 14:00 to 16:00
  Eastern.** It checks in once an hour inside each block, so about 4 times
  a day. Someone who replies in the morning hears back that afternoon.
- **Weekends off.** Quiet hours from 20:00 to 07:00 are a hard stop.
- **Claude limit of 20%.** That's a ceiling, not what it uses: if your
  Claude plan reaches 20% used, Harvey stops for the day. A check-in with
  nothing to do uses no Claude at all. Claude is only used to write emails
  and answer replies, so your usage follows how many emails it writes,
  not how often it checks in.
- **Once a day instead?** Delete the 14:00 shift. That works fine for
  finding and writing to prospects, but replies then wait until the next
  morning, and a slow answer to someone who's interested loses deals.

Change any of it in `harvey.yaml` under `usage:`. Check it any time:

```bash
harvey schedule
```

## Setup (about 30 minutes, once)

You need an always-on computer (your Mac, a Windows PC that stays on, or a
small VPS), Python 3.11+, and Claude Code logged in (`claude login`).

```bash
cd harvey-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[jobs]'          # 'jobs' adds job-board discovery
cp .env.example .env
```

1. **Sending mailbox.** Buy a separate domain for cold email (never send
   cold from theklipstudio.com), create a Google Workspace mailbox on it,
   and set up SPF, DKIM and DMARC. Warm it up for 2 to 4 weeks.
   Put the address in `persona.email` in `harvey.yaml`.
2. **Gmail access.** Google Cloud Console: enable the Gmail API, create an
   OAuth client ("Desktop app"), paste the ID and secret into `.env`, then
   run `harvey gmail auth`.
3. **Email verifier** (required, or nothing gets sent): a free
   `REOON_API_KEY` (600/month) and/or `ZEROBOUNCE_API_KEY` in `.env`.
4. **Optional extras** in `.env`: `HUNTER_API_KEY` (email patterns),
   `DATAFORSEO_LOGIN`/`PASSWORD` (best local-business data, about $0.37 per
   1,000), `SERPER_API_KEY` (2,500 free searches).
5. **Choose what makes a good prospect:**
   ```bash
   harvey signals --confirm free
   ```
6. **Find businesses** (the free OpenStreetMap source first):
   ```bash
   harvey discover --estimate && harvey discover
   ```
7. **Check prices.** Your website and the Klip skills disagree on room
   rates (for example Klip Room $199/hr on the site vs $169/$239 in the
   skills). Fix `skills/product_knowledge.md` and the `pricing` line in
   `harvey.yaml` to the real current numbers.

## Leave it running

Pick the one that matches the machine. Each restarts Harvey if it stops,
and Harvey itself sleeps outside its shifts.

- **Mac:** `deploy/com.klipstudio.harvey.plist` (install steps inside)
- **Windows:** `powershell -ExecutionPolicy Bypass -File deploy\windows-install.ps1`
- **Linux / VPS:** `deploy/harvey.service` (systemd, steps inside)
- **Docker:** `docker compose up -d` (mounts `~/.claude` for your login)

## Daily use

```bash
harvey dashboard          # http://localhost:5555, approve emails in Outbox
harvey outbox             # or approve from the terminal
harvey status             # pipeline summary
harvey sending pause      # kill switch; 'resume' to continue
```

Start with approval on (the default). Once a couple of weeks of drafts look
right, you can set `channels.email.require_approval: false`.

## Ground rules it follows

- Never invents prices, clients, testimonials or results.
- One link at most, plain text, short emails, no hype.
- Any "stop" or "remove me" is a permanent opt-out.
- Never adds anyone to a newsletter without a yes.
- If asked whether it's automated, it says yes.
- LinkedIn automation is off (it breaks LinkedIn's terms).
