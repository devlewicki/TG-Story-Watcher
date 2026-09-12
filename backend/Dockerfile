FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg2, telethon crypto, and pg_dump/pg_restore
# (required by the admin BackupService for PostgreSQL backups).
#
# pg_dump/pg_restore are pinned to the postgresql-client MAJOR VERSION that
# matches the postgres service in docker-compose (postgres:16-alpine).
# pg_dump writes its target server version into the dump header; a dump made
# by a NEWER client (e.g. 17) cannot be restored by an OLDER server's
# pg_restore ("unsupported version (1.16) in file header"), which silently
# breaks backup/restore after a Debian base-image bump. The PGDG repo
# provides versioned clients for Debian trixie (Debian ships only 17).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME:-trixie}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY healthcheck.sh /usr/local/bin/healthcheck
RUN chmod +x /usr/local/bin/healthcheck

EXPOSE 8000

# The compose file overrides the command for the worker/scheduler services.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]