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
    "secrets.DEPLOY_KNOWN_HOSTS",
    "StrictHostKeyChecking=yes",
    "sshpass -e ssh",
    "sshpass -e scp",
    "GlobalKnownHostsFile=/dev/null",
    "sha256sum -c",
    "scripts/cloud-pi-deploy.sh",
]:
    assert text in w, text
assert "appleboy/ssh-action" not in w and "appleboy/scp-action" not in w
assert "StrictHostKeyChecking=no" not in w
assert "docker build" not in w
assert "docker compose down -v" not in w
script = Path("scripts/cloud-pi-deploy.sh").read_text()
assert "has_owner_gateway" in script and "owner_status" in script
assert "http://127.0.0.1:8793/v1/status" in script
assert "docker-compose.yml" not in w
print("Cloud Pi transport contract OK: static only")
PY


# The private provisioning job is manual, prod-only and host-key verified.
python3 scripts/test_cloud_pi_build_env.py
python3 - <<'PY'
from pathlib import Path
p=Path(".github/workflows/cloud-pi-provision.yml").read_text()
for required in ["workflow_dispatch:", "refs/heads/prod", "inputs.confirm == 'PROVISION'",
                 "environment: production", "DEPLOY_KNOWN_HOSTS", "StrictHostKeyChecking=yes",
                 "sshpass -e ssh", "scripts/cloud-pi-build-env.py"]:
    assert required in p, required
assert "StrictHostKeyChecking=no" not in p
assert "docker compose up" not in p and "docker run" not in p
print("Cloud Pi private provision contract OK (static only)")
PY
