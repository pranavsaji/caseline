#!/usr/bin/env bash
# Dedicated local Postgres for Caseline development.
#
# Runs its own cluster on port 5455 (never touches any system/brew cluster),
# data in .tmp/pgdata, trust auth on localhost only — dev convenience, not a
# production posture. Usage:
#
#   scripts/dev_db.sh start | stop | status | reset
#
# After `start`, CASELINE_DATABASE_URL=postgresql://caseline_owner@127.0.0.1:5455/caseline
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATADIR="$REPO/.tmp/pgdata"
PORT=5455
LOG="$DATADIR/pg.log"

find_bindir() {
  for d in "$(dirname "$(command -v initdb 2>/dev/null || true)")" /opt/homebrew/opt/postgresql@*/bin; do
    if [ -n "$d" ] && [ -x "$d/initdb" ] && [ -x "$d/pg_ctl" ] && [ -x "$d/postgres" ]; then
      echo "$d"; return
    fi
  done
  echo "no postgres server binaries found (brew install postgresql@16)" >&2; exit 1
}
BIN="$(find_bindir)"

init() {
  if [ ! -d "$DATADIR" ]; then
    mkdir -p "$DATADIR"
    "$BIN/initdb" -D "$DATADIR" -U caseline_owner --auth=trust --no-sync >/dev/null
    # localhost only; trust is acceptable for a dev-only cluster bound to loopback
    echo "listen_addresses = '127.0.0.1'" >> "$DATADIR/postgresql.conf"
    echo "port = $PORT" >> "$DATADIR/postgresql.conf"
  fi
}

case "${1:-status}" in
  start)
    init
    if "$BIN/pg_ctl" status -D "$DATADIR" >/dev/null 2>&1; then
      echo "already running on port $PORT"
    else
      "$BIN/pg_ctl" start -D "$DATADIR" -w -l "$LOG" >/dev/null
      echo "started on port $PORT (log: $LOG)"
    fi
    "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U caseline_owner -d postgres \
      -tc "SELECT 1 FROM pg_database WHERE datname='caseline'" | grep -q 1 ||
      "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U caseline_owner -d postgres \
        -c "CREATE DATABASE caseline" >/dev/null
    echo "CASELINE_DATABASE_URL=postgresql://caseline_owner@127.0.0.1:$PORT/caseline"
    ;;
  stop)
    "$BIN/pg_ctl" stop -D "$DATADIR" -m fast
    ;;
  status)
    "$BIN/pg_ctl" status -D "$DATADIR" || true
    ;;
  reset)
    "$BIN/pg_ctl" stop -D "$DATADIR" -m immediate 2>/dev/null || true
    rm -rf "$DATADIR"
    "$0" start
    ;;
  *)
    echo "usage: $0 start|stop|status|reset" >&2; exit 1
    ;;
esac
