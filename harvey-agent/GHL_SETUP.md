# Harvey + GoHighLevel

How the two systems split the work, what Harvey does automatically, and
the few things that must be clicked inside GoHighLevel (its API can't
create workflows or connect a mailbox).

## Who owns what

| Before the prospect replies | After a genuine reply |
|---|---|
| **Harvey** finds, researches, writes, sends, follows up | **GoHighLevel** owns the relationship: conversations, calls, tasks, meetings, pipeline |

Harvey stops the moment a reply arrives (before any AI step) and never
emails that person again. If either system says stop, the stricter answer wins.

## What Harvey does on its own (built and tested)

| When | Harvey does |
|---|---|
| Before every cold email | Looks the address up in GHL. **Blocks** if the contact already exists and wasn't created by Harvey, has DND, carries a suppression tag (`do-not-contact`, `dnd`, `client`, `customer`, `harvey-opted-out`), is a customer, or has an open opportunity. If GHL can't be reached, the email **waits**; it is never sent blind. |
| Just before sending | Creates/updates the GHL contact (tag `harvey-outreach`). It has to exist first: GHL's Gmail sync only threads mail for existing contacts. |
| After sending | Adds a note: from, to, subject, body, time, Message-ID, Gmail thread, campaign. Marked "accepted by mail provider", not "delivered". |
| On a reply | Cancels all queued follow-ups, then hands off to GoHighLevel. It adds a note with the reply, its research and the full email history, creates a task for the salesperson, and opens an opportunity in **Engaged Lead** for interested replies or questions. Finally it adds the tags `harvey-replied` and `harvey-handoff`, which start Workflow A. No auto-reply from Harvey. |
| On "stop / remove me" | Turns on DND (Email) in GHL, adds the tag `harvey-opted-out` and suppresses the person permanently. |
| Later replies from a handed-off lead | Logged as a note only. |
| If GHL syncs keep failing | After 3 failures, all new outreach holds until `harvey ghl sync` clears them. |

Each sync job has an idempotency key, so a retry or a duplicate reply
never creates a second contact, note, task or opportunity.

## One-time setup

1. **Private Integration token.** Sub-account → Settings → Private Integrations → Create.
   - **Scopes:** contacts (read and write), opportunities (read and write), conversations (read), locations (read).
   - **`.env`:** put the token and the Location ID in as `GHL_API_TOKEN` and `GHL_LOCATION_ID`, and add a random `GHL_WEBHOOK_SECRET`.
2. **Check the connection, then create the pipeline if it's missing:**
   ```bash
   harvey ghl test
   harvey ghl setup    # reuses the pipeline if it already exists
   ```
   This creates **KLIP MEDIA — BUSINESS DEVELOPMENT** with eight stages: Engaged Lead, Contacted / Follow-Up, Meeting Scheduled, Meeting Completed, Proposal Sent, Negotiation, Won, and Lost / Nurture.
3. **Connect the outreach mailbox to GHL** so the conversation stays in one thread.
   - **Where:** the salesperson's profile → Email Sync → Connect Google, signed in as the outreach mailbox (e.g. enrique@growwithklip.com). Turn on two-way sync.
   - **What that gives you:** the prospect's reply shows in GHL Conversations. The salesperson answers from GHL, the email goes out from that same mailbox in the same thread, and the prospect's next reply lands in GHL too.
4. **Salesperson.** Put their GHL user ID in `harvey.yaml` → `crm.assigned_user_id`, then set `crm.enabled: true`.
5. **Workflows.** Build the five below (about 15 minutes).

## The workflows (build in GHL → Automation → Workflows)

Webhook URL for B, D and E:
`https://<HARVEY_HOST>/webhooks/ghl?secret=<GHL_WEBHOOK_SECRET>`.
In each webhook action, add **Custom Data** `event` = the value shown.
GHL already includes the contact's email.

| Workflow | Trigger | Actions |
|---|---|---|
| **A. Harvey handoff** | Contact Tag added: `harvey-handoff` | Assign to user (round robin or Enrique); Internal notification (email/app): "New reply from {{contact.name}}, see handoff note"; Update contact field "Lead source" = Harvey |
| **B. Customer reply** | Customer Replied (channel: Email) | If contact has tag `harvey-outreach`: internal notification to the assigned user. Remove the contact from other nurture workflows (to avoid conflicting automations). Webhook with `event` = `contacted` |
| **C. Sales follow-up** | Task added (or Opportunity stage = Contacted / Follow-Up) | Wait until due; if not completed, notify the assigned user |
| **D. Meeting booked** | Appointment Status: booked/confirmed | Move the opportunity to **Meeting Scheduled**; notify the assigned user; Webhook with `event` = `meeting_booked`. Optional: Opportunity status changed → Webhook `event` = `won` or `lost`; Pipeline stage changed → `stage_changed` |
| **E. Opt-out** | Contact DND changed (Email) **or** Tag added: `do-not-contact` | Add tag `harvey-opted-out`; remove from all workflows; Webhook with `event` = `opt_out` |

Events Harvey understands: `opt_out`, `dnd`, `meeting_booked`,
`appointment_booked`, `client`, `won`, `lost`, `contacted`, `call_logged`,
`stage_changed`, `proposal_sent`. Every one of them stops cold outreach to
that person. Webhooks only change Harvey's own records and never write back
to GHL, so the two systems can't loop.

## Calls

The salesperson calls from GHL. The handoff note carries the business,
contact, phone, website, industry, the opportunity Harvey found, the email
history, the reply and a suggested opener. Log the call outcome in GHL.
Harvey hears about it through Workflow B/D (`call_logged` / `contacted`).
Harvey never places calls or sends SMS.
