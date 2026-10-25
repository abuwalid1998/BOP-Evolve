#!/bin/sh
# Container entrypoint: api | worker | migrate | seed | test | <any command>
set -e

wait_for_db() {
  python - <<'PY'
import sys, time
from sqlalchemy import text
from app.db import engine
for attempt in range(60):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"Waiting for database ({attempt + 1}/60): {exc.__class__.__name__}", flush=True)
        time.sleep(2)
sys.exit("Database not reachable")
PY
}

case "$1" in
  api)
    wait_for_db
    alembic upgrade head
    if [ "${SEED_ON_START:-true}" = "true" ]; then
      python -m app.seed.seed_mock_data --if-empty
    fi
    python -m app.seed.upgrade
    if [ "${UVICORN_RELOAD:-false}" = "true" ]; then
      exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    fi
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    wait_for_db
    exec python -m app.pipeline.worker
    ;;
  migrate)
    wait_for_db
    alembic upgrade head
    exec python -m app.seed.upgrade
    ;;
  seed)
    wait_for_db
    shift
    exec python -m app.seed.seed_mock_data "$@"
    ;;
  test)
    exec python -m pytest -q
    ;;
  *)
    exec "$@"
    ;;
esac
