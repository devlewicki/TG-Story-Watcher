# TG Story Watcher

A self-hosted web application for monitoring and automatically viewing
Telegram Stories through the **Telegram MTProto User API**. Supports
multiple local users — each with their own Telegram accounts, tags,
search settings, rules, queues, history, and analytics.

The app works only with the official Telegram MTProto protocol via
Telethon, uses one Telegram account — one session, and never tries to
bypass limits or anti-spam mechanisms. All view actions run sequentially,
with delays, pauses, and safety checks — protecting your account from
being flagged.

## Features

- **Single-parameter configuration** — set only "Views per day" (50–12,000); all other settings are auto-computed
- Adaptive story search that adjusts frequency and result count based on queue state
- Even distribution of views throughout the day with automatic speed correction
- Local registration and login with first name, last name, email, and password
- Passwords stored as secure PBKDF2 hashes; plain passwords are never stored
- Multiple users with data isolation by authenticated user
- Telegram MTProto authorization via phone number → code → optional 2FA
- Multiple Telegram profiles per application user
- Automatic Telegram profile identity sync (name, surname, username, phone, Telegram ID)
- Monitoring and automatic viewing of available Telegram Stories
- Filtering and rules for monitored Stories
- Per-user tags, whitelist, blacklist, search configuration, and discovery settings
- Shared GeoPlace database with private user selections and search settings
- Queue management, delays, rate limits, and activity history
- Account dashboard with charts and recent actions
- Account analytics: active/archived own Stories, views, reactions, forwards, ER, viewer list, reaction breakdown, time-based snapshots, best Stories, period filters
- Responsive web interface with dark/light theme
- Docker Compose deployment with PostgreSQL, Redis, worker, frontend, and Nginx

## How Auto-Configuration Works

The entire system revolves around a single user parameter:

```
                ПРОСМОТРОВ В СУТКИ
                        │
                        ▼
                 основной лимит
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   скорость         поиск            очередь
  просмотров
        │               │                │
        ▼               ▼                ▼
  в час / минуту   интервал         параллельность
        │               │                │
        └───────────────┼────────────────┘
                        ▼
                задержки просмотра
                        │
                        ▼
              равномерная работа
                  в течение суток
```

### Derived Parameters

| Parameter | Formula | Example (12,000/day) |
|---|---|---|
| Views per hour | `daily / 24` | 500 |
| Views per minute | `ceil(daily / 1440)` | 9 |
| Min delay | `max(3, min(20, avg_delay × 0.3))` | 3s |
| Max delay | `max(10, min(120, avg_delay × 1.5))` | 11s |
| Parallel workers | 1 / 2 / 3 based on daily threshold | 3 |
| Monitoring interval | `max(15, min(60, 120 - daily/100))` | 15s |
| Search frequency | Adaptive based on queue fill | 60–600s |
| Search results | Adaptive based on queue gap | 10–200 |

### Adaptive Search

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

The system tracks views per account per day and pauses when the limit
is reached. Changing the limit mid-day adjusts remaining capacity:

```
Before: 5000 limit, 3000 viewed
After setting 12000: 9000 remaining
```

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

| History |
|---|
| ![History](docs/screenshots/history.png) |

## Architecture

```
Browser
   │
   ▼
Nginx ───────────────► Next.js frontend
   │
   ▼
FastAPI backend ──────► PostgreSQL
   │                     Redis
   │
   ▼
MTProto Telegram client
   │
   ▼
Combined background worker
   │
   ├── Queue processor (adaptive delays)
   ├── Scheduler (story sync)
   └── Discovery controller (adaptive search)
```

## Requirements

To run with Docker:

- Docker and Docker Compose (v2, included in Docker Desktop / docker-ce)
- Telegram API credentials (`TELEGRAM_API_ID` and `TELEGRAM_API_HASH`)
- A Telegram user account for MTProto authorization

To run manually (development mode):

- Python 3.12+
- Node.js 18+ and npm
- PostgreSQL (or SQLite for quick local runs)

## Installation & Running with Docker (recommended)

### 1. Get the code

```bash
git clone https://github.com/devlewicki/TG-Story-Watcher.git
cd TG-Story-Watcher
```

Repository: https://github.com/devlewicki/TG-Story-Watcher

### 2. Configure the environment

```bash
cp .env.example .env
```

The `.env.example` file contains all available variables with descriptions.
At minimum, set Telegram API credentials (get them at https://my.telegram.org):

```dotenv
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash_here
STORYWATCHER_API_TOKEN=your-random-token-here
SECRET_KEY=your-random-secret-here
```

### 3. Build and run

```bash
docker compose up -d --build
```

### 4. Open the app

| What | URL |
|---|---|
| Web UI | http://localhost:8081 |
| Backend API | http://localhost:9000/api |

The external port can be changed with `WEB_PORT` in `.env`.

Data (database, Telegram sessions) lives in Docker volumes and survives
rebuilds. To update to a new version, just run:

```bash
docker compose up -d --build
```

Stop: `docker compose down` (data is kept). Stop and wipe data:
`docker compose down -v` (careful: deletes the database and sessions).

## Manual Installation (Development Mode)

### Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
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

## Telegram API Credentials

To authorize a Telegram account via MTProto, you need API credentials:

1. Go to https://my.telegram.org
2. Sign in with your phone number
3. Go to **API development tools**
4. Fill in the form (app name, description, URL — any values are fine)
5. Copy `api_id` and `api_hash`

These credentials are used for all Telegram accounts connected to the
application and must be set in `.env` before starting.

## Usage

1. **Register.** Open the app → register with name, email, and password.
2. **Log in.** Enter your email and password.
3. **Connect Telegram.** Go to Accounts → Add account → enter your phone
   number → enter the code from Telegram → enter 2FA password if prompted.
4. **Verify.** The account card should show your name, username, phone,
   and Telegram ID.
5. **Configure.** Set "Views per day" in Settings → Limits. All other
   parameters (delays, search frequency, queue parallelism) are
   automatically computed.
6. **Add sources.** Go to Story Search → add hashtags, places, or
   enable geo-radius search.
7. **Monitor.** Toggle monitoring ON for connected accounts. The worker
   starts discovering and viewing Stories automatically.
8. **Analyze.** Check the Analytics page for views, reactions, forwards,
   ER, and viewer lists on your own Stories.
9. **Manage.** Use Whitelist/Blacklist to control which authors are
   processed. Use Queue to track and manage pending view actions.

> A Telegram account belongs to the application user who authorizes it.
> The same Telegram account cannot be attached to another application user.

## Settings Reference

### User-Configured Parameters

| Section | Parameter | Range | Description |
|---|---|---|---|
| Limits | Views per day | 50–12,000 | Maximum views per 24 hours |
| View | Auto-like | on/off | Like stories after viewing |
| View | Like emoji | 👍 ❤️ 🔥 etc. | Emoji for auto-reactions |
| Discovery | Auto search | on/off | Enable automatic story search |
| Discovery | Hashtags | text | Tags to search for |
| Discovery | Places & cities | text | Locations to search |
| Discovery | Geo-radius | map | Search within radius |

### Auto-Computed Parameters (not editable)

| Section | Parameter | Derived from |
|---|---|---|
| Limits | Views per hour | Views per day / 24 |
| Limits | Views per minute | Views per day / 1440 |
| View | Min delay | Views per day (uniform distribution) |
| View | Max delay | Views per day (uniform distribution) |
| Queue | Parallel workers | Views per day (1–3) |
| Monitoring | Check interval | Views per day (15–60s) |
| Discovery | Search interval | Queue state (adaptive) |
| Discovery | Results per search | Queue gap (adaptive) |

## Environment Variables

All variables are set in `.env` (project root) or via container environment.
See `.env.example` for a ready-to-copy template with all variables and descriptions.

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | `StoryWatcher` | Application name (display only) |
| `SECRET_KEY` | `dev-secret-key` | Secret key for the app. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DEBUG` | `false` | Enable debug mode (verbose logging) |
| `STORYWATCHER_API_TOKEN` | — | API token protecting the web panel (sent in `X-API-Token` header). Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `TELEGRAM_API_ID` | — | Telegram API ID from my.telegram.org (**required**) |
| `TELEGRAM_API_HASH` | — | Telegram API Hash from my.telegram.org (**required**) |
| `WEB_PORT` | `8081` | External port for the web interface |
| `POSTGRES_USER` | `storywatcher` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `storywatcher` | PostgreSQL password |
| `POSTGRES_DB` | `storywatcher` | PostgreSQL database name |
| `DATABASE_URL` | `postgresql+psycopg2://storywatcher:storywatcher@postgres:5432/storywatcher` | Database URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis URL |
| `SESSIONS_DIR` | `/data/sessions` | Telegram session files directory |
| `STORYWATCHER_SYNC_INTERVAL` | `30` | Story sync interval (seconds) |
| `STORYWATCHER_WORKER_POLL` | `1` | Worker poll interval (seconds) |
| `TELEGRAM_PROXY_ENABLED` | `false` | Enable proxy for Telegram |
| `TELEGRAM_PROXY_HOST` | — | Proxy host |
| `TELEGRAM_PROXY_PORT` | — | Proxy port |
| `TELEGRAM_PROXY_SECRET` | — | MTProto proxy secret |
| `NEXT_PUBLIC_API_URL` | `http://localhost:9000/api` | Frontend API base URL (set to `/api` in Docker via Nginx) |

User settings (language, time zone, daily views limit, filters) are configured
via the Settings page, stored in the database, and saved automatically on every
change. All technical parameters are derived from the daily views limit.

## Pages

| Route | Name | Description |
|---|---|---|
| `/` | Dashboard | Account stats, view charts, recent activity |
| `/accounts` | Accounts | Manage Telegram accounts: add, start, pause, delete |
| `/stories` | Stories | All discovered Stories with authors, view status, reactions |
| `/queue` | Queue | Current view task queue: status, priority, errors |
| `/history` | History | Full log of all views and system actions |
| `/analytics` | Analytics | Own Stories analytics: views, reactions, ER, viewers |
| `/settings` | Settings | App configuration: language, theme, Telegram, limits, filters |
| `/discovery` | Story Search | Auto-search by hashtags and geolocation, collected places map |
| `/whitelist` | Whitelist | Manage allowed authors list |
| `/blacklist` | Blacklist | Manage blocked authors list |
| `/statistics` | Statistics | Additional statistics |

## Telegram Limit (important)

Telegram may impose flood wait limits on accounts that perform too many
automated actions. The app handles this gracefully — the worker backs off
instead of retrying in a tight loop — but you should be aware:

- Excessive viewing may trigger `FLOOD_WAIT` status on your account
- The app respects Telegram's rate limiting and pauses accordingly
- Rate limits are automatically computed from your daily views setting
- The system distributes views evenly throughout the day to avoid spikes

Going beyond safe limits is at your own risk — Telegram may restrict
or ban accounts that exhibit bot-like behavior.

## Queue Safety

- All view actions run sequentially with auto-computed delays between requests
- Daily limit enforced before every view — never exceeded
- Whitelist is excluded at queue creation and re-checked before every action
- Blacklisted authors are always skipped
- Safe Mode: re-checks the actual state before each view
- Primary rate limit → the queue pauses until reset (auto-resumes)
- Secondary rate limit → Retry-After or exponential backoff
- Transient (network) errors retry with delays (up to the configured maximum)
- After a server restart the queue resumes automatically (tracks daily progress)
- Stale PROCESSING items are auto-recovered after timeout
- Adaptive parallelism (1–3 workers) based on daily views limit

## Project Structure

```
TG-Story-Watcher/
├── frontend/                      # Next.js 14 + React 18 + TypeScript + Tailwind
│   ├── app/
│   │   ├── page.tsx               # Dashboard
│   │   ├── accounts/              # Telegram accounts
│   │   ├── stories/               # Stories list
│   │   ├── queue/                 # View queue
│   │   ├── history/               # Operation history
│   │   ├── analytics/             # Account analytics
│   │   ├── settings/              # App settings (single-param config)
│   │   ├── discovery/             # Story search / hashtags / geo
│   │   ├── whitelist/             # Whitelist
│   │   ├── blacklist/             # Blacklist
│   │   └── statistics/            # Additional stats
│   ├── components/                # UI components, Sidebar, PlacesMap
│   ├── lib/                       # API client, theme, hooks, formatters
│   ├── Dockerfile
│   └── package.json
├── backend/                       # Python 3.12 + FastAPI + SQLAlchemy
│   ├── app/
│   │   ├── api/                   # Routes (auth, accounts, stories, queue, ...)
│   │   ├── analytics/             # Analytics service
│   │   ├── filters/               # Filter engine
│   │   ├── queue/                 # Queue processor
│   │   ├── services/              # Business logic (settings with auto-derivation)
│   │   ├── stories/               # Story monitoring and discovery
│   │   ├── telegram/              # MTProto client (Telethon)
│   │   ├── workers/               # Background workers (adaptive scheduler + queue)
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── db.py                  # SQLAlchemy engine and sessions
│   │   ├── main.py                # FastAPI application
│   │   └── models.py              # ORM models
│   ├── migrate_limits_derived.py  # Migration: recalculate derived settings
│   ├── Dockerfile
│   ├── requirements.txt
│   └── healthcheck.sh
├── docker/
│   └── nginx.conf                 # Nginx reverse proxy config
├── docker-compose.yml
├── .env.example
├── .env
└── LICENSE
```

## API (summary)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/register` | Register a new user |
| `POST` | `/api/login` | Login (returns API token) |
| `GET` | `/api/me` | Current user |
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
| `GET` | `/api/stories` | List Stories (pagination: `?limit=&offset=`) |
| `GET` | `/api/stories/count` | Story count |
| `GET` | `/api/stories/{id}` | Story details |
| `POST` | `/api/stories/{id}/view` | Add Story to view queue |
| `POST` | `/api/stories/{id}/skip` | Skip Story |
| `GET` | `/api/queue` | Queue items |
| `GET` | `/api/queue/count` | Queue count |
| `PATCH` | `/api/queue/{id}` | Update queue item |
| `POST` | `/api/queue/{id}/cancel` | Cancel queue item |
| `POST` | `/api/queue/{id}/retry` | Retry queue item |
| `DELETE` | `/api/queue/clear` | Clear queue |
| `GET` | `/api/rules` | List automation rules |
| `POST` | `/api/rules` | Create rule |
| `PATCH` | `/api/rules/{id}` | Update rule |
| `DELETE` | `/api/rules/{id}` | Delete rule |
| `POST` | `/api/rules/{id}/enable` | Enable rule |
| `POST` | `/api/rules/{id}/disable` | Disable rule |
| `POST` | `/api/rules/{id}/test` | Test rule |
| `GET` | `/api/whitelist` | List whitelist |
| `POST` | `/api/whitelist` | Add to whitelist |
| `DELETE` | `/api/whitelist/{id}` | Remove from whitelist |
| `GET` | `/api/blacklist` | List blacklist |
| `POST` | `/api/blacklist` | Add to blacklist |
| `DELETE` | `/api/blacklist/{id}` | Remove from blacklist |
| `GET` | `/api/history/views` | View history (pagination) |
| `GET` | `/api/history/views/count` | View count |
| `GET` | `/api/history/activity` | Activity log (pagination) |
| `GET` | `/api/history/activity/count` | Activity count |
| `GET` | `/api/dashboard` | Dashboard data (cards, charts, activity) |
| `GET` | `/api/stats` | General statistics |
| `GET` | `/api/analytics/overview` | Analytics overview (`?days=`) |
| `GET` | `/api/analytics/stories` | Stories with analytics |
| `GET` | `/api/analytics/stories/{id}` | Story analytics details |
| `GET` | `/api/analytics/stories/{id}/views` | Story views |
| `GET` | `/api/analytics/stories/{id}/viewers` | Story viewers |
| `GET` | `/api/analytics/stories/{id}/reactions` | Story reactions |
| `GET` | `/api/analytics/recent-events` | Recent events (`?limit=`) |
| `POST` | `/api/analytics/sync` | Sync analytics (`?account_id=`) |
| `GET` | `/api/discovery/config` | Discovery config |
| `POST` | `/api/discovery/config` | Save discovery config |
| `GET` | `/api/discovery/places` | Collected geo-places (`?q=`) |
| `GET` | `/api/discovery/places/count` | Places count |
| `GET` | `/api/discovery/geocode` | Geocoding (`?q=`) |
| `POST` | `/api/discovery/search` | Run discovery search |
| `GET` | `/api/settings` | Get all settings |
| `POST` | `/api/settings` | Save settings |
| `PUT` | `/api/settings` | Replace all settings |

Full interactive docs: http://localhost:9000/docs (when running the backend directly).

## Database

PostgreSQL by default (Docker deployment), with SQLite fallback for quick
local runs without a running Postgres. The schema is created automatically
on startup.

Main tables: `users`, `telegram_accounts`, `stories`, `story_stats_snapshots`,
`story_viewers`, `story_reaction_stats`, `story_queue`, `story_views`,
`whitelist`, `blacklist`, `automation_rules`, `activity_logs`,
`settings_store`, `auth_sessions`, `geo_places`.

## Multi-User Isolation

All user-owned data must be accessed through the authenticated application
token. The following resources are isolated per user:

- Telegram accounts
- Stories and Story statistics
- Viewers and reactions
- Queues and action history
- Whitelist and Blacklist
- Rules
- Tags and hashtags
- Discovery settings and selected locations
- Dashboard and account statistics

The collected `GeoPlace` catalog is intentionally shared. User-specific
tags, selections, and search configuration are stored separately and are
not inherited from another user.

## Troubleshooting

| Symptom | Solution |
|---|---|
| Telegram code is not sent on the first click | Check `docker compose logs --tail=200 backend`. The login flow recreates the in-memory client on disconnect errors. Wait briefly and request a fresh code. |
| Telegram profile is missing from the list | Refresh the Accounts page after authorization. Verify that the backend returned `200` for the confirm-code/confirm-password endpoint. |
| A user sees data from another account | Sign out, clear browser site storage, and sign in again. Do not reuse an old application token between browser profiles. |
| Services are unhealthy | Run `docker compose ps` and `docker compose logs --tail=200 backend worker postgres redis`. Ensure PostgreSQL and Redis are healthy and Telegram API credentials are in `.env`. |
| `FLOOD_WAIT` on Telegram account | Expected behavior — Telegram rate-limited the account. The worker backs off automatically. Wait for the flood wait to expire and check your rate limit settings. |
| Dashboard data is stale | Click the refresh button; after queue processing the data updates automatically. |
| Frontend shows old bundle after changes | Hard refresh the browser (Ctrl+Shift+R) to clear cached assets. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code conventions,
and a self-hosting deployment guide.

## License

MIT — see [LICENSE](LICENSE).

---

Made with ❤️ by [devlewicki](https://github.com/devlewicki)
