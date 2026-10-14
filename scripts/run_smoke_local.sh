#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-/home/ubuntu/credit-workers/task-8.4-be/.venv/bin/python}"
DB_NAME="smoke_$(date +%s)_${RANDOM}"
DB_CONTAINER="task-63-search-db-1"
PORT="$("$PYTHON" - <<'PY'
import random, socket
ports = list(range(4000, 5000))
random.shuffle(ports)
for port in ports:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        continue
    s.close()
    print(port)
    break
else:
    raise SystemExit("No free local port in 4000-4999")
PY
)"
LOG="$(mktemp /tmp/smoke-api.XXXXXX.log)"
SERVER_PID=""
DB_CREATED=0
cleanup() {
  status=$?
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ "$DB_CREATED" == 1 ]]; then
    docker exec "$DB_CONTAINER" psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" >/dev/null || true
  fi
  if [[ $status -ne 0 ]]; then
    echo "Smoke failed; server log: $LOG" >&2
    tail -80 "$LOG" >&2 || true
  else
    rm -f "$LOG"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM
docker exec "$DB_CONTAINER" pg_isready -U postgres >/dev/null
docker exec "$DB_CONTAINER" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DB_NAME\";" >/dev/null
DB_CREATED=1
export DEBUG=True SECRET_KEY=test SEARCH_ENABLED=False REDIS_CACHE_URL=redis://127.0.0.1:6379/14
export DATABASE_URL=
export DB_USER=postgres DB_PASSWORD=postgres DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME
export THROTTLE_RATE_ANON=1000/min THROTTLE_RATE_USER=1000/min THROTTLE_RATE_BURST=100/sec
export THROTTLE_RATE_REVIEW_WRITE=50/hour THROTTLE_RATE_AUTH_BURST=100/min THROTTLE_RATE_AUTH_ANON=100/min THROTTLE_RATE_AUTH_USER=1000/min
cd "$ROOT"
"$PYTHON" manage.py migrate --noinput
"$PYTHON" scripts/seed_smoke_data.py
"$PYTHON" manage.py runserver "127.0.0.1:$PORT" --noreload >"$LOG" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 80); do
  if "$PYTHON" - "$PORT" <<'PY'
import socket, sys
s=socket.socket(); s.settimeout(.2)
ok=s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
s.close(); sys.exit(0 if ok else 1)
PY
  then break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then cat "$LOG"; exit 1; fi
  sleep .25
done
SMOKE_BASE_URL="http://127.0.0.1:$PORT" "$PYTHON" scripts/smoke_api.py
