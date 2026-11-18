# Technical Decisions

Short records: **Context → Decision → Trade-off.** Numbered in the order they were made.

---

## D1. Separate worker process sharing the backend codebase
- **Context:** Checks are slow network I/O (up to a 10 s timeout each). The API must stay responsive.
- **Decision:** A separate `worker` container runs `python -m app.worker` from the same image as the API. The two share models and config, and communicate only through Postgres.
- **Trade-off:** There's one more container. In return, a hung check never affects the API, and there's no message broker to run.

## D2. Postgres as the job queue (`next_check_at` + `FOR UPDATE SKIP LOCKED`)
- **Context:** The worker needs to find due monitors and must never check the same one twice concurrently.
- **Decision:** Each monitor stores `next_check_at`. The worker claims due rows with `SKIP LOCKED` and pushes `next_check_at` forward as a lease.
- **Trade-off:** This doesn't scale to millions of monitors the way a dedicated queue would. It's more than enough here and adds zero infrastructure. Multiple worker replicas are safe.

## D3. UP = final status 2xx/3xx after redirects
- **Context:** We need a definition of "available".
- **Decision:** Redirects are followed (max 5). A final status of 200–399 counts as up. 4xx and 5xx count as down.
- **Trade-off:** A page that intentionally returns 401 or 403 shows as down. Per-monitor expected status codes are listed as future work.

## D4. 3 consecutive failures before DOWN, with a fast 30 s re-check
- **Context:** A single failed request is often a network blip. Alerting on it creates false alarms.
- **Decision:** DOWN is confirmed after 3 consecutive failures. While a failure streak is unconfirmed, the next check runs after `min(interval, 30 s)`. The incident's `started_at` is the time of the *first* failure.
- **Trade-off:** There's about a 1-minute confirmation delay. Without the fast re-check, a 5-minute interval would take 15 minutes to confirm. Once DOWN, the monitor returns to its normal interval, so recovery is detected within one interval.

## D5. SSRF protection: only globally routable IPs, validated on save, on every check, and on every redirect hop
- **Context:** The server makes requests to URLs that users supply. Without a guard, it could be used to probe `localhost`, the Docker network, or cloud metadata (169.254.169.254).
- **Decision:** Resolve the host and require every address to be `ipaddress.ip_address(...).is_global`, with IPv4-mapped IPv6 unwrapped. This is checked when a monitor is saved, before every check, and on every redirect hop (redirects are followed manually).
- **Trade-off / known limitation:** There is a small DNS-rebinding window (TOCTOU) between our resolution and httpx's own connect. The per-check and per-hop re-validation reduces the risk but doesn't remove it. Removing it fully would mean pinning the connection to the validated IP, which is noted as future hardening.

## D6. Fixed interval choices: 30 s, 1 m, 5 m, 15 m, 1 h
- **Context:** Free-form intervals complicate validation and load estimates.
- **Decision:** Allowed intervals are enforced by Pydantic and by a DB CHECK constraint. The UI uses a dropdown.
- **Trade-off:** Less flexible, but predictable load and simpler charts.

## D7. Retention: delete checks after 30 days (configurable), keep incidents
- **Context:** At a 30 s interval, a monitor produces about 2,880 rows per day.
- **Decision:** The worker runs a batched hourly delete driven by `RETENTION_DAYS` (default 30). Incidents are small and form the long-term history, so they are never deleted.
- **Trade-off:** Raw check detail disappears after 30 days. Downsampled rollups are future work.

## D8. Uptime is computed from checks (check-weighted)
- **Context:** Uptime % needs a definition.
- **Decision:** `count(up) / count(all)` over the window, computed at query time.
- **Trade-off:** It's simple and transparent. Fast-retry checks slightly over-weight failure periods. Time-weighted uptime based on incidents is an alternative for later.

## D9. Frontend served by nginx (multi-stage build), which proxies `/api`
- **Context:** The app should be production-minded even though it runs only locally.
- **Decision:** Vite builds static assets and nginx serves them. nginx proxies `/api` to FastAPI, so requests are same-origin and no CORS is needed.
- **Trade-off:** There's no hot reload inside Docker. Local frontend development can still use `npm run dev`.

## D10. Demo data seeded on first start
- **Context:** A reviewer opening an empty dashboard learns nothing.
- **Decision:** If `SEED_DEMO=true` and there are no monitors, seed four monitors, two healthy and two that always fail (HTTP 503, and DNS failure via the reserved `.invalid` TLD).
- **Trade-off:** The 503 demo depends on httpbin.org being reachable.

## D11. Webhook alerts (bonus): one global URL
- **Context:** Alerts are optional and must stay within the time budget.
- **Decision:** A single `WEBHOOK_URL` and `WEBHOOK_KIND` (slack|discord) in `.env`. It is sent after the DB commit with a 5 s timeout. Failures are logged and not retried.
- **Trade-off:** There is no per-monitor routing and no delivery guarantee. An outbox table would be the next step.

## D13. URL validation in two layers: format in Pydantic, DNS check in the endpoint
- **Context:** Pydantic validators are synchronous, but the SSRF check needs an async DNS lookup.
- **Decision:**
  - `validate_url_format()` contains no I/O and runs inside the Pydantic model. It checks the scheme, the host, that there are no credentials, the port, and the length, and it rejects private literal IPs.
  - `validate_monitor_url()` resolves DNS and is called by the endpoint. It raises `RequestValidationError` in the same 422 shape, so clients handle every URL error the same way.
  - The same module will be reused by the worker before every check and redirect (Stage 3).
- **Trade-off:** The validation lives in two places. The alternatives were a blocking DNS call inside Pydantic, which would stall the event loop, or no DNS check at save time.

## D14. Database-enforced invariants, no ORM relationships
- **Context:** The worker and the API both write to the same tables.
- **Decision:**
  - The allowed intervals are a CHECK constraint.
  - Deleting a monitor removes its data through `ON DELETE CASCADE`.
  - "One open incident per monitor" is a partial unique index.
  - There are no `relationship()`s. All queries are explicit, which avoids lazy-loading pitfalls in async SQLAlchemy and lets the DB do the cascades.
- **Trade-off:** Joins have to be written by hand. Bugs in either process can't corrupt these invariants.

## D15. Pausing closes any open incident; a URL change also clears the last result
- **Context:** What should downtime mean while nobody is checking?
- **Decision:** Pausing closes the open incident at the moment of pausing and resets the state to `pending`. It keeps the last result for display. A URL change does the same and also clears the last result, because it belonged to a different URL.
- **Trade-off:** An outage that is still going on while the monitor is paused isn't counted. This is the honest choice: we don't know the state while we aren't checking.

## D16. Concurrency by "claim only free slots" instead of a semaphore
- **Context:** The spec suggested `asyncio.Semaphore(20)` around the checks. With a semaphore the worker would claim a whole batch, and monitors waiting for a slot would sit leased but unchecked. The loop would also tend to wait on the batch, which delays the heartbeat.
- **Decision:** Each check is its own task. `tick()` claims `WORKER_CONCURRENCY − in_flight` monitors and returns immediately. The retention task is tracked separately, so it never takes a check slot. A test caught that it originally did.
- **Trade-off:** There's a bit more bookkeeping (a set of tasks). In return the concurrency bound is exact, leases are honest, and the loop never blocks.

## D17. Checker: manual redirects, one total deadline, no keep-alive, body never read
- **Context:** Response times should be comparable over time, and the SSRF check must cover every redirect hop.
- **Decision:**
  - Redirects are followed manually (max 5), and each hop is checked with `assert_public_host`.
  - `asyncio.timeout(CHECK_TIMEOUT_SECONDS)` wraps the entire check, so a slow redirect chain can't exceed the budget.
  - Keep-alive is disabled, so every check opens a fresh connection. Response time = time to response headers, summed over hops. The body is never downloaded (`client.stream`).
  - Error causes are found by walking the exception chain (`ssl.SSLError` → `ssl`, `socket.gaierror` → `dns`).
- **Trade-off:** Fresh TCP and TLS connections make each check slightly heavier, but they reflect what a new visitor experiences.

## D18. Stale results are discarded, not applied
- **Context:** A user can pause a monitor, change its URL or delete it while a check is running.
- **Decision:** `record_result` locks the monitor row (`SELECT … FOR UPDATE`). It drops the result if the monitor is gone or paused, or if its URL differs from the URL that was checked.
- **Trade-off:** That one check is lost, which is correct. Otherwise an old URL's result would overwrite the reset done by the API.

## D12. Migrations run on API container start; the worker waits for a healthy API
- **Context:** The reviewer should not have to run any manual setup.
- **Decision:** The API entrypoint runs `alembic upgrade head` before uvicorn. The worker `depends_on` the API with `condition: service_healthy`.
- **Trade-off:** With multiple API replicas, migrations would race. In that case they would move to a one-shot migration job. That's fine for a single local instance.
