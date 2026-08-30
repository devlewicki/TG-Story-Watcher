#!/bin/sh
# Healthcheck for the worker container.
# Checks two things:
#   1. The process with PID 1 is still alive (it is, otherwise this wouldn't run).
#   2. The heartbeat file was written within the last 2× the poll interval
#      (default poll=1s → threshold=30s to account for scheduler cycles).
#
# If either check fails, exit 1 → Docker marks container unhealthy → restart.

HEARTBEAT="${WORKER_HEARTBEAT:-/tmp/worker_heartbeat}"
POLL_INTERVAL="${STORYWATCHER_WORKER_POLL:-1}"
# Allow 30× the poll interval (with a floor of 20s) for the heartbeat to be stale.
THRESHOLD=$(awk "BEGIN{t=30*${POLL_INTERVAL}; if(t<20) t=20; printf \"%.0f\", t}")

if [ ! -f "$HEARTBEAT" ]; then
  echo "heartbeat file missing" >&2
  exit 1
fi

HEARTBEAT_AGE=$(awk "BEGIN{printf \"%.0f\", $(date +%s) - $(cat "$HEARTBEAT")}")

if [ "$HEARTBEAT_AGE" -gt "$THRESHOLD" ] 2>/dev/null; then
  echo "heartbeat stale (${HEARTBEAT_AGE}s > ${THRESHOLD}s)" >&2
  exit 1
fi

exit 0
