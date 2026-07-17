#!/usr/bin/env bash
# Railway service entrypoint: API + event worker in one service.
#
# Deliberate pilot-scale choice: the cms_sync worker (chaser, threads,
# referrals, CMS sync, alerts) rides in the same container as the API so a
# single Railway service is a complete backend. If either process dies the
# container exits non-zero and Railway restarts it. Scale-out path: split
# the worker into its own Railway service with the same image and
# `python -m workers.cms_sync` as the start command.
set -euo pipefail

# One image, two services: CASELINE_SERVICE=agent runs the LiveKit voice
# worker (its /health rides the daemon thread in agent.py on $PORT);
# anything else runs the API + cms_sync worker below.
if [ "${CASELINE_SERVICE:-api}" = "agent" ]; then
  exec python -m agent.agent start
fi

uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!
python -m workers.cms_sync &
WORKER_PID=$!

trap 'kill "$API_PID" "$WORKER_PID" 2>/dev/null || true' TERM INT

# Exit when the first process exits; Railway's restart policy takes it from there.
wait -n "$API_PID" "$WORKER_PID"
exit 1
