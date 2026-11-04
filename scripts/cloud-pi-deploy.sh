#!/usr/bin/env bash
# Production-only; called by Infra's guarded workflow.
set -Eeuo pipefail
umask 077
APP=/opt/cloud-pi
cd "$APP"
test -s dist/mira-cloud-pi-linux-amd64.tar.gz
test -s dist/mira-cloud-pi-linux-amd64.tar.gz.sha256
test -s dist/compose.yaml
test -s dist/version.txt
test -s secrets/agent.env || { echo "[cloud-pi] missing private configuration" >&2; exit 1; }
SHA="$(cat dist/version.txt)"
[[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || exit 1
export CLOUD_PI_IMAGE="mira-cloud-pi:$SHA"
export CLOUD_PI_DATA_DIR="$APP/data"
export CLOUD_PI_SECRETS_FILE="$APP/secrets/agent.env"
(
  cd dist
  sha256sum -c mira-cloud-pi-linux-amd64.tar.gz.sha256
  gzip -t mira-cloud-pi-linux-amd64.tar.gz
)
docker compose -f dist/compose.yaml config --quiet

# Load verified image before stopping the previous Cloud Pi.
echo "[cloud-pi] loading pinned image"
gzip -dc dist/mira-cloud-pi-linux-amd64.tar.gz | docker load
docker image inspect "$CLOUD_PI_IMAGE" --format '{{.Architecture}}' | grep -qx amd64

# UID 1000 in the container must read the private env and write state.
docker compose -f dist/compose.yaml run --rm --no-deps --entrypoint /bin/sh cloud-pi \
  -c 'test -r /run/secrets/agent.env && test -w /var/lib/cloud-pi' >/dev/null || {
    echo "[cloud-pi] runtime cannot access private configuration/state" >&2
    exit 1
  }

if test -n "$(docker compose -f dist/compose.yaml ps --all --quiet cloud-pi)"; then
  docker compose -f dist/compose.yaml stop cloud-pi
fi
if test -d data && find data -type f -print -quit | grep -q .; then
  mkdir -p backups
  chmod 700 backups
  tar -czf "backups/cloud-pi-data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" data
fi

# Do not pass --remove-orphans: an unrelated container must never be deleted.
docker compose -f dist/compose.yaml up -d --no-build --pull never
for _ in $(seq 1 24); do
  if curl -fsS -m 3 http://127.0.0.1:8787/v1/health >/dev/null 2>&1; then
    docker compose -f dist/compose.yaml ps
    printf '%s\n' "$SHA" > .deployed-cloud-pi-sha
    echo "[cloud-pi] local API ready (does not prove both IM channels or Guanlan)"
    exit 0
  fi
  sleep 3
done
echo "[cloud-pi] health failed, inspect only Cloud Pi" >&2
docker compose -f dist/compose.yaml ps || true
exit 1
