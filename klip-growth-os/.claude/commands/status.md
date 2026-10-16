---
description: One-screen status of the live app — data freshness, last jobs, open alerts, open recommendations
---
Read-only. Using the running app at http://127.0.0.1:8765 (GET only):
- `/api/jobs` → last run per job (state, finished_at, message) and unacknowledged alerts.
- `/api/t/ryj-media/overview?days=28` → `freshness_strip`.
- `/api/t/ryj-media/recommendations` → open cards with `state_label`.
- `/api/t/ryj-media/monetization` → progress toward each YPP tier.
Answer in under 12 lines, bottom line first. Never change anything on YouTube or Instagram.
