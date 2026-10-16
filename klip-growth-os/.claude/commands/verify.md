---
description: Run the test suite and the live page-load health check, then report what is broken
---
1. Run the tests: `python -m unittest discover -s tests -t .` (on Windows use `.venv/Scripts/python.exe` if `python` is not the venv). Report failures with file:line.
2. Run `python tools/healthcheck.py` against the running app (brand `$ARGUMENTS`, default ryj-media). Any FAIL or SLOW line means a dashboard page will hang or go blank.
3. For a SLOW endpoint, profile the matching function in `growth_os/api.py` with cProfile against a COPY of `data/growth_os.db` (never edit the live DB), find the slow query, and check it uses an index (`EXPLAIN QUERY PLAN`). Metrics joins must include `platform` to hit the primary key.
4. Fix, re-run 1–2, and summarise in under 8 lines: what was broken, the fix, proof (test count + healthcheck line).
