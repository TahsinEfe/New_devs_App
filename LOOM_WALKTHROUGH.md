# Loom walkthrough: 5–7 minutes

Before recording, pull the latest fork, run `docker compose up --build -d`, and run
`python3 scripts/smoke_revenue.py`. Keep the dashboard, the relevant source files,
and the terminal ready. Explain only checks you actually ran. Do not say Docker
integration passed if the smoke script has not passed on your computer.

## 0:00–0:40 — Introduction

“I investigated the existing revenue dashboard rather than rebuilding it. I focused
on tenant isolation, accurate reporting periods, and financial precision. I also
found a database configuration issue that was hiding failures behind mock data.”

## 0:40–1:40 — Tenant isolation

Show the original cache key in GitHub's commit diff, then the corrected key in
`backend/app/services/cache.py`.

“Both customers have a property called prop-001. Previously, Redis keyed the result
only by property ID, so the result could be reused across organizations. The new key
contains tenant ID, property ID, year, and month. The new namespace avoids reusing
old entries. Database queries also filter by tenant and verify property ownership.”

Show Sunset's Beach House Alpha, then Ocean's Mountain Lodge Beta. Refresh each.
Explain that the property selector now comes from a tenant-scoped API.

## 1:40–2:40 — The database failure behind inaccurate totals

Show `backend/app/core/database_pool.py` and the removed fallback in the commit diff.

“The pool used settings that do not exist in this Docker configuration. There were
also async pool and session-context issues. When the query failed, the service
returned fixed mock amounts, so the dashboard appeared functional while reporting
numbers unrelated to the database. I connected it to DATABASE_URL, reused the async
pool, fixed session management, and removed the financial mock fallback. A database
outage now produces a service-unavailable response instead of fake money.”

## 2:40–3:50 — Monthly reporting and timezone boundaries

Show `revenue_bounds` and `database/seed.sql`, then March/February in the UI.

“The monthly calculation was a placeholder, and the UI did not send a reporting
period. I connected monthly and annual filters through the UI, API, query, and cache.
Revenue follows the property's local check-in date. This booking at February 29th,
23:30 UTC is March 1st in Paris, so it belongs in March. The month boundaries are
constructed in the property's timezone and independently converted to UTC. This
also handles daylight-saving changes and year rollover.”

Show Sunset prop-001: March `2250.00`, four bookings; February `0.00`, zero bookings.

## 3:50–4:40 — Financial precision

Show the three sub-cent seed values and the Decimal reporting code.

“The database already stores exact NUMERIC values, but the endpoint converted them
to a float and the frontend rounded again. I preserve exact arithmetic through the
reporting boundary, round the aggregate once, and return a decimal string. These
three amounts total exactly one thousand dollars. Rounding each booking first
would lose a cent. I also avoid combining different currencies without an exchange
rate source.”

## 4:40–5:40 — Tests and closing

Show the terminal test results and, if passed, the smoke script output.

“The regression suite covers tenant cache collisions, local month boundaries,
daylight-saving transitions, decimal rounding, ownership checks, and failure paths.
I tested both provided client logins. I also guarded the frontend against old
responses arriving after a property or account changes, and fixed a local JWT
fallback that could accept an invalid token.”

“The fix stays within the existing architecture. The reporting rule is local
check-in attribution, and mixed currencies are rejected because no exchange rates
are supplied. The findings, expected seed totals, and verification commands are
documented in DEBUGGING.md.”

Copy the Loom URL after recording. Submission requires both the fork and the video;
committing code alone does not satisfy the assignment's required video deliverable.
