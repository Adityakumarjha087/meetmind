#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    if [ "${SEED_DEMO:-false}" = "true" ]; then python -m app.seed; fi
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" --proxy-headers --no-access-log
    ;;
  worker)
    exec celery -A app.worker worker --loglevel=INFO --concurrency="${WORKER_CONCURRENCY:-2}"
    ;;
  *)
    exec "$@"
    ;;
esac
