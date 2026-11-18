# Development Log

One entry per working session or stage. Time is tracked against the 12–15 h budget.

| Stage | Estimate | Actual |
|---|---|---|
| 0 — Interview + spec | 1 h | _fill in_ |
| 1 — Backend skeleton & infra | 1.5 h | _fill in_ |
| 2 — Models, migration, CRUD API, URL safety | 2 h | _fill in_ |
| 3 — Worker: checks, state machine, incidents, retention, seed | 2.5 h | _fill in_ |

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
