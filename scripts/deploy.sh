#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="/opt/mira-cloud-infra"
ARCHIVE="$APP_DIR/new-api-image.tar.gz"

cd "$APP_DIR"
test -s "$ARCHIVE" || { echo "[deploy] image archive missing" >&2; exit 1; }
gzip -t "$ARCHIVE"

mkdir -p data backups
chmod 700 data backups

echo "[deploy] loading pinned image delivered by GitHub Actions"
gzip -dc "$ARCHIVE" | docker load
rm -f "$ARCHIVE"

# Stop the running SQLite writer before taking a consistent filesystem snapshot.
if docker compose ps --status running --services | grep -Fxq new-api; then
  echo "[deploy] stopping New API for SQLite backup"
  docker compose stop new-api
fi
if find data -type f -print -quit | grep -q .; then
  backup="backups/data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
  tar -czf "$backup" data
  echo "[deploy] persistent data snapshot saved"
fi

docker compose up -d --pull never --remove-orphans

for i in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:3000/api/status >/dev/null 2>&1; then
    echo "[deploy] local API smoke OK"
    docker compose ps
    exit 0
  fi
  sleep 2
done

echo "[deploy] local API smoke failed" >&2
docker compose ps || true
docker compose logs --tail=100 new-api || true
exit 1
