<p align="right">
  <a href="CONTRIBUTING.md"><b>English</b></a> · <a href="README_ru.md">Документация на русском</a>
</p>

# Contributing to TG Story Watcher

Thanks for your interest in contributing! This document covers local
development setup, code conventions, and an extended self-hosting/deployment
guide. For end-user documentation, installation, configuration reference, and
troubleshooting see [README.md](README.md) / [README_ru.md](README_ru.md).

> The project's primary deployment target is **Docker Compose**. Manual launch
> is supported for development only — the worker watchdog, healthchecks, and
> volume layout are designed around the Compose setup.

## Table of Contents

- [Development Setup](#development-setup)
- [Environment Variables](#environment-variables)
- [Project Structure](#project-structure)
- [Auto-Configuration Architecture](#auto-configuration-architecture)
- [Code Conventions](#code-conventions)
- [How to Contribute](#how-to-contribute)
- [Testing](#testing)
- [Self-Hosting Deployment Guide](#self-hosting-deployment-guide)
- [License](#license)

## Development Setup

### Prerequisites

- Python 3.12+
- Node.js 18+ and npm
- PostgreSQL 16 (or SQLite for quick local runs)
- Redis 7
- Telegram API credentials (https://my.telegram.org)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Quick local run on SQLite (no Postgres required):

```bash
export DATABASE_URL=sqlite:///./data/storywatcher.db
export TELEGRAM_API_ID=...
export TELEGRAM_API_HASH=...
uvicorn app.main:app --reload --port 9000
```

With local Docker Postgres:

```bash
export DATABASE_URL=postgresql+psycopg2://storywatcher:storywatcher@localhost:5432/storywatcher
uvicorn app.main:app --reload --port 9000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on http://localhost:3000 and proxies `/api` to the backend
(http://localhost:9000). No CORS issues in dev mode.

### Running the Worker

The background worker handles story sync, queue processing, analytics, and
adaptive discovery as a **single process** (Telethon session files cannot be
shared safely across processes):

```bash
cd backend
python -m app.workers.combined
```

> ⚠️ Do not run multiple workers that open the same Telethon session files.

## Environment Variables

Copy `.env.example` to `.env` and fill in at minimum:

```dotenv
TELEGRAM_API_ID=your_id
TELEGRAM_API_HASH=your_hash
STORYWATCHER_API_TOKEN=your_token
SECRET_KEY=your_secret
DATABASE_URL=sqlite:///./data/storywatcher.db
REDIS_URL=redis://localhost:6379/0
```

Worker / infrastructure settings (all optional; defaults shown):

| Variable | Default | Description |
|---|---|---|
| `STORYWATCHER_SYNC_INTERVAL` | `30` | Story sync cycle interval (seconds) |
| `STORYWATCHER_WORKER_POLL` | `1` | Worker poll interval (seconds) |
| `STORYWATCHER_ANALYTICS_INTERVAL` | `3600` | Full archive analytics interval (seconds) |
| `WORKER_STALL_TIMEOUT` | `240` | Main-loop stall timeout before the worker exits (Docker restarts it) |
| `WORKER_HEARTBEAT` | `/tmp/worker_heartbeat` | Heartbeat file path for the worker healthcheck |
| `WORKER_MAX_ERRORS` | `10` | Consecutive cycle errors before exit |
| `POOL_SIZE` / `POOL_MAX_OVERFLOW` / `POOL_TIMEOUT` / `POOL_RECYCLE` | 10 / 20 / 10s / 1800s | PostgreSQL pool tuning in `backend/app/db.py` |

See [README.md](README.md#environment-variables) for the full user-facing list.
`pool_timeout` is intentionally small (10s): a lingering synchronous borrow
would otherwise block the worker event loop (queue "wedge" protection).

## Project Structure

```
TG-Story-Watcher/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers (auth, user-auth, accounts, ...)
│   │   ├── analytics/      # Analytics service
│   │   ├── filters/        # Filter engine for story processing
│   │   ├── queue/          # Queue processor (per-request RPC timeouts)
│   │   ├── services/       # Business logic (settings with auto-derivation)
│   │   ├── stories/        # Story monitoring and discovery
│   │   ├── telegram/       # MTProto client (Telethon)
│   │   ├── workers/        # queue_worker, scheduler, combined (entry point)
│   │   ├── config.py       # pydantic-settings configuration
│   │   ├── db.py           # SQLAlchemy engine and sessions
│   │   ├── main.py         # FastAPI app entry point
│   │   ├── models.py       # ORM models
│   │   └── multitenancy.py # User token creation/verification
│   ├── tests/              # Integration tests (pytest + SQLite)
│   │   ├── conftest.py
│   │   ├── test_stories.py
│   │   ├── test_dashboard.py
│   │   ├── test_analytics.py
│   │   ├── test_settings_service.py
│   │   └── test_scheduler_rotation.py
│   ├── migrate_limits_derived.py  # Migration: recalculate derived settings
│   ├── Dockerfile
│   ├── requirements.txt
│   └── healthcheck.sh
├── frontend/
│   ├── app/                # Next.js App Router pages
│   ├── components/         # UI components (Sidebar, PlacesMap, ui.tsx)
│   ├── lib/                # api.ts, theme.tsx, i18n.tsx, format.ts, hooks
│   ├── Dockerfile
│   └── package.json
├── docker/
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md / README_ru.md
```

## Auto-Configuration Architecture

The system derives all technical parameters from a single user input:
**Views per day** (50–12,000).

### Key Files

| File | Purpose |
|---|---|
| `backend/app/services/settings_service.py` | `compute_all_from_daily()` — derives limits, view delays, queue parallelism, monitoring interval |
| `backend/app/workers/scheduler.py` | `_compute_adaptive_search_params()` — dynamic search interval and result count |
| `backend/app/workers/queue_worker.py` | Recomputes rate limits from daily on each cycle; claims/processes queue tasks |
| `backend/app/queue/processor.py` | Executes the MTProto view request with a per-request timeout (`RPC_TIMEOUT`) |
| `frontend/app/settings/page.tsx` | Single slider UI, instant recalculation on change |
| `backend/migrate_limits_derived.py` | Migration script to recalculate all derived settings |

### Queue Worker Design (important)

`backend/app/workers/queue_worker.py` drains the queue for one account at a time:

- DB sessions are opened **inside** the worker semaphore so the connection pool
  can never be exhausted by 100 concurrent coroutines (see K-01 in
  `audit-report-technical.md` if present).
- `parallel` is hard-capped at 4 and `max_tasks` at 100 regardless of settings.
- Every task runs under `asyncio.wait_for(task_timeout)`; timed-out tasks are
  returned to `PENDING` (with a 30s delay) or moved to `FAILED` once the
  auto-retry budget is exhausted.
- Stale-`PROCESSING` recovery runs in `run_once()` for every candidate account
  *before* draining.
- `parallel`/`max_tasks`/`processing_timeout`/`max_auto_retries` come from
  `SettingsService` per user.

### Adding New Derived Parameters

1. Add the formula to `compute_all_from_daily()` in `settings_service.py`.
2. Add the key to the appropriate section dict in the return value.
3. Update the frontend to display the computed value for instant UI feedback.
4. Run `migrate_limits_derived.py` to update existing users.

## Code Conventions

### Backend (Python)

- **Formatter/Linter:** follow the existing style. Some modules use compact
  class definitions — match the surrounding code when editing.
- **ORM:** SQLAlchemy 2.0 (`Mapped[type]`). New models go in `backend/app/models.py`.
- **API schemas:** Pydantic v2 models in `backend/app/api/schemas.py` or inline
  in route files. Prefer the standalone `model_validator` import from `pydantic`
  (do not rely on `BaseModel.model_validator` attribute).
- **Auth:** user tokens are `user.<base64(payload)>.<hmac>` validated by
  `multitenancy.py`; routes use the `X-API-Token` header via `deps.py`.
- **Database:** `init_db()` creates tables on startup. For schema changes modify
  `models.py` (Alembic can be added later). No raw SQL — use the ORM.
- **Settings derivation:** always derive auto-computed parameters from
  `views_per_day` in `compute_all_from_daily()`.
- **Worker safety:** wrap Telegram RPC calls in `asyncio.wait_for`; never leave
  a task without a timeout (see `processor.py`, `queue_worker.py`).

### Frontend (TypeScript/React)

- **Framework:** Next.js 14 App Router (`"use client"` pages).
- **Styling:** Tailwind CSS using existing component patterns from `components/ui.tsx`.
- **State:** React hooks (`useState`, `useEffect`). No external state library.
- **API calls:** through `lib/api.ts` (`api.get`, `api.post`, etc.).
- **Theme/i18n:** `lib/theme.tsx` and `lib/i18n.tsx` (+ `lib/translations/`).
- **Settings UI:** auto-computed values use `readonly` fields; only
  user-configurable parameters get sliders.

### Git

- Keep commits focused — one logical change per commit.
- Write clear commit messages.
- Do not commit `.env`, session files, or `node_modules`.

## How to Contribute

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Make your changes.
4. Test locally (see below).
5. Commit with a clear message.
6. Push and open a Pull Request.

### What to Work On

- Bug fixes
- New features (open an issue first for large changes)
- Documentation improvements
- Test coverage
- UI/UX improvements

## Testing

### Backend (Integration Tests)

```bash
cd backend
pip install -r requirements.txt
pip install pytest httpx
python -m pytest tests/ -v
```

The suite uses in-memory SQLite databases (no PostgreSQL required) and covers:

- **Stories endpoint** — DB-level pagination, sort order, view count
  aggregation, like annotations, filters, authentication
- **Dashboard / Stats endpoints** — aggregated charts, card/totals, period
  parameter, empty states, 401
- **Analytics overview** — viewer aggregation, period filtering, top stories
- **Settings service** — `compute_all_from_daily` caching, defaults, recompute
- **Scheduler rotation** — offset dict isolation for hashtags/locations/venues

**54 tests** total. Run `python -m pytest tests/ -v` for detailed output.

### Manual Testing

1. Start the backend: `uvicorn app.main:app --reload --port 9000`
2. Start the worker: `python -m app.workers.combined`
3. Start the frontend: `cd frontend && npm run dev`
4. Open http://localhost:3000, register, log in, connect a Telegram account,
   and test the flow.

## Self-Hosting Deployment Guide

The **recommended** way to deploy is Docker Compose (see
[README.md](README.md#installation-with-docker-recommended) for the quick
start). This section adds production-grade details.

### Minimum Server Requirements

- **CPU:** 1 vCPU (2+ recommended)
- **RAM:** 1 GB (2+ recommended)
- **Storage:** 10 GB+
- **OS:** Ubuntu 22.04+, Debian 12+, or any Linux with Docker
- **Ports:** 8081 (web UI, configurable via `WEB_PORT`)

### Step 1: Install Docker

```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

### Step 2: Get the Code

```bash
git clone https://github.com/devlewicki/TG-Story-Watcher.git
cd TG-Story-Watcher
```

### Step 3: Configure

```bash
cp .env.example .env
```

Edit `.env`. For production, generate strong secrets:

```dotenv
# Required
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# Generate with: openssl rand -hex 32
STORYWATCHER_API_TOKEN=$(openssl rand -hex 32)
SECRET_KEY=$(openssl rand -hex 32)

# PostgreSQL (change defaults for production!)
POSTGRES_USER=storywatcher
POSTGRES_PASSWORD=use-a-strong-password-here
POSTGRES_DB=storywatcher

# Web port
WEB_PORT=8081
```

> **Important:** change the default PostgreSQL credentials for any non-local
> deployment. Rotating `SECRET_KEY` later signs out all users, so pick it once.

### Step 4: Start

```bash
docker compose up -d --build
```

This starts 6 containers:

| Container | Purpose |
|---|---|
| `postgres` | PostgreSQL 16 database |
| `redis` | Redis 7 cache |
| `backend` | FastAPI REST API (port 9000, internal) |
| `worker` | Background sync + queue + analytics + discovery |
| `frontend` | Next.js SSR frontend (port 3000, internal) |
| `nginx` | Reverse proxy (exposes port 8081) |

All services have healthchecks; `nginx` waits for the `frontend` service to be
healthy before starting (`docker compose ps` shows `healthy`).

### Step 5: Open and Use

```
http://your-server-ip:8081
```

1. Register an account.
2. Log in.
3. Go to Accounts → Add Account, enter your Telegram phone number, then the
   code from Telegram (and 2FA password if prompted).
4. Toggle monitoring ON.
5. Go to Settings and set "Views per day" — all other settings are auto-computed.

### Health & Self-Healing

- If the worker's main loop shows no progress for `WORKER_STALL_TIMEOUT`
  seconds, the watchdog exits the process and Docker restarts it.
- Stuck `PROCESSING` queue items are recovered automatically on the next cycle.
- Backend healthcheck is HTTP (`/api/health`), not just a TCP port check.

### Updating

```bash
cd TG-Story-Watcher
git pull
docker compose up -d --build
```

Data persists in the Docker volumes `postgres_data` and `sessions_data`.

### Stopping

```bash
# Stop (data preserved)
docker compose down

# Stop and delete ALL data
docker compose down -v
```

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f worker

# Last 50 lines
docker compose logs --tail=50 backend
```

### Reverse Proxy (Nginx/Caddy)

If you want to put the app behind your own reverse proxy (e.g., for HTTPS):

```nginx
# Example Nginx server block for your-domain.com
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (for hot reload in dev)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

With Caddy (automatic HTTPS):

```
your-domain.com {
    reverse_proxy localhost:8081
}
```

### Backups

```bash
# Backup PostgreSQL
docker compose exec postgres pg_dump -U storywatcher storywatcher > backup.sql

# Restore
cat backup.sql | docker compose exec -T postgres psql -U storywatcher -d storywatcher
```

Telegram session files live in the `sessions_data` volume. Back up the whole
volume for full recovery:

```bash
docker run --rm -v tg-story-watcher_sessions_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/sessions_backup.tar.gz -C /data .
```

### Troubleshooting Deployment

| Problem | Solution |
|---|---|
| Port 8081 already in use | Change `WEB_PORT` in `.env` |
| Containers keep restarting / unhealthy | `docker compose ps`, `docker compose logs --tail=200 backend worker` |
| Worker keeps exiting | Check `WORKER_STALL_TIMEOUT`: a healthy worker logs a `queue_worker:` line every cycle. If the account is simply slow, raise the timeout |
| Telegram code not received | Verify `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in `.env` |
| Database connection errors | Ensure PostgreSQL is healthy: `docker compose ps` |
| Out of disk space | `docker system prune -a` to clean unused images |

## License

By contributing, you agree that your contributions will be licensed under
the MIT License.