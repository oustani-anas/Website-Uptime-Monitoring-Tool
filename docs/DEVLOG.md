# Development Log

One entry per working session or stage. Time is tracked against the 12–15 h budget.

| Stage | Estimate | Actual |
|---|---|---|
| 0 — Interview + spec | 1 h | _fill in_ |
| 1 — Backend skeleton & infra | 1.5 h | _fill in_ |
| 2 — Models, migration, CRUD API, URL safety | 2 h | _fill in_ |
| 3 — Worker: checks, state machine, incidents, retention, seed | 2.5 h | _fill in_ |
| 4 — Stats endpoints | 1 h | _fill in_ |
| 5 — Frontend skeleton & dashboard | 2 h | _fill in_ |

---

## Session 0 — Requirements interview + specification
**Goal:** Turn the client brief into an agreed, reviewable spec before writing code.

**Done**
- Interviewed on the open questions and locked in these decisions (details in `DECISIONS.md`):
  - UP = 2xx/3xx after redirects (D3)
  - 3 failures with a fast 30 s re-check before DOWN (D4)
  - Strict SSRF: validate on save, on every check, and on every redirect hop (D5)
  - Fixed intervals (D6)
  - 30-day retention (D7)
  - nginx-served frontend (D9)
  - Seeded demo monitors (D10)
  - Single global webhook as the bonus (D11)
- Wrote `SPEC.md` (10 sections, staged build plan with "done when" criteria) and `DECISIONS.md`.

**Next:** Stage 1, the backend skeleton and infrastructure.

---

## Stage 1 — Backend skeleton & infrastructure
**Goal:** A running, healthy `db` + `api` + `worker` stack and a working test harness, with no business logic yet. (The frontend service is added in Stage 5.)

**Done**
- `docker-compose.yml`:
  - **db:** Postgres 16 with a `pg_isready` healthcheck and a named volume. `db/init/` creates `uptime_test`.
  - **api:** waits for the db to be healthy. Its healthcheck calls `/api/health`.
  - **worker:** waits for the api to be healthy, which means migrations have been applied. Its healthcheck is a heartbeat file the loop touches on every tick, so a hung loop shows up as unhealthy.
- `backend/Dockerfile`: one `python:3.12-slim` image for both api and worker (D1). It runs as a non-root user. The dependency layer is cached separately from the code.
- `app/config.py`: a pydantic-settings `Settings` class. Every tunable from `.env.example` lives here, and the API and worker share it.
- `app/db.py`: async engine with `pool_pre_ping`, a session factory, and a `get_session` dependency (overridden in tests).
- `app/api/health.py`: `GET /api/health` runs `SELECT 1`. It returns **503** if the DB is unreachable, so Docker health reflects real usability.
- Alembic, async `env.py`. The DB URL comes from settings, not from `alembic.ini`. `entrypoint-api.sh` runs `alembic upgrade head` before uvicorn (D12).
- `app/worker/main.py`, the loop skeleton:
  - waits for the DB
  - calls `tick()` every `WORKER_POLL_SECONDS` (empty until Stage 3)
  - catches and logs tick exceptions so one bad iteration never kills the process
  - stops immediately on SIGTERM/SIGINT through an `asyncio.Event`
- Tests (`tests/conftest.py`):
  - The session-scoped engine creates the schema from the models on `uptime_test`.
  - Each test runs in an outer transaction that is rolled back. `join_transaction_mode="create_savepoint"` means code under test can call `commit()`.
  - Safety guard: abort if `TEST_DATABASE_URL == DATABASE_URL`.

**Verification**
- `cp .env.example .env && docker compose up -d --build`: all 3 services report `healthy`.
- `curl localhost:8000/api/health` → `{"status":"ok","db":"ok"}`. Alembic logs show it ran.
- `docker compose run --rm api pytest`: **4 passed**:
  - health ok
  - health 503 when the DB is down
  - worker heartbeat plus prompt stop on signal
  - worker survives a failing tick
- `docker compose stop worker` takes about 0.2 s and logs "Worker stopped" (graceful shutdown, no 10 s SIGKILL).

**Issues**
- Alembic couldn't import `app` (`ModuleNotFoundError`) because it doesn't add the working directory to `sys.path`. Fixed with `prepend_sys_path = .` in `alembic.ini`.

**Decisions / notes**
- Dev dependencies (pytest, respx) are installed in the image so tests run in the same environment as the app. Trade-off: a slightly larger image. A production image would use a separate build target.
- pytest-asyncio runs all tests on one session-wide event loop, because async engines can't be shared across loops.

**Next:** Stage 2: models and the first migration, the CRUD API, and URL safety (SSRF).

---

## Stage 1 follow-up — Audit fixes
**Goal:** Review the Stage 1 files before building on them (empty files, placeholders, conventions, gaps) and fix what the audit found.

**Audit result:** No incomplete implementations. The empty `__init__.py` files and `.gitkeep` are intentional. `models.py`, `alembic/versions/`, `tick()`, and the seed hook are planned placeholders for Stages 2–3.

**Fixed**
- **One image, as intended by D1:** both services had `build:` with no shared tag, so Compose built two images. Both now use `image: uptime-monitor-backend`.
- **Dockerfile:**
  - `PYTHONPATH=/app` as insurance against the earlier Alembic import error.
  - `COPY --chown` replaces a separate `chown -R` layer.
  - `/app` is owned by the non-root user.
- **Fail fast on a hung database:** an asyncpg `connect_args={"timeout": 5}` (default was 60 s, longer than the healthcheck's 5 s).
- **Settings validation:** `Field(gt=0)` and similar bounds, plus `log_level` as a `Literal`. A bad `.env` now fails at startup instead of misbehaving at runtime. New `tests/test_config.py`.
- **Logging and shutdown:** logging setup and `engine.dispose()` moved into a FastAPI `lifespan` hook. Previously logging was an import side effect and the API never disposed the pool.
- **pytest config:** a custom hook in `conftest.py` is replaced by the built-in `asyncio_default_test_loop_scope = "session"` option.
- **`pyproject.toml`:** removed the misleading `[project]` table. The file now holds tool config only.
- **README:** a minimal Run and Test section. The full README is still planned for Stage 7.
- **SPEC §6 liveness requirement:** the worker loop must not block on a whole batch of checks. Otherwise one slow batch (up to 100 × 10 s ÷ 20 slots = 50 s) would exceed the 30 s heartbeat window and Docker would mark a healthy worker unhealthy. This is now a Stage 3 design requirement.

**Issues**
- The `COPY --chown` change caused a regression: `WORKDIR` had created `/app` as root, so pytest couldn't write `.pytest_cache`. Fixed by creating `/app` owned by the `app` user before `WORKDIR`.

**Verification:** all 3 services are healthy, there's a single `uptime-monitor-backend` image, and `pytest` shows **10 passed** with no warnings.

**Deferred**
- An empty `WEBHOOK_URL` is read as `""` rather than `None`. To handle in Stage 8.
- uvicorn `--forwarded-allow-ips` for nginx. To handle in Stage 5.

---

## Stage 2 — Models, migration, CRUD API, URL safety
**Goal:** Monitors can be created, listed, read, edited, paused, resumed and deleted through the API. User-supplied URLs can't point at internal addresses.

**Done**
- **`app/models.py`:**
  - `Monitor`, `Check` and `Incident`, plus the `MonitorStatus` and `ErrorType` enums. Enums are stored by their lowercase values.
  - A naming convention, so constraint and index names are deterministic.
  - Invariants enforced in the DB (D14): the interval CHECK, cascading foreign keys, and the partial unique index for one open incident per monitor.
  - A partial index `ix_monitors_due` on `next_check_at WHERE NOT is_paused`, ready for the worker.
- **Migration `1d5ac33eb4d3`:** autogenerated, then fixed by hand. The shared `error_type` enum is created once instead of per table, and `downgrade()` drops the enum types.
- **`app/services/url_safety.py`** (D5, D13):
  - Format checks.
  - The `is_public_ip()` rule: `is_global`, not multicast, with IPv4-mapped IPv6 unwrapped.
  - Async resolution with a 5 s timeout, and `assert_public_host()`, which requires *every* resolved address to be public.
  - An unresolvable host is allowed when saving a monitor.
- **`app/schemas.py`:**
  - The `MonitorCreate`, `MonitorUpdate`, `MonitorOut`, `MonitorDetail` and `IncidentOut` models.
  - `display_status` and `duration_seconds` are computed fields.
  - `extra="forbid"`, so unknown fields return 422.
  - PATCH rejects an explicit `null`.
- **`app/services/monitors.py`:** the edit rules from SPEC §6 (D15):
  - Pausing resets the state and closes the incident.
  - Resuming schedules an immediate check.
  - Changing the URL resets the state, clears the last result and schedules an immediate check.
  - Changing the interval reschedules from the last check.
- **`app/api/monitors.py`:** `GET` and `POST` on `/api/monitors`, plus `GET`, `PATCH` and `DELETE` on `/api/monitors/{id}`. The router stays thin. `stats.uptime_*` is `null` until Stage 4, and `open_incident` is already real.

**Verification**
- `pytest`: **77 passed**:
  - 39 for URL safety
  - 25 for the API
  - 3 for DB constraints
  - 10 from Stage 1 (config, health, worker loop)
- `alembic check` reports "No new upgrade operations detected", so the models and the migration agree.
- The downgrade → upgrade round trip works.
- Manual curl test against the running stack, with real DNS:
  - The CRUD calls and pause work.
  - `http://localhost:8000`, `http://169.254.169.254/...` and `http://db:5432` (our own Postgres container's hostname) are all rejected with 422.
  - `https://this-site-does-not-exist.invalid` is accepted.

**Issues**
- The autogenerated migration would have failed: three `CREATE TYPE error_type` statements, and enums left behind on downgrade. Fixed by hand, as described in the migration docstring.
- My first manual curl script failed because zsh doesn't word-split variables, so the header was malformed. That was a test-script problem, not an app bug.

**Notes for Stage 3**
- **Race condition:** if a user changes the URL or pauses while a check is in flight, the worker must not write the old result over the reset state. When recording a result, the worker should lock the monitor row (`SELECT ... FOR UPDATE`) and drop the result if the URL changed or the monitor was paused.
- The worker reuses `assert_public_host()` before every request and every redirect hop.

**Next:** Stage 3, the worker: claim loop, checker, state machine, incidents, retention and seed.

---

## Stage 3 — Worker: checks, state machine, incidents, retention, seed
**Goal:** The worker actually checks sites, records every result, confirms DOWN after 3 failures, opens and closes incidents, purges old data, and seeds demo monitors.

**Done** (`app/worker/`, each file with one responsibility)
- **`checker.py`:** `perform_check(url) → CheckResult`, with no DB access (D17).
  - Redirects are followed manually and every hop gets the SSRF check. A redirect to another scheme is blocked.
  - One total deadline covers the whole check. Keep-alive is off, and the body is never read.
  - Errors are classified as timeout, dns, connection, ssl, http_4xx, http_5xx, too_many_redirects, blocked_address or unknown. The function never raises.
- **`state.py`:** the pure `apply_result(state, result)` → new state, next check time, open/close incident, event.
  - Implements the 3-failure rule, the fast 30 s re-check while unconfirmed, the normal interval once DOWN, and `incident.started_at` = the first failure.
- **`store.py`:**
  - `claim_due`: one atomic `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED) RETURNING`, which also sets the lease.
  - `record_result`: locks the monitor row, discards stale results (D18), then writes the check, the state and the incident in one transaction.
- **`retention.py`:** batched deletion of checks older than `RETENTION_DAYS`. Incidents are kept.
- **`scheduler.py`:** the `Worker` class.
  - It claims only free slots (D16), and every check is its own task.
  - Retention runs at startup and then hourly, without taking a check slot.
  - `shutdown()` drains in-flight work, then cancels after the grace period.
- **`main.py`:** the process loop now drives `Worker`. The HTTP client is closed on exit.
- **`app/seed.py`** plus the entrypoint: 4 demo monitors, inserted only when SEED_DEMO=true and the table is empty.
- httpx's per-request INFO logs are silenced. The worker logs DOWN (WARNING) and RECOVERED (INFO) itself, and each check at DEBUG.

**Verification**
- `pytest`: **121 passed**. 44 of them are new in this stage:
  - state: 8
  - checker: 19
  - store: 8
  - scheduler: 5
  - retention: 2
  - seed: 2

  The worker-loop tests were rewritten.
- Real checks run from the container:
  - expired, self-signed and wrong-host certificates (badssl.com) → `ssl`, with readable messages
  - `http://github.com` → redirect → 200 up
  - httpbin 503 → `http_5xx`
  - `.invalid` → `dns`
  - `10.255.255.1` → `blocked_address`
- **Live end-to-end:**
  - The DNS demo (30 s interval) failed at 17:25:33, 17:26:03 and 17:26:34, went **DOWN on the 3rd failure**, and its incident started at **17:25:33**, the first failure.
  - The 503 demo (60 s interval) was confirmed DOWN in about 1 min thanks to the fast retry.
  - Google was UP via a redirect. The paused monitor was not checked.
- `docker compose stop worker` is immediate and logs "Worker stopped". Retention ran at startup ("deleted 0").

**Issues**
- **A real bug found by a test:** the retention task was tracked in the same set as the checks, so while it ran it used up a check slot (4 claims instead of 5). Fixed by tracking it separately and still draining it on shutdown.
- **A mock limitation:** respx replaces an exception's `__cause__` with its own `SideEffectError`, so an SSL error chain can't be simulated through it. The classifier is now unit-tested directly, and real SSL failures were confirmed against badssl.com.
- **Seed was skipped on the dev DB** because it already held user-created monitors. That's correct behaviour. Run `docker compose down -v` to see the seed on a fresh volume.

**Next:** Stage 4, the stats endpoints: uptime 24h/7d, response-time buckets, the checks list and the incidents list.

---

## Stage 4 — Stats endpoints
**Goal:** All the availability numbers the frontend needs, served by the API. This completes the backend MVP.

**Done**
- **`app/services/stats.py`** (D19):
  - `uptime_24h_by_monitor`: one grouped query for the dashboard.
  - `monitor_stats`: uptime 24h and 7d plus the 24h average response time, in one query with `FILTER`.
  - `response_time_buckets`: Postgres `date_bin`. 24h uses 5-minute buckets and 7d uses 1-hour buckets, aligned to UTC. Empty buckets are omitted, and the averages count successful checks only.
  - `recent_checks`: newest first, with `before` for paging.
  - `incident_history`: newest first.
- **New endpoints:**
  - `GET /api/monitors/{id}/checks?limit=1..500&before=<iso>`
  - `GET /api/monitors/{id}/response-times?range=24h|7d`
  - `GET /api/monitors/{id}/incidents?limit=1..100`
- **Existing endpoints:** `GET /api/monitors` now fills `uptime_24h`. `GET /api/monitors/{id}` fills `stats.uptime_24h`, `uptime_7d` and `avg_response_ms_24h`.
- New schemas: `CheckOut`, `ResponseTimePoint`, `ResponseTimes`.

**Verification**
- `pytest`: **134 passed**. The 13 new tests in `test_stats_api.py` cover:
  - uptime math: 75 % over 24h and 37.5 % over 7d, checks older than 7 days ignored, rounding (66.67), `null` with no data
  - failures excluded from the average
  - the dashboard's per-monitor uptime
  - bucket grouping, alignment, ordering and omitted empty buckets
  - paging with `before`
  - limit bounds
  - incident order and durations, both ongoing and resolved
  - 404 and 422 cases
- Live, against real worker data:
  - Google 100 % with an average of 703 ms. The DNS demo 0 % with an open incident since 17:25:33 (about 26 min).
  - The chart returns 5-minute buckets with real averages and maxima.
  - `range=1y` → 422 "Input should be '24h' or '7d'".

**Issues:** none. All tests passed on the first run.

**Status:** the backend MVP is complete: CRUD, SSRF protection, worker, incidents, retention, seed and stats.

**Next:** Stage 5, the frontend dashboard. The remaining backend items are the webhook bonus (Stage 8) and the uvicorn proxy setting when nginx is added (Stage 5).

---

## Stage 5 — Frontend skeleton & dashboard
**Goal:** The app runs in Docker on :8080 behind nginx. The dashboard shows live status, and monitors can be added, edited, paused, resumed and deleted from the UI.

**Done**
- **Infrastructure:**
  - `frontend/Dockerfile` is a multi-stage build: `npm ci`, then lint, then `tsc --noEmit`, then `vite build`, then nginx.
  - `nginx.conf` serves the SPA with a fallback for deep links, proxies `/api`, `/docs` and `/openapi.json` to FastAPI (same origin, so no CORS), gzips responses, and caches hashed assets for a year.
  - A `frontend` service in Compose, with a healthcheck, waits for a healthy API.
  - The Vite dev server proxies `/api` for local hot-reload development.
- **API layer:**
  - `api/types.ts` mirrors the backend schemas.
  - `api/client.ts` is a typed fetch wrapper. Its `ApiError` maps FastAPI 422 details to form fields.
  - `hooks/useMonitors.ts` holds the queries (polling: list every 10 s, detail every 15 s) and the mutations, which invalidate the cache.
- **Dashboard:**
  - Summary tiles.
  - A sorted table (down, then unstable, up, checking, paused) that becomes cards on phones.
  - Response times are coloured fast, ok or slow. A failed check is always red and shows the error type.
  - "Updated Xs ago" plus manual refresh.
  - Error banner that keeps the last data on screen, a loading skeleton and an empty state.
- **Actions:** `useMonitorActions` provides add, edit, delete and pause in one place and will be reused by the detail page.
  - Add and edit share one modal. 422 errors show under the matching field. Edit sends only the fields that changed.
  - Delete asks for confirmation.
  - **Toasts** appear for add, edit, pause, resume and delete (requested addition #4).
- **`tabular-nums`** on every ms, % and count value (requested addition #3).
- The detail page so far has routing, a header and a 404 state. The rest arrives in Stage 6.
- The deferred uvicorn proxy-header item is resolved without code. Nothing uses the client IP, and nginx forwards `Host` with its port, so any redirect FastAPI generates points back to :8080.

**Verification**
- `npm run lint` and `npm run build` (strict TypeScript) are clean, and the Docker build runs both.
- nginx: `/` and the deep link `/monitors/3` return the SPA (200), `/api/health` and `/docs` are proxied, assets are gzipped and served with `Cache-Control: public, immutable`.
- **Visual checks** with headless Chrome screenshots: the desktop table, a phone at 390 px (via an iframe, because headless Chrome enforces a minimum window width of about 500 px), the detail header and the detail 404 state.
- **Real UI flow**, driven through the Chrome DevTools protocol with a small Node script (no new dependencies), against the real API:
  1. Open Add, submit `http://localhost:5432`, and "Private or local addresses are not allowed" appears under URL.
  2. Add `https://example.org`, and the toast and a "Checking…" row appear.
  3. Pause it, and a toast appears.
  4. Delete it, the confirmation shows, then a toast, and the row is gone.

  The test monitor was removed afterwards.
- Backend is unchanged: 134 passed.

**Issues / fixes from the visual review**
- The HTTP 503 demo's response time was green because it was fast. A failed check is now always red.
- The detail page's 404 was retried once before showing. Queries no longer retry 4xx errors.
- The mobile card showed "— — 24h —" for a monitor with no checks. It now says "No checks yet". An empty uptime dash is muted like the other empty values.
- ESLint 9 was end of life, so it was upgraded to 10, with `eslint-plugin-react-hooks` 7 (D21).

**Next:** Stage 6, the detail page:
- stat cards
- the 24h uptime bar (requested addition #1)
- the response-time chart with the "No successful checks in this period" state (requested addition #2)
- recent checks with "Load more"
- incidents

### Stage 5 addition — Dark mode (requested)
- `dark:` variants were added to every component, using one consistent mapping: slate-950 page, slate-900 cards, softer status tints, and an inverted primary button.
- `hooks/useTheme.ts` and the header `ThemeToggle`: follow the OS by default, react to live OS changes, and remember a manual choice in `localStorage`. An inline script in `index.html` prevents a flash on load (D22).
- **Verified** in headless Chrome over the DevTools protocol:
  - With the OS emulated as dark, the page renders dark.
  - The toggle switches to light and saves `"light"`.
  - After a reload, the saved choice wins over the OS.
  - With the OS emulated as light, the page renders unchanged.
- **Fix from the visual review:** in dark mode the modal blended into the page. It now has a subtle ring and a darker backdrop.
- Lint and build are clean.

### Stage 5 review fixes (feedback before Stage 6)
1. **Duplicate URLs** (D23):
   - The API returns **409 "This URL is already monitored"** on create and on a URL-changing PATCH. The form shows it under the URL field without frontend changes.
   - The root path is normalized (`https://x.com/` → `https://x.com`).
   - 9 new tests: duplicates after normalization (case, trailing `/`, fragment), a different scheme or path allowed, a PATCH to another monitor's URL rejected, a PATCH with its own URL allowed. `pytest`: **143 passed**.
   - The dev DB already has one duplicate pair (#3 "Google" and #8 "google"). It was left for the user to remove, because the check doesn't delete existing data.
2. **Tooltips:**
   - `IconButton` now shows an instant styled tooltip on hover and on keyboard focus. Native `title` attributes were removed, so there are no double tooltips.
   - Short visible text ("Pause", "Resume", "Edit", "Delete", "Dark mode", "Refresh"), with the full `aria-label` for screen readers ("Delete Google").
   - The refresh button now uses `IconButton` too.
3. **Light mode review** in headless Chrome with the OS emulated as light:
   - The dashboard, the row tooltip, the theme-toggle tooltip and the add form showing the duplicate error all render correctly.
   - The phone width (390 px) is clean.
   - No native `title` attributes remain.

### Search and filters (requested before deployment)
- **What was added:**
  - `lib/filter.ts`: `filterMonitors()` and `parseStatusFilter()`.
  - `components/MonitorToolbar.tsx`: a search box with a clear button, plus status chips (All, Up, Down, Unstable, Paused) with counts and `aria-pressed`.
  - The Dashboard keeps the filter state in the URL via `useSearchParams` (D24).
  - A "No monitors match" empty state with a **Clear filters** button.
- **Verified** by driving the real UI in headless Chrome over the DevTools protocol:
  - **Down** shows exactly the 5 down monitors, with `?status=down`.
  - Search by name ("goo" → google) and by URL ("aoustani.com") both work.
  - Search and a chip combine (`?q=a&status=up` → 3 rows).
  - The filter survives a reload.
  - A query with no match shows the empty state, and **Clear filters** restores all 11 rows and a clean URL.
  - Screenshots are clean in light, in dark, and on a 390 px phone, where the chips wrap under the search box.
- **Test-harness issue:** a headless Chrome from an earlier run hadn't exited and kept the debugging port. Later scripts connected to it, along with its stored theme choice, so a "dark" screenshot came out light. The stale process was stopped and the screenshot retaken in a fresh profile. The app was behaving correctly by honouring a saved choice.
- Lint and the strict build are clean. No backend change.
