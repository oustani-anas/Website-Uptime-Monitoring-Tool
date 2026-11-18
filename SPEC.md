# Website Uptime Monitor — Specification

> Source of truth for the build. Changes to scope or architecture are recorded in `docs/DECISIONS.md`.

## 1. Overview

A self-hosted tool where users register website URLs. A background worker checks each one on its own interval and records the HTTP status code, response time, and error reason. The dashboard shows the live status of every monitor. Each monitor's detail page shows uptime % (24h / 7d), a response-time chart, recent checks, and incident history.

Everything runs locally:

```bash
cp .env.example .env && docker compose up
```

## 2. Scope

### MVP
- Add, edit, delete, pause, and resume monitors (name, URL, check interval).
- Worker picks due monitors via `next_check_at`, with a concurrency limit and a request timeout. It follows redirects and requires **3 consecutive failures** before marking a monitor DOWN. After a failure it re-checks quickly (30 s) to confirm.
- Each check is stored with: up/down, HTTP status code, response time, error type and message.
- Dashboard: all monitors with current status, response time, uptime 24h, last checked. Auto-refreshing.
- Monitor detail: uptime % 24h and 7d, response-time chart, recent checks, incident history (down since / duration).
- URL validation and SSRF protection: only globally routable IPs are allowed. This is checked on save, on every check, and on every redirect hop.
- Data retention: checks older than `RETENTION_DAYS` (default 30) are deleted. Incidents are kept.
- Demo monitors are seeded on first start so the reviewer sees data immediately.

### Bonus (only if ≤ 12 h are used by the end of Stage 7)
- One global webhook (`WEBHOOK_URL`, Slack or Discord) on DOWN and on recovery.

### Out of scope (future work)
User accounts/auth, deployment, SSL expiry checks, keyword/body checks, public status pages, email alerts, per-monitor expected status codes, multi-region checks, frontend unit tests.

## 3. Tech stack

| Choice | Reason |
|---|---|
| FastAPI | Async-native; automatic OpenAPI docs at `/docs` for the reviewer. |
| Pydantic v2 + pydantic-settings | One mechanism for request validation and env config. |
| SQLAlchemy 2.0 (async) + asyncpg | Typed models shared by the API and the worker. |
| Alembic | Versioned, reproducible schema; runs automatically on API start. |
| PostgreSQL 16 | `FOR UPDATE SKIP LOCKED` for job claiming, `date_bin` for chart buckets, partial indexes. |
| httpx | Async client with fine-grained timeouts and manual redirect control (needed for per-hop SSRF checks). |
| Separate worker process (same image) | Slow checks never block the API; the worker can scale independently. |
| React + Vite + TypeScript | Fast builds and type safety against API shapes. |
| TanStack Query | Polling, caching, and mutation invalidation without hand-written state. |
| Tailwind CSS | Fast, consistent styling with no component-library weight. |
| Recharts | Declarative React charts; enough for a response-time chart. |
| pytest + pytest-asyncio + respx | Async tests, with HTTP mocked at the transport level. |
| Docker Compose + nginx | One-command run; production-like static frontend build. |

## 4. Architecture

```
Browser ──> frontend (nginx :8080) ──/api/*──> api (FastAPI :8000) ──> db (Postgres 16)
                                                                    ↑
                                         worker (async loop, httpx) ┘ ──> monitored sites
                                                                      └─> webhook (bonus)
```

- **db**: Postgres 16 with a named volume and a `pg_isready` healthcheck. An init script also creates the `uptime_test` database for pytest.
- **api**: The entrypoint runs `alembic upgrade head`, then the seed (if `SEED_DEMO=true` and there are no monitors), then uvicorn. Healthcheck: `GET /api/health`. Port 8000 is exposed so the reviewer can open `/docs`.
- **worker**: Same backend image, started with `python -m app.worker`. It uses `depends_on: api (service_healthy)`, which guarantees migrations have run before it starts. It has no HTTP port. On SIGTERM it finishes in-flight checks before exiting.
- **frontend**: Multi-stage build (node → nginx). nginx serves the SPA and proxies `/api` to the api service, so the browser makes same-origin requests and no CORS setup is needed.
- The API and the worker communicate **only through the database**. There is no queue or broker; Postgres row locking is enough at this scale.

**Backend layout**
```
backend/
  app/
    config.py  db.py  models.py  schemas.py  main.py  seed.py
    api/            # routers
    services/       # url_safety.py, monitors.py (edit rules), stats.py
    worker/         # main.py (process loop), scheduler.py (Worker), store.py (DB ops),
                    # checker.py, state.py, retention.py, notify.py (bonus)
  alembic/
  tests/
```

**Frontend layout:** `frontend/src/{api/, hooks/, pages/, components/}`

## 5. Database schema

### monitors
| column | type | notes |
|---|---|---|
| id | bigserial PK | |
| name | varchar(100) not null | |
| url | varchar(2048) not null | normalized |
| interval_seconds | int not null | CHECK in (30, 60, 300, 900, 3600) |
| is_paused | bool not null default false | |
| status | enum `monitor_status` (`pending`, `up`, `down`) default `pending` | confirmed state |
| consecutive_failures | int not null default 0 | |
| failing_since | timestamptz null | time of the first failure in the current streak |
| last_checked_at | timestamptz null | |
| last_status_code | int null | denormalized for a cheap dashboard query |
| last_response_time_ms | int null | |
| last_error_type | enum `error_type` null | |
| next_check_at | timestamptz not null default now() | |
| created_at / updated_at | timestamptz not null | |

Index: `(next_check_at) WHERE is_paused = false`.

### checks
| column | type | notes |
|---|---|---|
| id | bigserial PK | |
| monitor_id | bigint FK → monitors ON DELETE CASCADE | |
| checked_at | timestamptz not null | |
| is_up | bool not null | |
| status_code | int null | |
| response_time_ms | int null | time to response headers |
| error_type | enum `error_type` null | `timeout`, `dns`, `connection`, `ssl`, `http_4xx`, `http_5xx`, `too_many_redirects`, `blocked_address`, `unknown` |
| error_message | varchar(500) null | |

Indexes: `(monitor_id, checked_at)` for detail queries and `(checked_at)` for retention. Postgres scans a B-tree backwards for `ORDER BY checked_at DESC`, so the index doesn't need to be declared DESC.

### incidents
| column | type | notes |
|---|---|---|
| id | bigserial PK | |
| monitor_id | bigint FK → monitors ON DELETE CASCADE | |
| started_at | timestamptz not null | = `failing_since` (the first failure, not the confirmation) |
| resolved_at | timestamptz null | null = ongoing |
| error_type | enum `error_type` null | cause at confirmation |
| error_message | varchar(500) null | |

A partial unique index `(monitor_id) WHERE resolved_at IS NULL` allows at most one open incident per monitor.

### Display status (derived, not stored)
- `paused` if `is_paused`
- `failing` ("Unstable", amber) if `status != down` and `consecutive_failures > 0`
- otherwise the value of `status`

## 6. Check logic

### Scheduling loop (every `WORKER_POLL_SECONDS` = 2)
1. **Claim** in one short transaction:
   ```sql
   SELECT ... FROM monitors
   WHERE is_paused = false AND next_check_at <= now()
   ORDER BY next_check_at LIMIT :batch
   FOR UPDATE SKIP LOCKED
   ```
   On the claimed rows, set `next_check_at = now() + interval` as a **lease**, so a crashed worker can't cause tight re-check loops. Commit.
2. **Run** each claimed check as its own task. Concurrency is bounded by claiming only `WORKER_CONCURRENCY (20) − checks in flight` monitors per tick (DECISIONS D16). This has the same effect as a semaphore, but no monitor is ever leased while it waits for a slot.
3. **Record** each result in its own transaction: insert the check, apply the state transition, open or close an incident, and set the final `next_check_at`.

`SKIP LOCKED` keeps multiple worker replicas safe, even though one replica is the default.

**Liveness requirement:** the scheduling loop must never block waiting for a whole batch of checks to finish. Each check runs as its own task and records its result when it completes. The loop keeps ticking (and touching the heartbeat file the Docker healthcheck reads, stale after 30 s) while slow checks are in flight. Before claiming more monitors, it only claims as many as there are free concurrency slots.

### A single check (`checker.py`, returns a `CheckResult`)
- Resolve the host and require **every** resolved IP to be `ip.is_global`, with IPv4-mapped IPv6 unwrapped. Otherwise → `blocked_address`.
- `GET` with `follow_redirects=False`. Redirects are followed manually up to `MAX_REDIRECTS = 5`, and each hop is re-validated. More hops → `too_many_redirects`.
- Total timeout `CHECK_TIMEOUT_SECONDS = 10`. The response is streamed and the body is never downloaded. Requests send `User-Agent: UptimeMonitor/1.0`.
- Classification:
  - 200–399 → **up**
  - 400–499 → `http_4xx`; 500+ → `http_5xx`
  - `httpx.TimeoutException` → `timeout`
  - DNS resolution failure → `dns`
  - SSL/TLS errors → `ssl`
  - other connect errors → `connection`
  - anything else → `unknown`

### State transitions (`state.py`, a pure function)
- **Success:** `consecutive_failures = 0`, `failing_since = null`. If the status was `down`, close the open incident (`resolved_at = checked_at`) and emit a *recovery* event. `status = up`.
- **Failure:** `consecutive_failures += 1`. On the first failure, set `failing_since = checked_at`. When failures reach `FAILURE_THRESHOLD = 3` and the status is not `down`: set `status = down`, open an incident with `started_at = failing_since`, and emit a *down* event.
- **Next check:**
  - `0 < failures < threshold` → `now + min(interval, RETRY_INTERVAL_SECONDS = 30)` (fast confirmation)
  - otherwise → `now + interval`. A DOWN monitor goes back to its normal interval, which keeps load predictable.

### Edits and pause
- **Pause:** close any open incident at `now`, reset `status = pending` and `consecutive_failures = 0`.
- **Resume:** `next_check_at = now`.
- **URL change:** the same reset as pause, then `next_check_at = now`.
- **Interval-only change:** `next_check_at = coalesce(last_checked_at, now) + new interval`.

### Uptime
`uptime % = count(is_up) / count(*)` over the window (24 h or 7 d), rounded to 2 decimals, or `null` if there are no checks. `avg_response_ms_24h` averages successful checks only.

### Retention
Every 60 minutes the worker deletes checks with `checked_at < now() - RETENTION_DAYS` in batches. Incidents are kept.

## 7. API endpoints (prefix `/api`)

All timestamps are UTC ISO-8601.

**`GET /api/health`** →
```json
{"status": "ok", "db": "ok"}
```
If the database can't be reached, it returns 503 with `"db": "error"`.

**`GET /api/monitors`** → dashboard list
```json
[{
  "id": 1, "name": "Example", "url": "https://example.com", "interval_seconds": 60,
  "status": "up", "display_status": "up", "is_paused": false, "consecutive_failures": 0,
  "last_checked_at": "2026-11-18T10:00:00Z", "last_status_code": 200,
  "last_response_time_ms": 142, "last_error_type": null, "uptime_24h": 99.86
}]
```

**`POST /api/monitors`**
```json
{"name": "Example", "url": "https://example.com", "interval_seconds": 60}
```
→ `201` with the monitor.

Validation rules:
- scheme must be http or https
- host is required
- no userinfo in the URL
- at most 2048 characters
- the interval must be in the allowed list
- the host must not resolve to a non-global IP. An unresolvable host is accepted, and the worker then records `dns` errors.

Example error:
```json
{"detail": [{"loc": ["body", "url"], "msg": "Private or local addresses are not allowed", "type": "value_error"}]}
```

**`GET /api/monitors/{id}`** → the monitor plus:
```json
{"stats": {"uptime_24h": 99.86, "uptime_7d": 99.95, "avg_response_ms_24h": 150, "open_incident": null}}
```

**`PATCH /api/monitors/{id}`**: partial update of `{name?, url?, interval_seconds?, is_paused?}` → `200` with the monitor. Pause and resume are `{"is_paused": true|false}`.

**`DELETE /api/monitors/{id}`** → `204`. Checks and incidents are deleted with it (cascade).

**`GET /api/monitors/{id}/checks?limit=50&before=<iso>`**
```json
[{"id": 991, "checked_at": "2026-11-18T10:00:00Z", "is_up": false, "status_code": 503,
  "response_time_ms": 88, "error_type": "http_5xx", "error_message": "HTTP 503"}]
```

**`GET /api/monitors/{id}/response-times?range=24h|7d`**: 24h uses 5-minute buckets, 7d uses 1-hour buckets (`date_bin`). Buckets are aligned to UTC boundaries. Buckets with no checks are omitted. `avg_ms` and `max_ms` are computed from successful checks only and are `null` when every check in the bucket failed.
```json
{"range": "24h", "bucket_seconds": 300,
 "points": [{"t": "2026-11-18T10:00:00Z", "avg_ms": 143, "max_ms": 210, "checks": 5, "failures": 0}]}
```

**`GET /api/monitors/{id}/incidents?limit=20`**
```json
[{"id": 3, "started_at": "2026-11-18T09:53:00Z", "resolved_at": null, "duration_seconds": 420,
  "error_type": "timeout", "error_message": "Timed out after 10s"}]
```

Unknown monitor → `404 {"detail": "Monitor not found"}`.

## 8. Frontend pages and components

- **Routing** (react-router): `/` is the Dashboard, `/monitors/:id` is the Monitor detail page.
- **Dashboard**
  - Summary bar with counts of up, down, unstable, and paused monitors.
  - "Add monitor" button.
  - Monitor table with:
    - status badge
    - name and URL
    - response time
    - uptime 24h
    - relative last-checked time
    - interval
    - row actions: pause/resume, edit, delete
  - DOWN monitors are sorted first. There is an empty state for no monitors.
  - Polls every 10 s and refetches when the window regains focus.
- **Monitor detail**
  - Header: badge, name, URL link, "Down since …" when an incident is open, and actions.
  - Stat cards: uptime 24h, uptime 7d, avg response 24h, current status duration.
  - Response-time chart with a 24h/7d toggle. Buckets that contain failures are marked red.
  - Recent checks table.
  - Incidents list: start, end or "Ongoing", duration, cause.
  - Polls every 15 s.
- **Theme:** light and dark. It follows the OS setting by default, and a header toggle saves the choice (DECISIONS D22).
- **Components:** `StatusBadge`, `MonitorFormModal` (shared for add and edit; shows API 422 errors per field), `ConfirmDialog`, `StatCard`, `ResponseTimeChart`, `ChecksTable`, `IncidentsList`, `RelativeTime`, `EmptyState`.
- **API layer:** a typed `api/client.ts` fetch wrapper and `hooks/useMonitors.ts`, whose queries and mutations invalidate the cache on success.

## 9. Staged build plan

Estimate: about 13 h, plus 1 h bonus.

| # | Stage | Est. | Done when |
|---|---|---|---|
| 0 | Interview, SPEC, docs | 1 h | SPEC.md, DECISIONS.md, and DEVLOG.md exist. |
| 1 | Backend skeleton and infrastructure | 1.5 h | `docker compose up` starts db, api, and worker, and all are healthy. `GET /api/health` returns ok (with a DB round-trip). Alembic runs on start. pytest runs in the container against `uptime_test`. |
| 2 | Models, migration, CRUD API, URL safety | 2 h | CRUD and validation work via `/docs`. Tests pass for CRUD, 404, 422, and SSRF (loopback, 10/8, 169.254, ::1, IPv4-mapped IPv6, DNS resolving to a private IP). |
| 3 | Worker: claim loop, checker, state machine, incidents, retention, seed | 2.5 h | Seeded monitors accumulate checks. The `.invalid` demo flips to DOWN about 1 min after start, and its incident has `started_at` = the first failure. Tests pass for classification (respx), transitions, retry scheduling, and retention. |
| 4 | Stats endpoints | 1 h | The uptime, buckets, checks, and incidents endpoints return correct data. Tests cover the uptime math and bucket output. |
| 5 | Frontend skeleton and dashboard | 2 h | The frontend container serves the app on :8080 and proxies `/api`. Add, edit, pause, and delete work. Status updates without a reload. Validation errors show in the form. |
| 6 | Frontend detail page | 2 h | Stats, the chart (24h/7d), checks, and incidents render for the seeded monitors. DOWN and ongoing states are visible. |
| 7 | Polish, README, docs, end-to-end pass | 1 h | A fresh clone runs with 2 commands. The README covers run, test, architecture, and future work. The docs are up to date. |
| 8 | Bonus: webhook | 1 h | With `WEBHOOK_URL` set, DOWN and recovery messages reach Slack or Discord (`WEBHOOK_KIND`). They are sent after commit with a 5 s timeout. Failures are logged and never block checks. |

At the end of every stage, `docs/DEVLOG.md` gets an entry covering time spent, what was done, issues hit, and the next step.

## 10. Testing approach

- **Run:** `docker compose run --rm api pytest`, against the `uptime_test` database. The schema is created once per test session. Each test runs inside a transaction that is rolled back afterwards.
- **Pure unit tests:**
  - `url_safety`: schemes, userinfo, IP ranges, IPv6, mapped addresses, mocked DNS.
  - `state.py` transitions:
    - pending → up
    - 1–2 failures → no incident
    - 3rd failure → DOWN + incident
    - recovery closes the incident
    - pause resets the state
  - next-check scheduling.
- **Checker tests** (respx-mocked httpx): 200, 301 → 200, redirect to a private IP → blocked, redirect loop, 404, 503, timeout, connect error, SSL error.
- **API tests** (httpx `AsyncClient` + `ASGITransport`): CRUD, PATCH semantics (a URL change resets the state), 404/422, and the stats endpoints with fixture data.
- **DB tests:** the retention delete. The claim query must skip paused monitors and monitors that are not yet due.
- **Frontend:** `tsc --noEmit` and eslint run in the build. A manual QA checklist is in the README.

## Configuration (`.env.example`)

`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`, `TEST_DATABASE_URL`, `CHECK_TIMEOUT_SECONDS=10`, `WORKER_CONCURRENCY=20`, `WORKER_POLL_SECONDS=2`, `FAILURE_THRESHOLD=3`, `RETRY_INTERVAL_SECONDS=30`, `MAX_REDIRECTS=5`, `RETENTION_DAYS=30`, `SEED_DEMO=true`, `WEBHOOK_URL=`, `WEBHOOK_KIND=discord`.

## Seed monitors
| Name | URL | Interval | Expected |
|---|---|---|---|
| Example | https://example.com | 60 s | up |
| GitHub | https://github.com | 300 s | up |
| HTTP 503 demo | https://httpbin.org/status/503 | 60 s | down (`http_5xx`) |
| DNS failure demo | https://this-site-does-not-exist.invalid | 30 s | down (`dns`; the `.invalid` TLD never resolves) |
