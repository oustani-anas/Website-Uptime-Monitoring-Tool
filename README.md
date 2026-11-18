# Website Uptime Monitoring Tool

A self-hosted web app that monitors websites: periodic health checks, response times, uptime stats, and incident history.

> 🚧 Work in progress. The backend is complete and the frontend dashboard is in place; the monitor detail page comes next (see `docs/DEVLOG.md`). The full README comes in Stage 7.

## Run

Requires Docker with Docker Compose v2.

```bash
cp .env.example .env && docker compose up
```

- **App: http://localhost:8080**
- API docs (OpenAPI): http://localhost:8080/docs (also directly on http://localhost:8000/docs)
- API health: http://localhost:8080/api/health

### Frontend development (optional)
With the stack running, `cd frontend && npm install && npm run dev` serves the app with hot reload on http://localhost:5173. It proxies `/api` to the API on port 8000.

## Test

```bash
docker compose run --rm api pytest
```

Tests use a separate `uptime_test` database, which is created automatically the first time the `db` volume is initialized. If you have a volume from an older checkout, recreate it with `docker compose down -v`.

## Documentation

- [`SPEC.md`](SPEC.md): scope, architecture, schema, check logic, API, build plan
- [`docs/DECISIONS.md`](docs/DECISIONS.md): technical decisions and trade-offs
- [`docs/DEVLOG.md`](docs/DEVLOG.md): progress log per stage
