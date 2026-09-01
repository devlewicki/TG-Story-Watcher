# TG Story Watcher

Self-hosted web application for monitoring Telegram Stories through the **Telegram MTProto User API**.
The application supports multiple local users. Each user has an isolated workspace with their own
Telegram accounts, tags, search settings, rules, queues, history, and analytics.

## Main features

- Local registration and login with first name, last name, email, and password
- Passwords stored as secure PBKDF2 hashes; plain passwords are never stored
- Multiple users with data isolation by authenticated user
- Telegram user-account authorization through MTProto:
  - phone number;
  - Telegram confirmation code;
  - optional Telegram 2FA password
- Multiple Telegram profiles per application user
- Automatic Telegram profile identity sync: name, surname, username, phone, and Telegram ID
- Monitoring and automatic viewing of available Telegram Stories
- Filtering and rules for monitored Stories
- Per-user tags, whitelist, blacklist, search configuration, and discovery settings
- Shared GeoPlace database with private user selections and search settings
- Queue management, delays, rate limits, and activity history
- Account dashboard with charts and recent actions
- Account analytics:
  - active and archived own Stories;
  - views, reactions, forwards, and ER;
  - viewer list when Telegram provides it;
  - reaction breakdown;
  - time-based statistics snapshots;
  - recent views and reactions;
  - best Stories and period filters
- Responsive web interface with dark/light theme
- Docker Compose deployment with PostgreSQL, Redis, worker, frontend, and Nginx

## Architecture

```text
Browser
   │
   ▼
Nginx ───────────────► Next.js frontend
   │
   ▼
FastAPI backend ─────► PostgreSQL
   │                     Redis
   │
   ▼
MTProto Telegram client
   │
   ▼
Combined background worker
```

The backend exposes the REST API and handles user requests. The combined worker performs periodic
Story synchronization and queue processing. Telegram session files are kept in the backend volume
and are not sent to the browser.

## Technology stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Telethon, SQLAlchemy |
| Frontend | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Database | PostgreSQL 16 |
| Cache / coordination | Redis 7 |
| Background processing | Combined Python worker with APScheduler-compatible scheduling |
| Reverse proxy | Nginx |
| Deployment | Docker Compose |

## Requirements

- Docker Engine and Docker Compose v2
- Telegram API credentials:
  - `TELEGRAM_API_ID`
  - `TELEGRAM_API_HASH`
- A Telegram user account for MTProto authorization

Create Telegram API credentials at:

<https://my.telegram.org>

## Quick start

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Set Telegram credentials in `.env`:

```dotenv
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
```

3. Build and start all services:

```bash
docker compose up -d --build
```

4. Open the application:

```text
http://localhost:8081
```

The external port can be changed with `WEB_PORT` in `.env`.

Useful commands:

```bash
# View service status
docker compose ps

# Follow backend logs
docker compose logs -f backend

# Follow worker logs
docker compose logs -f worker

# Rebuild after source changes
docker compose up -d --build backend worker frontend
```

## First use

1. Register a local application user.
2. Log in with email and password.
3. Open **Accounts**.
4. Click **Add account**.
5. Enter the Telegram phone number.
6. Enter the code received from Telegram.
7. Enter the Telegram 2FA password if requested.
8. Confirm that the Telegram profile card contains the name, username, phone, and ID.
9. Configure tags, rules, monitoring, and queue settings.

A Telegram account belongs to the application user who authorizes it. The same Telegram account
cannot be attached to another application user.

## Multi-user isolation

All user-owned data must be accessed through the authenticated application token. The following
resources are isolated per user:

- Telegram accounts;
- Stories and Story statistics;
- viewers and reactions;
- queues and action history;
- whitelist and blacklist;
- rules;
- tags and hashtags;
- discovery settings and selected locations;
- dashboard and account statistics.

The collected `GeoPlace` catalog is intentionally shared. User-specific tags, selections, and
search configuration are stored separately and are not inherited from another user.

## Account analytics

Analytics is available at:

```text
/analytics
```

The analytics module is separate from monitoring other users' Stories and works only with Stories
belonging to the authenticated user's Telegram accounts.

Typical API endpoints include:

```text
GET /api/analytics/overview
GET /api/analytics/stories
GET /api/analytics/stories/{story_id}
GET /api/analytics/stories/{story_id}/views
GET /api/analytics/stories/{story_id}/viewers
GET /api/analytics/stories/{story_id}/reactions
GET /api/analytics/recent-events
```

Telegram may not return a complete viewer list. Therefore the application distinguishes between
`views_count` and `known_viewers_count`; known viewers must not be interpreted as all viewers.

The engagement rate is calculated as:

```text
ER = (reactions + forwards) / views * 100
```

Missing Telegram values are not treated as real zeroes when the API does not provide them.

## Telegram authorization and sessions

Interactive login uses a memory-backed Telethon `StringSession` to avoid SQLite session locking
while entering the phone code. After successful authorization, the session is persisted for the
Telegram profile and the profile identity is refreshed through `get_me()`.

The application handles reconnects and Telegram authorization restarts during code delivery.
Telegram 2FA passwords are used only for the authorization request and are not stored.

Never commit the following files or values:

- `.env`;
- Telegram API hash;
- Telegram session files;
- application tokens;
- Telegram confirmation codes;
- Telegram 2FA passwords.

## Statuses

Account statuses may include:

```text
ACTIVE
PAUSED
AUTH_REQUIRED
ERROR
FLOOD_WAIT
DISCONNECTED
BANNED_OR_RESTRICTED
```

Queue statuses may include:

```text
PENDING
WAITING_DELAY
PROCESSING
VIEWED
SKIPPED
FAILED
EXPIRED
CANCELLED
```

## Operational notes

- Do not run multiple workers that open the same Telethon session files.
- The provided combined worker is used because SQLite-backed Telegram sessions cannot safely be
  opened by competing processes.
- Telegram flood waits are expected behavior. The worker should back off instead of retrying in a
  tight loop.
- Dashboard pages use the application database and cache; they should not make direct Telegram
  requests from the browser.
- After frontend changes, use a hard browser refresh if an old bundle is cached.

## Troubleshooting

### Telegram code is not sent on the first click

Check backend logs:

```bash
docker compose logs --tail=200 backend
```

The login flow recreates the in-memory client when Telegram returns a disconnected or authorization
restart error. Wait briefly and request a fresh code; old Telegram codes expire quickly.

### Telegram profile is missing from the list

Refresh the Accounts page after authorization. Verify that the backend returned `200` for
`POST /api/auth/confirm-code` or `POST /api/auth/confirm-password`, then inspect backend logs.
The profile card is populated from Telegram's `get_me()` response.

### A user sees data from another account

Sign out, clear the browser's site storage, and sign in again. Then inspect the authenticated
request token and backend logs. Do not reuse an old application token between browser profiles.

### Services are unhealthy

```bash
docker compose ps
docker compose logs --tail=200 backend worker postgres redis
```

Make sure PostgreSQL and Redis are healthy and that Telegram API credentials are present in `.env`.

## License

MIT
