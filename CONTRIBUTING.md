# Contributing to TG Story Watcher

Thanks for your interest in contributing! This document covers local
development setup, code conventions, and how to deploy the app yourself.

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

For local development without Docker Postgres, you can use SQLite:

```bash
export DATABASE_URL=sqlite:///./data/storywatcher.db
uvicorn app.main:app --reload --port 9000
```

With Docker Postgres:

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
(http://localhost:9000). No CORS issues in dev.

### Running the Worker

The background worker handles story sync, queue processing, and adaptive
discovery:

```bash
cd backend
python -m app.workers.combined
```

> Do not run multiple workers that open the same Telethon session files.
> SQLite-backed Telegram sessions cannot safely be used by competing processes.

### Environment Variables

Copy `.env.example` to `.env` and fill in at minimum:

```dotenv
TELEGRAM_API_ID=your_id
TELEGRAM_API_HASH=your_hash
STORYWATCHER_API_TOKEN=your_token
SECRET_KEY=your_secret
DATABASE_URL=sqlite:///./data/storywatcher.db
REDIS_URL=redis://localhost:6379/0
```

See [README.md](README.md#environment-variables) for the full list.

## Project Structure

```
TG-Story-Watcher/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers (auth, accounts, stories, ...)
│   │   ├── analytics/      # Analytics service
│   │   ├── filters/        # Filter engine for story processing
│   │   ├── queue/          # Queue processor
│   │   ├── services/       # Business logic (settings with auto-derivation)
│   │   ├── stories/        # Story monitoring and discovery
│   │   ├── telegram/       # MTProto client (Telethon)
│   │   ├── workers/        # Background workers (adaptive scheduler + queue)
│   │   ├── config.py       # pydantic-settings configuration
│   │   ├── db.py           # SQLAlchemy engine and sessions
│   │   ├── main.py         # FastAPI app entry point
│   │   ├── models.py       # ORM models
│   │   └── multitenancy.py # User auth, token, password hashing
│   ├── migrate_limits_derived.py  # Migration: recalculate derived settings
│   ├── Dockerfile
│   ├── requirements.txt
│   └── healthcheck.sh
├── frontend/
│   ├── app/                # Next.js App Router pages
│   ├── components/         # UI components (Sidebar, PlacesMap, ui.tsx)
│   ├── lib/                # API client, theme, hooks, formatters
│   ├── Dockerfile
│   └── package.json
├── docker/
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```

## Auto-Configuration Architecture

The system derives all technical parameters from a single user input:
**Views per day** (50–12,000).

### Key Files

| File | Purpose |
|---|---|
| `backend/app/services/settings_service.py` | `compute_all_from_daily()` — derives limits, view delays, queue parallelism, monitoring interval |
| `backend/app/workers/scheduler.py` | `_compute_adaptive_search_params()` — dynamic search interval and result count |
| `backend/app/workers/queue_worker.py` | Recomputes rate limits from daily on each cycle |
| `frontend/app/settings/page.tsx` | Single slider UI, instant recalculation on change |
| `backend/migrate_limits_derived.py` | Migration script to recalculate all derived settings |

### Adding New Derived Parameters

1. Add the formula to `compute_all_from_daily()` in `settings_service.py`
2. Add the key to the appropriate section dict in the return value
3. Update the frontend `setField()` to compute the value for instant UI feedback
4. Run the migration to update existing users

## Code Conventions

### Backend (Python)

- **Formatter/Linter:** Follow existing style. The codebase uses minimal
  whitespace in some files (compressed class definitions) — match the
  surrounding code when editing.
- **ORM:** SQLAlchemy 2.0 mapped columns (`Mapped[type]`). New models go
  in `backend/app/models.py`.
- **API schemas:** Pydantic v2 models in `backend/app/api/schemas.py` or
  inline in route files.
- **Auth:** User authentication uses `X-API-Token` header validated by
  `deps.py`. Telegram auth is in `auth.py`.
- **Database:** `init_db()` creates tables on startup. For schema changes,
  modify `models.py` — Alembic can be added later.
- **No raw SQL.** Use SQLAlchemy ORM queries.
- **Settings derivation:** When adding new auto-computed parameters, always
  derive from `views_per_day` in `compute_all_from_daily()`.

### Frontend (TypeScript/React)

- **Framework:** Next.js 14 App Router (`"use client"` pages).
- **Styling:** Tailwind CSS. Use existing component patterns from
  `components/ui.tsx`.
- **State:** React hooks (`useState`, `useEffect`). No external state
  library.
- **API calls:** Through `lib/api.ts` (`api.get`, `api.post`, etc.).
- **Components:** Functional components with TypeScript props.
- **Theme:** Dark/light support via `lib/theme.tsx`.
- **Settings UI:** Use `readonly` field type for auto-computed values.
  Only user-configurable parameters get sliders.

### Git

- Keep commits focused — one logical change per commit.
- Write clear commit messages.
- Do not commit `.env`, session files, or `node_modules`.

## How to Contribute

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`
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

### Backend

```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/ -q
```

### Manual Testing

1. Start the backend: `uvicorn app.main:app --reload --port 9000`
2. Start the frontend: `cd frontend && npm run dev`
3. Open http://localhost:3000
4. Register, log in, connect a Telegram account, and test the flow.

## Self-Hosting Deployment Guide

### Minimum Server Requirements

- **CPU:** 1 vCPU (2+ recommended)
- **RAM:** 1 GB (2+ recommended)
- **Storage:** 10 GB+
- **OS:** Ubuntu 22.04+, Debian 12+, or any Linux with Docker
- **Ports:** 8081 (web UI) — configurable via `WEB_PORT`

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

Edit `.env`:

```dotenv
# Required
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
STORYWATCHER_API_TOKEN=$(openssl rand -hex 32)
SECRET_KEY=$(openssl rand -hex 32)

# PostgreSQL (change defaults for production!)
POSTGRES_USER=storywatcher
POSTGRES_PASSWORD=use-a-strong-password-here
POSTGRES_DB=storywatcher

# Web port
WEB_PORT=8081
```

> **Important:** Change the default PostgreSQL credentials for any
> non-local deployment. Generate secure tokens with `openssl rand -hex 32`.

### Step 4: Start

```bash
docker compose up -d --build
```

This starts 6 containers:

| Container | Purpose |
|---|---|
| `postgres` | PostgreSQL 16 database |
| `redis` | Redis 7 cache |
| `backend` | FastAPI REST API (port 9000 internal) |
| `worker` | Background story sync + queue processor + adaptive discovery |
| `frontend` | Next.js SSR frontend (port 3000 internal) |
| `nginx` | Reverse proxy (exposes port 8081) |

### Step 5: Open and Use

```
http://your-server-ip:8081
```

1. Register an account
2. Log in
3. Go to Accounts → Add Account
4. Enter your Telegram phone number
5. Enter the code from Telegram
6. Toggle monitoring ON
7. Go to Settings → set "Views per day" (all other settings auto-computed)

### Updating

```bash
cd TG-Story-Watcher
git pull
docker compose up -d --build
```

Data persists in Docker volumes (`postgres_data`, `sessions_data`).

### Stopping

```bash
# Stop (data preserved)
docker compose down

# Stop and delete ALL data
docker compose down -v
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

Telegram session files are in the `sessions_data` volume. Back up the
entire volume for full recovery:

```bash
docker run --rm -v tg-story-watcher_sessions_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/sessions_backup.tar.gz -C /data .
```

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f worker

# Last 100 lines
docker compose logs --tail=100 backend
```

### Troubleshooting Deployment

| Problem | Solution |
|---|---|
| Port 8081 already in use | Change `WEB_PORT` in `.env` |
| Containers keep restarting | Check logs: `docker compose logs backend worker` |
| Telegram code not received | Verify `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in `.env` |
| Database connection errors | Ensure PostgreSQL is healthy: `docker compose ps` |
| Out of disk space | Run `docker system prune -a` to clean unused images |

## License

By contributing, you agree that your contributions will be licensed under
the MIT License.
