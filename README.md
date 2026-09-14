<p align="right">
  <a href="README.md"><b>English</b></a> · <a href="README_ru.md">Русский</a>
</p>

# TG Story Watcher

A self-hosted web application for monitoring and automatically viewing
**Telegram Stories** through the official **Telegram MTProto User API**
(Telethon). Supports multiple local users — each with their own Telegram
accounts, tags, search settings, rules, queues, history, and analytics.

> ⚠️ The app works only with the **official Telegram MTProto protocol**, uses
> one Telegram account — one session, and **never tries to bypass limits or
> anti-spam**. All view actions run sequentially, with delays, pauses, and
> safety checks — protecting your account from being flagged.

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [How It Works](#how-it-works)
- [Auto-Configuration](#auto-configuration)
- [Requirements](#requirements)
- [Installation with Docker (recommended)](#installation-with-docker-recommended)
- [Manual Setup (Development Mode)](#manual-setup-development-mode)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Settings Reference](#settings-reference)
- [Account & Queue Statuses](#account--queue-statuses)
- [Telegram Limits & Safety](#telegram-limits--safety)
- [VPN & Proxy Support](#vpn--proxy-support)
- [Performance](#performance)
- [Security](#security)
- [Reliability & Self-Healing](#reliability--self-healing)
- [Multi-User Data Isolation](#multi-user-data-isolation)
- [Database](#database)
- [API (summary)](#api-summary)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Single-parameter configuration** — set only "Views per day" (50–12,000);
  all other technical parameters are auto-computed
- **Adaptive story search** — frequency and result count adapt to queue fill so
  views are spread evenly throughout the day
- **Local registration** — sign in with name, email, and password; passwords
  are stored as PBKDF2 hashes (never as plaintext)
- **Multi-user** — multiple users, data isolated by the authenticated user
- **Telegram MTProto authorization** — phone number → code → optional 2FA
- **Multiple Telegram profiles** per application user
- **Automatic profile sync** — name, username, phone, and Telegram ID
- **Monitoring and auto-viewing** of available Stories with filtering
- **Whitelist and blacklist** of authors, per-user tags and rules
- **Discovery** — search by hashtags, places, and geo-radius with a map of collected places
- **View queue** — priorities, cancel, retry, rate limits
- **Account dashboard** with charts and recent activity
- **Account analytics** — own active/archived Stories, views, reactions, forwards,
  ER, viewer lists, time-based snapshots, best Stories, period filters
- **Responsive web UI** with a dark theme and EN/RU translations
- **Quick start** — new users receive starter hashtags; auto-search and
  monitoring turn on automatically once Telegram is connected
- **Admin panel** — global management of users, accounts, the worker, and
  backups with roles (SUPER_ADMIN/ADMIN/READ_ONLY)
- **VPN proxy support** — built-in Xray SOCKS5 proxy for Telegram MTProto
  with subscription-based server management, automatic failover, and IP
  change monitoring
- **Docker Compose deployment** — PostgreSQL, Redis, VPN (Xray), worker, frontend, Nginx
- **Self-healing** — the worker restarts on hangs, stuck queue tasks are
  recovered automatically, every service has a healthcheck

## Screenshots

| Dashboard | Accounts | Stories |
|---|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Accounts](docs/screenshots/accounts.png) | ![Stories](docs/screenshots/stories.png) |

| Queue | Discovery | Analytics |
|---|---|---|
| ![Queue](docs/screenshots/queue.png) | ![Discovery](docs/screenshots/discovery.png) | ![Analytics](docs/screenshots/analytics.png) |

| Settings | Whitelist | Blacklist |
|---|---|---|
| ![Settings](docs/screenshots/settings.png) | ![Whitelist](docs/screenshots/whitelist.png) | ![Blacklist](docs/screenshots/blacklist.png) |

| History | Statistics |
|---|---|
| ![History](docs/screenshots/history.png) | ![Statistics](docs/screenshots/statistics.png) |

## How It Works

```
Browser
   │
   ▼
Nginx ───────────────────► Next.js frontend (UI pages)
   │
   ▼
FastAPI backend ─────────► PostgreSQL (data) + Redis (cache)
   │
   ├── Single background process (worker)
   │   ├── Scheduler (story sync, analytics collection)
   │   ├── View queue (delays, rate limits, task recovery)
   │   ├── Discovery controller (adaptive search, geo/hashtag rotation)
   │   ├── Auto-backup and stale-data cleanup
   │   └── VPN IP monitor (detects IP changes → reconnects Telegram clients)
   │
   └── VPN container (Xray SOCKS5)
       └── Routes Telegram MTProto traffic through proxied tunnel
```

A single `worker` process combines sync, queue, discovery, and analytics
because Telethon session files cannot be safely opened from multiple processes.
The FastAPI backend serves the REST API and updates the view queue in real
time; the worker picks up tasks, authorizes as a connected Telegram account,
and performs views with all limits enforced.

The optional VPN container runs an Xray SOCKS5 proxy that routes Telegram
MTProto traffic through a remote server. When the VPN's external IP changes
(e.g. server reconnection), the worker proactively disconnects all Telegram
clients before they hit `AuthKeyDuplicatedError`.

## Auto-Configuration

The entire system revolves around **one** user parameter — "Views per day":

```
                VIEWS PER DAY
                     │
                     ▼
              primary limit
                     │
     ┌───────────────┼────────────────┐
     ▼               ▼                ▼
  view speed     search           queue
     │               │                │
     ▼               ▼                ▼
  per hour/min   interval       parallelism
     │               │                │
     └───────────────┼────────────────┘
                     ▼
              view delays
                     ▼
            even distribution
               throughout day
```

### Derived Parameters

| Parameter | Formula | Example (12,000/day) |
|---|---|---|
| Views per hour | `daily / 24` | 500 |
| Views per minute | `ceil(daily / 1440)` | 9 |
| Min delay | `max(3, min(20, avg_delay × 0.3))` | 3s |
| Max delay | `max(10, min(120, avg_delay × 1.5))` | 11s |
| Queue parallelism | based on daily limit (1–3) | 3 |
| Max tasks per cycle | based on daily limit (50–200) | 200 |
| Monitoring interval | `max(15, min(60, 120 - daily/100))` | 15s |
| Search interval | adaptive, based on queue fill | 60–600s |
| Search results | adaptive, based on queue gap | 20–200 |

> `parallel` and `max_tasks` are additionally clamped by hard caps in the
> worker so the DB connection pool can never be exhausted and the event loop
> cannot be blocked (protection against queue "wedging").

### Adaptive Search (Discovery)

The discovery system continuously monitors queue state and adjusts:

- **Queue empty** → search every 60 seconds, fetch maximum results
- **Queue half-full** → search every 5 minutes, fetch moderate results
- **Queue full** → search every 10 minutes, fetch minimal results
- **Queue oversized** → skip search entirely
- **Views nearly exhausted** → skip search entirely

### Daily Budget Protection

The daily limit is an absolute ceiling. Before every view:

```
if viewed_today >= daily_limit:
    STOP
```

Views are tracked per account per day; the account pauses when the limit is
reached. Changing the limit mid-day adjusts the remaining capacity:

```
Before: 5000 limit, 3000 viewed
After setting 12000: 9000 remaining
```

## Requirements

**To run with Docker (recommended):**

- Docker and Docker Compose v2 (included in Docker Desktop / docker-ce)
- Telegram API credentials (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`) from
  https://my.telegram.org
- A Telegram user account for MTProto authorization

**To run manually (development mode):**

- Python 3.12+
- Node.js 18+ and npm
- PostgreSQL 16 (or SQLite for quick local runs)
- Redis 7

## Installation with Docker (recommended)

### 1. Get the code

```bash
git clone https://github.com/devlewicki/TG-Story-Watcher.git
cd TG-Story-Watcher
```

### 2. Configure the environment

```bash
cp .env.example .env
```

Edit `.env`. Telegram API credentials are **required**:

```dotenv
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash_here

# Generate strong values for production:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=your_random_secret_here
STORYWATCHER_API_TOKEN=your_random_token_here

# Optional: VPN proxy for Telegram MTProto
# TELEGRAM_PROXY_ENABLED=true
# TELEGRAM_PROXY_HOST=vpn
# TELEGRAM_PROXY_PORT=1080
# VPN_SUBSCRIPTION_URL=https://your-v2ray-subscription-url
```

### 3. Build and run

> The first frontend build takes a few minutes.

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

All services should eventually report `healthy` (each container has a healthcheck).

### 4. Open the app

| What | URL |
|---|---|
| Web UI | http://localhost:8081 |
| Web port (external) | `WEB_PORT` in `.env` (default `8081`) |
| Backend API | http://localhost:9000/api |
| Interactive API docs | http://localhost:9000/docs |

Containers:

| Container | Purpose |
|---|---|
| `vpn` | Xray SOCKS5 proxy (vmess/vless/shadowsocks/trojan) with auto-failover |
| `postgres` | PostgreSQL 16 database |
| `redis` | Redis 7 cache |
| `backend` | FastAPI REST API (host 9000 → container 8000) |
| `worker` | Single background process: sync + queue + analytics + discovery + VPN monitor |
| `frontend` | Next.js SSR web UI (port 3000, internal only) |
| `nginx` | Reverse proxy, exposes external port 8081 |

### Updating

```bash
git pull
docker compose up -d --build
```

Data (PostgreSQL `postgres_data` volume, Telegram sessions `sessions_data`
volume, and backups `backups_data` volume) survives rebuilds.

### Stopping & Wiping

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop AND delete all data (careful!)
```

### Logs & Backups

```bash
docker compose logs -f worker
docker compose logs --tail=200 backend
docker compose logs -f vpn

# Backup PostgreSQL
docker compose exec postgres pg_dump -U storywatcher storywatcher > backup.sql

# Restore
cat backup.sql | docker compose exec -T postgres psql -U storywatcher -d storywatcher
```

Telegram sessions live in the `sessions_data` volume
(`SESSIONS_DIR=/data/sessions`) — back them up together with the database for
full recovery.

## Manual Setup (Development Mode)

Docker is the primary and recommended deployment method (the worker, queue,
and healthchecks are configured in `docker-compose.yml`). For local development
the project can also be run manually.

### Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Quick start on SQLite (no Postgres needed):

```bash
export DATABASE_URL="sqlite:///./data/storywatcher.db"
export REDIS_URL="redis://localhost:6379/0"
export TELEGRAM_API_ID=...
export TELEGRAM_API_HASH=...
uvicorn app.main:app --reload --port 9000
```

Or with local PostgreSQL:

```bash
export DATABASE_URL="postgresql+psycopg2://storywatcher:storywatcher@localhost:5432/storywatcher"
uvicorn app.main:app --reload --port 9000
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:3000 — Next.js proxies `/api` to the backend
(http://localhost:9000), so CORS is not an issue.

### Worker

```bash
cd backend
python -m app.workers.combined
```

> ⚠️ Do not run multiple workers that open the same Telethon session files —
> SQLite-backed sessions cannot be safely used by competing processes.

## Environment Variables

All variables are set in `.env` (project root); Compose passes them into
containers. A ready-to-copy template is `.env.example`.

### Core

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | `StoryWatcher` | Application name (display only) |
| `SECRET_KEY` | `dev-secret-key` | App secret key (signs user tokens); **change it** |
| `DEBUG` | `false` | Debug mode (verbose logging) |
| `STORYWATCHER_API_TOKEN` | — | Legacy API key (not used for authentication; included in the backup secrets snapshot) |
| `NEXT_PUBLIC_API_URL` | `http://localhost:9000/api` | Frontend API base URL (set to `/api` in Docker via Nginx) |

### Telegram

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_API_ID` | — | Telegram API ID from my.telegram.org (**required**) |
| `TELEGRAM_API_HASH` | — | Telegram API Hash from my.telegram.org (**required**) |
| `SESSIONS_DIR` | `/data/sessions` | Telegram session files directory |

### Database & Cache

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `storywatcher` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `storywatcher` | PostgreSQL password (**change it**) |
| `POSTGRES_DB` | `storywatcher` | PostgreSQL database name |
| `DATABASE_URL` | `postgresql+psycopg2://storywatcher:storywatcher@postgres:5432/storywatcher` | Database URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis URL |

### Worker & Performance

| Variable | Default | Description |
|---|---|---|
| `STORYWATCHER_SYNC_INTERVAL` | `30` | Story sync interval (seconds) |
| `STORYWATCHER_WORKER_POLL` | `1` | Worker poll interval (seconds) |
| `STORYWATCHER_ANALYTICS_INTERVAL` | `3600` | How often to collect full archive analytics (seconds) |
| `WORKER_STALL_TIMEOUT` | `240` | Seconds without main-loop progress before the worker exits (Docker restarts it) |
| `WORKER_HEARTBEAT` | `/tmp/worker_heartbeat` | Heartbeat file used by the worker healthcheck |
| `WORKER_MAX_ERRORS` | `10` | Consecutive cycle errors before exit + restart |
| `WEB_PORT` | `8081` | External web interface port |

### VPN / Proxy

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_PROXY_ENABLED` | `false` | Enable VPN SOCKS5 proxy for Telegram |
| `TELEGRAM_PROXY_HOST` | `vpn` | SOCKS5 proxy host (container name) |
| `TELEGRAM_PROXY_PORT` | `1080` | SOCKS5 proxy port |
| `VPN_SUBSCRIPTION_URL` | — | V2Ray subscription URL for the VPN container |
| `VPN_REFRESH_INTERVAL` | `3600` | How often to re-fetch the subscription (seconds) |
| `VPN_SOCKS_PORT` | `1080` | SOCKS5 port exposed by the VPN container |
| `VPN_LOG_LEVEL` | `warning` | Xray log level |
| `VPN_TEST_URL` | `https://www.gstatic.com/generate_204` | URL for tunnel connectivity tests |
| `VPN_TEST_TIMEOUT` | `8` | Timeout for tunnel tests (seconds) |
| `VPN_PROBE_INTERVAL` | `10` | How often to probe tunnel health (seconds) |
| `VPN_FAIL_THRESHOLD` | `3` | Consecutive probe failures before failover |
| `VPN_SCAN_PORT` | `1081` | Dedicated port for candidate scanning (avoids dropping the live proxy) |
| `VPN_SCAN_SLEEP` | `1.0` | Delay between scan probes (seconds) |
| `VPN_SCAN_ATTEMPTS` | `1` | Probe attempts per candidate during scan |
| `VPN_IP_CHECK_INTERVAL` | `30` | How often the VPN IP monitor checks for IP changes (seconds) |

### Administration & Backups

| Variable | Default | Description |
|---|---|---|
| `ADMIN_BOOTSTRAP_USERNAME` | `admin` | First admin login (created on startup) |
| `ADMIN_BOOTSTRAP_PASSWORD` | — | First admin password |
| `BACKUP_STORAGE_DIR` | `/data/backups` | Backup storage directory (volume `backups_data`) |
| `BACKUP_AUTO_PASSWORD` | — | Encryption password for automatic backups |
| `BACKUP_SNAPSHOT_SECRETS` | `1` | Include secrets (`.env`, sessions) in the backup snapshot |
| `WORKER_DISCOVERY_TIMEOUT` | `1200` | Timeout for one discovery cycle in the worker (seconds) |
| `STORYWATCHER_GEOCODER_URL` | `https://nominatim.openstreetmap.org` | Geocoder for address search |
| `PROBE_INTERNAL_SERVICES` | `0` | Probe internal services (frontend/nginx) in the admin panel |

### Production Security

- Change `SECRET_KEY` — rotating `SECRET_KEY`
  signs out all users (their session tokens are signed with it).
- Set a strong `POSTGRES_PASSWORD`.
- Never commit `.env`, session files, or `node_modules` (covered by `.gitignore`).
- Running behind an HTTPS reverse proxy is recommended (Nginx/Caddy examples in
  [CONTRIBUTING.md](CONTRIBUTING.md#reverse-proxy-nginxcaddy)).

## Usage

1. **Register.** Open the app → sign up with name, email, and password.
2. **Connect Telegram.** Right after registration the Telegram connection dialog
   opens: phone number → code from Telegram → 2FA password if prompted. You can
   also connect later (Accounts → Add account). The account card shows your name,
   username, phone, and Telegram ID.
3. **Automatic setup.** For a new user, connecting Telegram automatically enables
   monitoring and auto-search, and Story Search is pre-filled with starter
   hashtags. Existing users' settings are not touched.
4. **Configure.** Set "Views per day" in Settings → Limits. All other parameters
   (delays, search frequency, queue parallelism) are auto-computed.
5. **Add sources.** Story Search → add hashtags, places & cities, or enable a
   geo-radius search around a point on the map.
6. **Filters.** Settings → Filters controls which authors are processed
   (contacts, channels, groups, bots, etc.).
7. **Analyze.** The Analytics page shows views, reactions, forwards, ER, and
   viewer lists for your own Stories; Statistics aggregates actions.
8. **Manage.** Use Whitelist/Blacklist to control which authors are processed;
   use Queue to track, cancel, or retry view tasks.
9. **Extras.** Settings → Additional settings holds the Telegram API ID and
   API hash (usually changed only after reinstalling the app).

> A Telegram account belongs to the application user who authorizes it.
> The same Telegram account cannot be attached to another application user.

## Settings Reference

Settings are managed on the Settings page. The "Queue" and "Discovery"
sections are not edited there: the queue is fully automatic, and search is
configured on its own Story Search page.

### User-Configured Parameters

| Section | Parameter | Range | Description |
|---|---|---|---|
| General | Language | RU / EN | Interface localization |
| General | Timezone | tz identifier | e.g. `Europe/Moscow`, `UTC`; auto-detect available |
| General | Autostart | on/off | Start automation when the application launches |
| Telegram | Reconnection | on/off | Auto-reconnect when the connection drops |
| Monitoring | Real-time updates | on/off | Process updates as they arrive |
| Monitoring | Fallback sync | on/off | Restore missed stories after a restart |
| Limits | Views per day | 50–12,000 | Main parameter; everything else derives from it |
| View | Max stories per author per day | 1–10 | Newest first; resets at 00:00 in your timezone |
| View | Auto-like | on/off | Add a reaction after viewing |
| View | Like emoji | 👍 ❤️ 🔥 etc. | Emoji for auto-reactions |
| Filters | Which authors to process | 9 toggles | Contacts, unknown, mutual/non-mutual, channels, groups, bots, deleted, blocked |
| Additional | API ID, API Hash | text | Telegram API credentials from my.telegram.org |

### Auto-Computed Parameters (not editable)

| Section | Parameter | Formula |
|---|---|---|
| Limits | Views per hour | `floor(daily / 24)` |
| Limits | Views per minute | `ceil(daily / 1440)` |
| Limits | Searches per hour | 1–10 (`daily / 1500`) |
| Limits | Max search results | 20–200 |
| Limits | Search delay | 60–600s |
| View | Min delay | 3–20s (avg delay × 0.3) |
| View | Max delay | 10–120s (avg delay × 1.5) |
| Queue | Parallel processing | 1–3 (by daily limit) |
| Queue | Max tasks per cycle | 50–200 |
| Queue | Processing timeout | 300/600s |
| Queue | Auto retries | 3/5 |
| Monitoring | Check interval | 15–60s (`120 − daily / 100`) |
| Discovery | Search interval | 60–600s (by queue fill) |
| Discovery | Results per search | 20–200 (by queue gap) |

## Account & Queue Statuses

**Accounts:** `ACTIVE` — working, `PAUSED` — paused (including when the daily
limit is reached), `FLOOD_WAIT` — Telegram rate-limited (auto-pause),
`ERROR` — error, `DISCONNECTED` — needs reconnect, `AUTH_REQUIRED` — needs
authorization, `BANNED_OR_RESTRICTED` — restricted by Telegram.

**Queue:** `PENDING` — waiting, `WAITING_DELAY` — waiting for the pre-view delay,
`PROCESSING` — in flight, `VIEWED` — viewed, `SKIPPED` — skipped,
`FAILED` — errored (retry via API), `EXPIRED` — story expired,
`CANCELLED` — cancelled.

Tasks "stuck" in `PROCESSING` (after a worker crash/restart) are recovered
automatically: first returned to `PENDING` and retried; when the auto-retry
budget is exhausted they move to `FAILED` for manual handling.

## Telegram Limits & Safety

Telegram may impose flood wait limits on accounts that perform too many
automated actions. The app handles this gracefully:

- Excessive viewing may trigger `FLOOD_WAIT` — the worker backs off instead of
  retrying in a tight loop
- Rate limits are auto-computed from the daily views setting
- Views are spread evenly across the day
- The daily limit is checked **before every view** and never exceeded
- Whitelist is excluded at queue creation and re-checked before each action
- Blacklisted authors are always skipped
- Transient (network) errors retry with exponential backoff
- The queue resumes automatically after a server restart

> Going beyond safe limits is at your own risk — Telegram may restrict or ban
> accounts that exhibit bot-like behavior.

## VPN & Proxy Support

The application includes a built-in VPN container for routing Telegram MTProto
traffic through a remote proxy server. This is useful when:

- Telegram is blocked in your region
- You need to route traffic through a specific country
- Your server's IP is rate-limited by Telegram

### Supported Protocols

The VPN container runs [Xray](https://xtls.github.io/) and supports
subscription-based configurations with the following proxy protocols:

- **VMess** (with TLS, WebSocket, gRPC transports)
- **VLESS** (with TLS, Reality, WebSocket, gRPC, xhttp transports)
- **Shadowsocks** (SIP002 and legacy format)
- **Trojan**

### How It Works

1. The VPN container fetches your V2Ray subscription URL on startup
2. Parses all server links and tests each candidate on a dedicated scan port
3. Selects the fastest working server and starts Xray as a SOCKS5 proxy
4. The `worker` container routes Telegram traffic through the SOCKS5 proxy
5. A **VPN IP monitor** continuously checks the external IP — when it changes
   (e.g. VPN reconnected to a different country), all Telegram clients are
   proactively disconnected to prevent `AuthKeyDuplicatedError`

### Failover

- Periodic tunnel health checks every `VPN_PROBE_INTERVAL` seconds
- After `VPN_FAIL_THRESHOLD` consecutive failures, the VPN container scans
  all candidates in the subscription and switches to the fastest working server
- A cooldown period prevents excessive re-scanning
- The live SOCKS5 port is never dropped during scanning — only replaced once
  a verified replacement is ready

### Enabling VPN

1. Set `VPN_SUBSCRIPTION_URL` in `.env` to your V2Ray subscription URL
2. Set `TELEGRAM_PROXY_ENABLED=true`
3. Set `TELEGRAM_PROXY_HOST=vpn` and `TELEGRAM_PROXY_PORT=1080`
4. Rebuild: `docker compose up -d --build`

The VPN container will be included automatically in the compose stack.

## Performance

- **Dashboard charts** — aggregated queries (`EXTRACT(HOUR)`, `DATE()`) instead
  of dozens of individual `COUNT(*)`
- **Stories list** — DB-level `LEFT JOIN` and `OFFSET/LIMIT`
- **Analytics** — viewer counts via a single `COUNT(*)`
- **Settings cache** — `compute_all_from_daily()` LRU-cached
- **PostgreSQL connection pool** — `pool_size=10`, `max_overflow=20`,
  `pool_timeout=10s`, `pool_recycle=1800s`
- **Archive analytics** — collected rarely (default once per hour) so it never
  floods Telegram RPC usage during real-time viewing
- **Queue worker** — per-task timeouts prevent single stuck RPC from blocking
  the entire queue; DB sessions opened inside the semaphore to avoid pool
  exhaustion

## Security

### Authentication

- **Local registration** — PBKDF2-SHA256 password hashing (310k iterations)
- **Token-based auth** — `user.<base64 payload>.<hmac signature>` tokens with
  30-day expiry, validated via HMAC against `SECRET_KEY`
- **Token revocation** — tokens can be revoked through the settings store
- **User isolation** — all endpoints are scoped to the authenticated user's
  `user_id`; cross-user data access is blocked at the API layer

### Endpoint Protection

- User auth endpoints (`/api/user-auth/*`) handle registration and login
- Telegram auth endpoints (`/api/auth/*`) require a valid user token
- Account, stories, queue, analytics, and settings endpoints all require
  authentication via the `X-API-Token` header
- The admin panel (`/api/admin/*`) uses a separate `x-admin-token` header with
  roles `SUPER_ADMIN`, `ADMIN`, `READ_ONLY`
- Only `GET /api/health`, `POST /api/user-auth/register`,
  `POST /api/user-auth/login`, and `POST /api/admin/auth/login` are
  unauthenticated

The first admin is created automatically on backend startup from
`ADMIN_BOOTSTRAP_USERNAME` / `ADMIN_BOOTSTRAP_PASSWORD`; change the password
right after the first login.

### Recommendations

- Change `SECRET_KEY` for production
- Set a strong `POSTGRES_PASSWORD`
- Run behind an HTTPS reverse proxy (Nginx/Caddy)
- The `.env` file is excluded from Git via `.gitignore`

## Reliability & Self-Healing

### Worker Watchdog

- The worker writes a heartbeat file every cycle
- If no progress for `WORKER_STALL_TIMEOUT` seconds, the worker exits
- Docker's `restart: unless-stopped` policy restarts it automatically
- After `WORKER_MAX_ERRORS` consecutive cycle failures, the worker exits

### Queue Recovery

- Tasks stuck in `PROCESSING` (e.g. after a crash) are automatically returned
  to `PENDING` and retried
- Per-task timeouts (`asyncio.wait_for`) prevent single stuck RPC from
  blocking the queue
- Timed-out tasks return to `PENDING` with a 30-second delay, or move to
  `FAILED` when the auto-retry budget is exhausted

### VPN Resilience

- The VPN container probes tunnel health and fails over to backup servers
- The VPN IP monitor detects IP changes and proactively disconnects Telegram
  clients to prevent `AuthKeyDuplicatedError`
- After IP change, Telegram clients reconnect automatically on the next cycle

### Healthchecks

Every container has a healthcheck:

| Container | Method | Interval |
|---|---|---|
| `postgres` | `pg_isready` | 5s |
| `redis` | `redis-cli ping` | 5s |
| `backend` | HTTP `/api/health` | 15s |
| `worker` | Heartbeat file check | 15s |
| `frontend` | `fetch()` on port 3000 | 15s |
| `nginx` | `wget` on port 80 | 15s |
| `vpn` | `curl` through SOCKS5 | 20s |

## Multi-User Data Isolation

All user-owned data must be accessed through the authenticated application
token. The following resources are isolated per user:

- Telegram accounts, Stories, and their statistics
- Viewers and reactions
- Queues and action history
- Whitelist and Blacklist, rules
- Tags and hashtags
- Discovery settings and selected locations
- Dashboard and account statistics

The collected `GeoPlace` catalog is intentionally shared. User-specific tags,
selections, and search configuration are stored separately per user.

## Database

PostgreSQL 16 by default (Docker), with SQLite fallback for quick local runs.
The schema is created automatically on startup.

Main tables: `users`, `telegram_accounts`, `stories`, `story_stats_snapshots`,
`story_viewers`, `story_reaction_stats`, `story_queue`, `story_views`,
`whitelist`, `blacklist`, `automation_rules`, `activity_logs`,
`settings_store`, `auth_sessions`, `geo_places`.

Admin panel tables: `admin_users`, `admin_sessions`, `admin_audit_logs`,
`system_events`, `backup_records`, `backup_operations`.

## API (summary)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/user-auth/register` | Register a user |
| `POST` | `/api/user-auth/login` | Login (returns the token) |
| `GET` | `/api/user-auth/me` | Current user |
| `POST` | `/api/auth/send-code` | Send Telegram confirmation code |
| `POST` | `/api/auth/confirm-code` | Confirm code (may return `twofa`) |
| `POST` | `/api/auth/confirm-password` | Confirm 2FA password |
| `GET` | `/api/auth/status` | Authorization status |
| `GET` | `/api/accounts` | List Telegram accounts |
| `POST` | `/api/accounts` | Add an account |
| `POST` | `/api/accounts/{id}/start` | Start account |
| `POST` | `/api/accounts/{id}/pause` | Pause account |
| `POST` | `/api/accounts/{id}/monitoring` | Toggle monitoring |
| `DELETE` | `/api/accounts/{id}` | Delete account |
| `GET` | `/api/stories` | List Stories (`?limit=&offset=`) |
| `GET` | `/api/stories/count` | Story count |
| `GET` | `/api/stories/{id}` | Story details |
| `POST` | `/api/stories/{id}/view` | Add Story to the view queue |
| `POST` | `/api/stories/{id}/skip` | Skip Story |
| `GET` | `/api/queue` | Queue items |
| `GET` | `/api/queue/count` and `/api/queue/stats` | Queue counts and summary |
| `PATCH` | `/api/queue/{id}` | Update a queue item |
| `POST` | `/api/queue/{id}/cancel` | Cancel an item |
| `POST` | `/api/queue/{id}/retry` | Retry an item |
| `DELETE` | `/api/queue/clear` | Clear the queue |
| `GET` / `POST` | `/api/whitelist` `/api/blacklist` | Author lists |
| `DELETE` | `/api/whitelist/{entry_id}` `/api/blacklist/{entry_id}` | Remove from a list |
| `GET` | `/api/rules` `/api/rules/{id}` | Automation rules |
| `POST`/`PATCH`/`DELETE` | `/api/rules` `/api/rules/{id}` | Create/update/delete a rule |
| `POST` | `/api/rules/{id}/enable` `/disable` | Enable/disable a rule |
| `POST` | `/api/rules/{id}/test` | Test a rule |
| `GET` | `/api/history/views` | View history (pagination) |
| `GET` | `/api/history/views/count` | View count |
| `GET` | `/api/history/activity` | Activity log (pagination) |
| `GET` | `/api/history/activity/count` | Activity count |
| `GET` | `/api/dashboard` | Dashboard data |
| `GET` | `/api/stats` | General statistics |
| `GET` | `/api/analytics/overview` | Analytics overview (`?days=&period=`) |
| `GET` | `/api/analytics/stories` | Stories with analytics |
| `GET` | `/api/analytics/stories/{id}` `/views` `/viewers` `/reactions` | Story analytics details |
| `GET` | `/api/analytics/daily` | Daily aggregates for the dashboard chart |
| `GET` | `/api/analytics/recent-events` | Recent events (`?limit=`) |
| `POST` | `/api/analytics/sync` | Sync analytics (`?account_id=`) |
| `GET`/`POST` | `/api/settings` | Get/save settings |
| `PUT` | `/api/settings` | Replace all settings |
| `GET` | `/api/discovery/config` | Discovery config |
| `POST` | `/api/discovery/config` | Save discovery config |
| `GET` | `/api/discovery/places` `/places/count` | Collected geo-places |
| `POST` | `/api/discovery/geocode` | Geocode a city query (`?q=`) |
| `POST` | `/api/discovery/geo-radius` | Search within a radius of a point |
| `POST` | `/api/discovery/geo-search` | Geo round-trip: source → hotspot → target |
| `DELETE` | `/api/discovery/places/{id}` | Remove a discovered place |
| `GET` | `/api/discovery/geocode` | Geocoding (`?q=`) |
| `POST` | `/api/discovery/search` | Run discovery search manually |

User authentication uses the `X-API-Token: user.<...>` header (the token is
returned at login). Full interactive docs: http://localhost:9000/docs (when
running the backend directly).

### Admin API (`/api/admin/*`)

The admin panel is served under `/api/admin/*` with its own authorization via
the `x-admin-token` header and role-based access
(`SUPER_ADMIN`, `ADMIN`, `READ_ONLY`). Endpoints include: admin users and
sessions, dashboard/overview, accounts overview, system events, periodic job
control, worker control (pause/resume/status), settings, and backups (create,
download, restore, auto-backup, secrets snapshot).

## Project Structure

```
TG-Story-Watcher/
├── frontend/                      # Next.js 14 + React 18 + TypeScript + Tailwind
│   ├── app/                       # Pages (App Router)
│   │   ├── page.tsx               # Dashboard
│   │   ├── accounts/              # Telegram account management
│   │   ├── stories/               # Story listing and details
│   │   ├── queue/                 # View queue management
│   │   ├── discovery/             # "Story Search": hashtags, places, geo-radius
│   │   ├── analytics/             # Account analytics
│   │   │   └── stories/[id]/      # Single-Story analytics details
│   │   ├── statistics/            # Action statistics (views, likes, errors)
│   │   ├── settings/              # Settings (general, limits, view, filters, etc.)
│   │   ├── whitelist/             # Author whitelist
│   │   ├── blacklist/             # Author blacklist
│   │   ├── history/               # View and activity history
│   │   └── admin/                 # Admin panel (13 sections)
│   ├── components/                # UI components
│   │   ├── ui.tsx                 # Shared UI primitives (Button, Card, etc.)
│   │   ├── AppShell.tsx           # Authenticated shell wrapper
│   │   ├── ShellGate.tsx          # Routing: /admin* gets its own shell
│   │   ├── TelegramAuthModal.tsx  # Connect Telegram (code → password → 2FA)
│   │   ├── LandingPage.tsx        # Landing page with login/register form
│   │   ├── TokenGate.tsx          # Auth token gate
│   │   ├── Sidebar.tsx            # Navigation sidebar
│   │   ├── PlacesMap.tsx          # Leaflet map for places
│   │   ├── GeoSearchMap.tsx       # Geo-radius search map
│   │   ├── ListManager.tsx        # Whitelist/blacklist management
│   │   ├── shellLayout.ts         # Shell geometry (top bar, insets)
│   │   └── admin/                 # Admin panel components (AdminShell, adminUi)
│   ├── lib/                       # Utilities
│   │   ├── api.ts                 # API client (api.get, api.post, etc.)
│   │   ├── adminApi.ts            # Admin panel API client (x-admin-token)
│   │   ├── theme.tsx              # Theme provider (dark only)
│   │   ├── i18n.tsx               # Internationalization (EN/RU)
│   │   ├── format.ts              # Formatting helpers
│   │   ├── compute_all_from_daily.ts  # Client-side derived parameter calculation
│   │   ├── useFetch.ts            # Data fetching hook
│   │   └── translations/          # en.ts, ru.ts
│   ├── Dockerfile
│   └── package.json
├── backend/                       # Python 3.12 + FastAPI + SQLAlchemy
│   ├── app/
│   │   ├── api/                   # User-facing API routes
│   │   │   ├── auth.py            # Telegram MTProto authorization
│   │   │   ├── user_auth.py       # Local user registration/login
│   │   │   ├── accounts.py        # Telegram account CRUD
│   │   │   ├── stories.py         # Story listing and management
│   │   │   ├── queue.py           # View queue CRUD
│   │   │   ├── analytics.py       # Analytics endpoints
│   │   │   ├── dashboard.py       # Dashboard data
│   │   │   ├── settings.py        # Settings CRUD
│   │   │   ├── discovery.py       # Discovery config, places, geocode, search
│   │   │   ├── whitelist.py       # Whitelist CRUD
│   │   │   ├── blacklist.py       # Blacklist CRUD
│   │   │   ├── rules.py           # Automation rules
│   │   │   ├── history.py         # View/activity history
│   │   │   ├── schemas.py         # Pydantic schemas
│   │   │   ├── deps.py            # Auth dependencies (current_user_id)
│   │   │   ├── timezone.py        # Timezone helpers
│   │   │   └── admin/             # Admin panel routes /api/admin/*
│   │   ├── admin_auth.py          # Admin authentication and roles (HMAC)
│   │   ├── admin_models.py        # Admin panel ORM models (6 tables)
│   │   ├── analytics/             # Analytics service (archive collection)
│   │   ├── filters/               # Filter engine for story processing
│   │   ├── queue/                 # Queue processor (per-request RPC timeouts)
│   │   ├── services/              # Business logic, settings auto-derivation, audit
│   │   │   └── backup/            # Backups (archive, encryption, storage, auto)
│   │   ├── settings/              # Defaults and new-user onboarding
│   │   ├── stories/               # Story monitoring, discovery, and ingest
│   │   ├── telegram/              # MTProto client manager (Telethon)
│   │   │   └── client_manager.py  # Session lifecycle, SQLite conversion
│   │   ├── workers/               # Background workers
│   │   │   ├── combined.py        # Entry point: scheduler + queue + VPN monitor
│   │   │   ├── scheduler.py       # Story sync, analytics, discovery scheduling
│   │   │   ├── queue_worker.py    # Queue draining with concurrency control
│   │   │   └── worker_control.py  # Worker control via Redis (pause/status)
│   │   ├── config.py              # pydantic-settings configuration
│   │   ├── db.py                  # SQLAlchemy engine, sessions, pool, migrations
│   │   ├── main.py                # FastAPI app (lifespan, CORS, health)
│   │   ├── models.py              # User-facing ORM models (15 tables)
│   │   ├── multitenancy.py        # User token creation/verification (HMAC)
│   │   └── vpn_monitor.py         # VPN IP change detection
│   ├── tests/                     # Integration tests (pytest + SQLite)
│   ├── migrate_limits_derived.py  # Migration: recalculate derived settings
│   ├── migrate_existing_user.py   # Migration: port legacy users
│   ├── Dockerfile
│   ├── requirements.txt
│   └── healthcheck.sh
├── docker/
│   ├── nginx.conf                 # Nginx reverse proxy config
│   └── vpn/
│       ├── Dockerfile             # Xray VPN container (Alpine + Xray)
│       └── entrypoint.sh          # Subscription parser, server selection, failover
├── docker-compose.yml             # 7 services: vpn, postgres, redis, backend, worker, frontend, nginx
├── .env.example
├── CONTRIBUTING.md
├── LICENSE
├── bugs.md                        # Bug tracker (fixed and open issues)
├── AUDIT_REPORT.md                # Full repository audit report
├── audit-report-technical.md      # Technical audit report
├── deployment.md                  # Production deployment guide (tgstory.space)
└── README.md / README_ru.md
```

## Testing

Integration tests run with pytest + in-memory SQLite (no PostgreSQL required):

```bash
cd backend
pip install pytest httpx
python -m pytest tests/ -v
```

Tests cover: Stories pagination/sorting, aggregated dashboard charts,
statistics, analytics (viewers/periods/top stories), `compute_all_from_daily()`
caching, discovery rotation dict isolation, and new-user onboarding (starter
hashtags, auto-enabling search and monitoring after connecting Telegram).

## Troubleshooting

| Symptom | Solution |
|---|---|
| Containers keep restarting | `docker compose ps` and `docker compose logs --tail=200 backend worker`. Check Telegram API credentials in `.env` |
| Telegram code not received | `docker compose logs --tail=200 backend`. The login flow recreates the client on errors. Wait briefly and request a fresh code |
| Views stopped / queue stuck | Check account and worker status: `docker compose ps`, `docker compose logs --tail=200 worker`. Stuck `PROCESSING` items recover automatically |
| Worker "hangs" (healthy but silent) | The worker exits after `WORKER_STALL_TIMEOUT` without main-loop progress and Docker restarts it. Or run `docker compose restart worker` |
| Telegram profile missing | Refresh the Accounts page after authorization |
| A user sees another user's data | Sign out, clear browser site storage, sign in again. Do not reuse tokens between profiles |
| `FLOOD_WAIT` on an account | Expected — Telegram rate-limited the account. The worker backs off automatically |
| `AuthKeyDuplicatedError` | The VPN IP changed and clients were reconnected. If persistent, check VPN logs: `docker compose logs vpn` |
| Port 8081 is busy | Change `WEB_PORT` in `.env` |
| Frontend shows an old UI | Hard refresh the browser (Ctrl+Shift+R) |
| VPN not connecting | Check `docker compose logs vpn`. Verify `VPN_SUBSCRIPTION_URL` is set and the subscription is valid |
| VPN fails over frequently | Check the subscription for working servers. Increase `VPN_FAIL_THRESHOLD` to reduce sensitivity |
| VPN IP change causing issues | The VPN monitor proactively disconnects clients on IP change. Check `docker compose logs worker` for reconnection logs |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code conventions,
and an extended self-hosting guide (HTTPS reverse proxy, volume backups,
migrations).

## License

MIT — see [LICENSE](LICENSE).

---

Made with ❤️ by [devlewicki](https://github.com/devlewicki)
