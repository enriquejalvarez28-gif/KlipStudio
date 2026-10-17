# KLIP — Terms & Privacy gap analysis

**Status: draft for Florida counsel. Nothing here has been published.**
Prepared 17 Oct 2026 against `data/legal.json` (the live website terms).

This is an operational checklist, not legal advice. Per KLIP_FIXES §8 the
existing SimplyBook terms must not be replaced blindly — the middle column
below is deliberately blank until the SimplyBook customer-facing text is
exported, so that existing protections are preserved rather than overwritten.

## What is still needed before this can be finished

1. Export from SimplyBook.me (Settings → the customer-facing text blocks):
   Terms & Conditions, booking policies, cancellation/reschedule policy,
   waiver/release text, and any privacy language.
2. Confirm three facts that change what the terms must say:
   - **Security cameras.** Does KLIP record video in common/studio areas?
     Does any camera capture **audio**? Florida Chapter 934 regulates
     interception of oral communications, so an audio-capable system needs
     its own review. No surveillance clause has been drafted, because
     disclosing surveillance that does not exist is as wrong as omitting it.
   - **Content ownership.** What KLIP's actual policy is on footage shot in
     the studio. No ownership or licence language has been invented.
   - **Photography deliverables.** What is included per session: number of
     edited images, retouching, turnaround, and the cancellation rule when a
     specific photographer becomes unavailable.

## Terms & Conditions

| Clause required (§8) | In SimplyBook today | On the website today | Action |
| --- | --- | --- | --- |
| Booking party authority | *pending export* | Not stated | **Missing** — add |
| Guest/crew responsibility | *pending export* | Partly — "In the studio" | **Revise** — name guests, talent, vendors and crew explicitly |
| Damage responsibility | *pending export* | Partly — "In the studio" | **Revise** — extend to equipment, sets, furniture and building property |
| No smoking/vaping | *pending export* | Not stated | **Missing** — add, and name the permitted outdoor area if one exists |
| Cleaning / condition on leaving | *pending export* | Not stated | **Missing** — add, with fees only if they are actually disclosed at booking |
| Food and drinks | *pending export* | Not stated | **Missing** — add |
| Equipment use | *pending export* | Partly — "In the studio" | **Revise** — prohibit moving, rewiring, disassembly, misuse |
| Time / overtime | *pending export* | Partly — "Bookings" | **Revise** — state that setup and cleanup are inside the reserved time |
| Late arrival / no-show / cancellation | *pending export* | Yes — "Cancellations and changes" | **Keep**, then reconcile word-for-word with SimplyBook |
| Access codes | *pending export* | Not stated | **Missing** — booking party only, valid only for the reservation window |
| Occupancy / capacity | *pending export* | Not stated | **Missing** — add per-room limits |
| Children / minors | *pending export* | Not stated | **Missing** — supervision and guardian requirements |
| Prohibited / illegal activity | *pending export* | Not stated | **Missing** — include conduct affecting neighbouring tenants |
| Personal property | *pending export* | Not stated | **Missing** — add, to the extent Florida law permits |
| Parking / building rules | *pending export* | Not stated | **Missing** — add, including towing where applicable |
| Content and recording permissions | *pending export* | Partly — "Your content and ours" | **Revise** — client obtains releases for guests, talent, music, trademarks |
| KLIP production/content ownership | *pending export* | Partly — "Your content and ours" | **Hold** — needs Enrique's actual policy; do not invent rights |
| Photography / provider terms | *pending export* | Not stated | **Missing** — needs the deliverables answer above |
| Third-party platforms | *pending export* | Partly — "Payment" | **Revise** — name SimplyBook, the payment processor and Calendly |
| Force majeure / equipment failure | *pending export* | Not stated | **Missing** — remedies and reschedule limits, counsel to set them |
| Indemnity / liability / disputes | *pending export* | Partly — "Limits" | **Attorney required** before any change |
| Security cameras | *pending export* | Not stated | **Blocked** — see the three facts above |
| Affirmative acceptance at checkout | *pending export* | n/a | Enable in SimplyBook where supported |

## Privacy Policy

| Data flow (§10) | Covered today | Action |
| --- | --- | --- |
| Contact/inquiry form data | Yes — "What we collect" | Keep |
| Booking data via SimplyBook.me | Partly | **Revise** — name SimplyBook as the processor |
| Consultation data via Calendly | Not stated | **Missing** — add |
| Payment processing, and that KLIP does not store full card numbers | Not stated | **Missing** — add |
| Google Analytics | Conditional — "Services we use" | **Verify** whether it is actually enabled, then state it or drop it |
| Google Ads / Meta Pixel | Not stated | **Verify first.** Do not list a tag that is not installed |
| Cookies and consent controls | Yes — "Cookies" | Keep; revisit if a consent banner is added |
| Newsletter / email / SMS and opt-out | Not stated | **Missing** — add if marketing sends are live |
| Photographer/provider data on selection | Not stated | **Missing** — add once photographer profiles go live |
| Security-camera footage | Not stated | **Blocked** — only if cameras exist |
| How to make a privacy request | Partly — "Your choices" | **Revise** — give the exact contact route |
| Retention | Yes — "How long we keep it" | Keep |
| Third-party links/services | Partly | Keep |
| Children / minors | Yes — "Children" | **Revise** to match the services actually offered |
| Effective and updated date | `legal.effective` exists | Keep; update on publish |

**Do not claim compliance with any named privacy statute** (CCPA, GDPR, the
Florida Digital Bill of Rights) until counsel has confirmed that it applies to
KLIP's size, data practices, audience and vendors.
