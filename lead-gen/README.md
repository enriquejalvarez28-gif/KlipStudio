# Klip Media — Lead Generation System

A research-and-tracking workflow for finding South Florida professional
businesses that could use Klip Media / Klip Studio services, and preparing
personalized Instagram DMs for **manual** sending.

Nothing here sends messages, logs into Instagram, or scrapes private data.

## Files

| File | Purpose |
|---|---|
| `leads.csv` | The CRM database (one row per business). Open in Excel / Google Sheets or import into Notion. |
| `crm.py` | Import research, de-duplicate, build the daily queue, update statuses, print the dashboard. |
| `daily_queue_YYYY-MM-DD.csv` | The day's 10 highest-scoring uncontacted leads, with DMs. |
| `research/` | Raw research batches (JSON) as collected with source URLs, plus `build_batch.py` (scoring and DMs) and the merged import batch. |

## Daily workflow

```bash
python3 lead-gen/crm.py queue            # today's 10 leads -> daily_queue_<date>.csv
# ...open each Instagram link, confirm it is the firm's real account, send the DM yourself...
python3 lead-gen/crm.py mark KM-0007 Contacted          # only after YOU sent it
python3 lead-gen/crm.py mark KM-0007 Responded --note "Asked for pricing"
python3 lead-gen/crm.py mark KM-0012 "Do Not Contact" --note "Asked not to be messaged"
python3 lead-gen/crm.py dashboard
```

`mark ... Contacted` sets Date Contacted and a Follow-Up Date 5 days later.
`Do Not Contact`, `Not Interested` and `Client` leads never return to the queue.

New research batches are merged with `python3 lead-gen/crm.py import <file.json>`;
duplicates (same website domain, or same normalized name) are skipped, so a
business already in the database can never re-enter a future queue.

## Statuses

New Lead → Ready to Contact → Contacted → Responded → Interested →
Meeting Scheduled → Client, plus Not Interested and Do Not Contact.

A lead is only set to **Ready to Contact** once its Instagram account has been
verified (opened and confirmed to belong to the business).

## Lead score (0–100)

| Component | Max | How it is assigned |
|---|---|---|
| Geographic fit | 20 | Pembroke Pines 20 · Miramar/Weston/Davie/Cooper City 18 · Plantation/Hollywood/Sunrise 16 · Fort Lauderdale 14 · Miami-Dade 10 · Palm Beach 6 |
| Industry fit | 20 | Priority-1 legal (PI, immigration, family...) 20 · medical 18 · dental 16 · beauty/wellness 14 |
| Visible content opportunity | 25 | Based only on observed evidence. Unknown/unreviewed = 12 (neutral). Missing data is never scored as poor performance. |
| Fit for Klip services | 20 | Local independent firm 20 · regional multi-office 14 · national firm (likely in-house marketing) 6 |
| Verified contactability | 15 | Instagram verified 8 (search-result candidate 4) · named decision maker 4 · public phone/email 3 |

80–100 High · 60–79 Medium · below 60 Low.

## Data integrity rules

- Every value comes from a recorded source URL; blank means "not found", never "bad".
- Instagram handles not linked from the business's own site are labelled
  **Needs Verification** — confirm before sending.
- DMs make no claims about results or outcomes, and for medical practices avoid
  testimonial / before-after suggestions without compliance review.

## Integrations that would improve this

| Integration | Why |
|---|---|
| Network access to business websites (cloud environment → Network access) | Confirm firms, addresses, decision makers and the Instagram links on their own sites. Currently blocked. |
| Google Places API key | Structured business discovery (address, phone, website, rating) for any city/category. |
| Instagram Graph API (Business Discovery, via a Klip-owned Business account) | Read public business-account stats (followers, media count, recent posts) through Meta's permitted API. |
| Notion database (connected) | Optional: mirror `leads.csv` into a Notion CRM board. |
