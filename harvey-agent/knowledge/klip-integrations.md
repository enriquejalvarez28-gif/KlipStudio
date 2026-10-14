# Integrations

| System | Role | Status |
|---|---|---|
| Harvey (this repo) | Research, drafts, sending, reply detection | Built; 459 tests pass |
| GoHighLevel | CRM after reply; pre-send check; webhooks back | Code built + tested against a fake GHL; needs GHL_API_TOKEN + Location ID. Workflows A–E built by hand (GHL_SETUP.md) |
| Gmail / Google Workspace | Sending + reply reading; GHL two-way sync for thread continuity | Pending mailbox approval |
| Claude subscription | AI for opportunity interpretation, drafting, ambiguous replies | Available |
| Reoon / ZeroBounce (free tiers) | Email verification | Needs a free API key |
| Apollo, Clay (connected) | Optional enrichment | Not used: costs credits, needs approval |
| Other Klip stack (skills) | SimplyBook.me, Stripe, Twilio, Make.com, Metricool | Not connected to Harvey |
