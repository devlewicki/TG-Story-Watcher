# StoryWatcher

Self-hosted web application for automated monitoring and viewing of Telegram Stories.

StoryWatcher connects to your regular Telegram account via the MTProto API, watches for
available new stories, filters them by configurable rules, and automatically marks
matching stories as viewed.

> **Important limitation:** "unknown users" does NOT mean the app can find stories of every
> Telegram user. Basic monitoring works with stories already available to the connected
> account. Global discovery of new users is only possible through Telegram's intended
> search mechanisms (hashtags and geolocation near-tags). See the Telegram Stories API docs:
> https://core.telegram.org/api/stories

## Features (MVP)

- Telegram authorization via MTProto (phone → code → 2FA password)
- Fetching available new stories via `stories.getAllStories`
- Real-time update tracking
- Filtering: non-contact users, whitelist, blacklist, username patterns
- Configurable view queue with random delay
- Per-account rate limits (per minute / hour / day)
- Automatic processing of the queue
- Full action history
- Dashboard with activity charts
- Dark / light themes
- Docker Compose deployment (single command)

## Tech stack

| Layer       | Tech                                             |
|-------------|--------------------------------------------------|
| Backend     | Python 3.12, FastAPI, Telethon, SQLAlchemy, Redis |
| Frontend    | Next.js, React, TypeScript, Tailwind CSS         |
| Infra       | Docker, Docker Compose, PostgreSQL, Redis, Nginx |

## Quick start

1. Fill in your Telegram API credentials:

```bash
cp .env.example .env
```

Get `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from https://my.telegram.org.

2. Start everything:

```bash
docker compose up -d --build
```

3. Open http://localhost

## Statuses

Account statuses: `ACTIVE`, `PAUSED`, `AUTH_REQUIRED`, `ERROR`, `FLOOD_WAIT`,
`DISCONNECTED`, `BANNED_OR_RESTRICTED`.

Queue statuses: `PENDING`, `WAITING_DELAY`, `PROCESSING`, `VIEWED`, `SKIPPED`, `FAILED`,
`EXPIRED`, `CANCELLED`.

## Security

- Telegram sessions live only on the backend, never sent to the frontend
- Secrets only via `.env`
- 2FA password is never stored
- API is auth-protected
- Ability to delete a Telegram session

## License

MIT