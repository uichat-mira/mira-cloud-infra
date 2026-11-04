#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
bash -n scripts/cloud-pi-deploy.sh
SHA="$(cat cloud-pi/version.txt)"
[[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || {
  echo "Cloud Pi release pin must be a full immutable commit SHA" >&2
  exit 1
}
python3 - <<'PY'
from pathlib import Path
w = Path(".github/workflows/cloud-pi-deploy.yml").read_text()
for text in [
    "branches: [prod]",
    "github.ref == 'refs/heads/prod'",
    "vars.MIRA_CLOUD_PI_DEPLOY_ENABLED == 'true'",
    "environment: production",
    "secrets.DEPLOY_HOST",
    "secrets.DEPLOY_PASSWORD",
    "appleboy/ssh-action@0ff4204d59e8e51228ff73bce53f80d53301dee2",
    "appleboy/scp-action@ff85246acaad7bdce478db94a363cd2bf7c90345",
    "sha256sum -c",
    "scripts/cloud-pi-deploy.sh",
]:
    assert text in w, text
assert "docker build" not in w
assert "docker compose down -v" not in w
script = Path("scripts/cloud-pi-deploy.sh").read_text()
assert "has_owner_gateway" in script and "owner_status" in script
assert "http://127.0.0.1:8793/v1/status" in script
assert "docker-compose.yml" not in w
print("Cloud Pi transport contract OK: static only")
PY
