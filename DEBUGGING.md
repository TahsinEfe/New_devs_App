# Property Revenue Dashboard: findings and verification

The dashboard could reuse another tenant's cached revenue, silently replace real
database data with mock totals, and label an all-time report as monthly. The fixes
keep the existing FastAPI, SQLAlchemy, Redis, and React structure.

## Findings

| Finding | Evidence in the original code | Fix |
| --- | --- | --- |
| Cross-tenant cache collision | `services/cache.py` used `revenue:{property_id}`. Both tenants own a different `prop-001`. | Versioned key includes tenant, property, year, and month; cached payload identity is checked. Legacy keys are ignored. |
| Database errors disguised as financial data | `database_pool.py` referenced absent `supabase_db_*` settings instead of `DATABASE_URL`, used a synchronous `QueuePool` with an async engine, and returned a session via an unawaited coroutine. `reservations.py` caught all exceptions and substituted hard-coded totals. | Use the configured async database URL and async-compatible engine pool, share one pool, return a session context manager synchronously, and close it on shutdown. Database failure returns HTTP 503 instead of invented revenue. |
| Monthly report was not implemented | `calculate_monthly_revenue` returned `Decimal('0')`; the dashboard summary only requested all-time totals. | Implement monthly and annual query periods and connect the UI selectors through the API and cache. All-time remains supported when no period is supplied. |
| Incorrect local calendar boundaries | Original monthly boundaries were naive datetimes. The Paris seed booking at `2024-02-29 23:30 UTC` is `2024-03-01 00:30` locally. | Read the tenant-owned property's IANA timezone, construct both local boundaries, and convert each independently to UTC. Query `[start, end)`; DST and December rollover are covered. |
| Financial precision was discarded at the API boundary | The database stores `NUMERIC(10,3)` and the service used Decimal, but the endpoint converted it to float and React rounded it again. | Sum NUMERIC values in SQL, use Decimal, round once with `ROUND_HALF_UP` at the report boundary, and return a two-decimal string. Display the string directly. This removes a precision hazard; no claim is made that every original seed total necessarily exhibits a float error. |
| Tenant-unaware property selector and stale responses | React hard-coded properties from both tenants and did not guard against late request completion. | Load only tenant-owned properties from the backend, clear report state on account/property/period changes, and ignore superseded responses. |
| Authentication could fail open in challenge mode | Failed JWT verification could reach a mock client that decoded without checking signatures. Unknown users defaulted to `tenant-a`. | Verify local JWT signature and expiry before cache lookup, use verified server-controlled tenant claims, reject missing tenant context, and remove the default tenant fallback. `/auth/me` preserves the authenticated tenant. |
| Frontend tenant handling did not match the supplied tokens | SecureAPI omitted `app_metadata.tenant_id`, accepted only UUIDs, and the supplied tokens use `tenant-a` / `tenant-b`. | Read app metadata, support the supplied tenant IDs, synchronize the cached token with auth changes, decode base64url claims, and reject responses after session changes. Backend remains the authorization authority. |

## Reporting rules and limits

- Revenue is attributed to the **property-local check-in date**, consistent with the
  original query's intended business rule. It is not nightly accrual or payment-date reporting.
- Monthly: pass `month` and `year`. Annual: pass `year`. All-time: omit both.
- Round the final aggregate, not each reservation. `333.333 + 333.333 + 333.334`
  is exactly `1000.000`, reported as `1000.00`.
- Preserve the actual currency for a single-currency report. Mixed currencies
  return HTTP 422 because no conversion rates are provided. Empty periods default
  to USD, matching the supplied seed; a property-level base currency would be needed
  to label empty reports differently.
- Unknown or other-tenant properties return HTTP 404 without exposing ownership.
- Redis failure falls back to the real database. Database failure returns HTTP 503.
- Cache TTL remains five minutes; no new reservation write path is introduced.
- Static challenge credentials and the supplied development secret are retained.
  This exercise does not rebuild the application's production authentication system.

## Expected results for the supplied March 2024 seed

| Tenant | Property | Revenue (USD) | Reservations |
| --- | --- | ---: | ---: |
| Sunset / tenant-a | prop-001 / Beach House Alpha | 2250.00 | 4 |
| Sunset / tenant-a | prop-002 / City Apartment Downtown | 4975.50 | 4 |
| Sunset / tenant-a | prop-003 / Country Villa Estate | 6100.50 | 2 |
| Ocean / tenant-b | prop-001 / Mountain Lodge Beta | 0.00 | 0 |
| Ocean / tenant-b | prop-004 / Lakeside Cottage | 1776.50 | 4 |
| Ocean / tenant-b | prop-005 / Urban Loft Modern | 3256.00 | 3 |

Sunset prop-001's February 2024 report is `0.00`; its local March report includes
the UTC-February booking. Annual 2024 and all-time reports match March for this seed.

## Verification

Completed in the development workspace:

- 17 Python regression tests covering period boundaries/DST, Decimal rounding,
  tenant-scoped queries, absent properties, currency handling, cache segregation,
  Redis/database failures, provided client logins, and invalid local tokens.
- Full FastAPI app import, startup/shutdown, and both client login → `/auth/me` flows.
- TypeScript syntax/transpilation checks for changed frontend files.
- React rendering checks for an old property response arriving late, account-change
  state clearing, and recovery from a previous error.

The automated Python suite mocks database/Redis I/O. It is **not** a substitute for
running the full Docker stack. Docker is unavailable in the development workspace;
the real PostgreSQL/Redis smoke test and full frontend build must be run locally.

```bash
docker compose up --build -d
python3 scripts/smoke_revenue.py
docker compose exec backend python -m unittest discover -s tests -v
```

The smoke script uses both supplied credentials, warms and alternates the same-ID
cache, validates all seeded totals and tenant property lists, checks February,
annual and all-time reports, and confirms unauthorized/invalid requests are denied.
It expects the unchanged supplied seed database.

For a browser walkthrough, open `http://localhost:3000`, use March 2024, log in as
Sunset then Ocean, select the shared property ID, and refresh each account.
Record the required Loom video and submit its URL together with the fork URL.
