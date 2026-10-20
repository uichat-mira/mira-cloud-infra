#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
bash -n scripts/deploy.sh
bash -n scripts/check.sh
command -v docker >/dev/null || { echo "docker CLI required" >&2; exit 1; }
docker compose -f docker-compose.yml config --quiet

python3 - <<'PY'
import json
import subprocess

spec = json.loads(subprocess.check_output(
    ["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
    text=True,
))
assert set(spec["services"]) == {"new-api"}, "v0 should deploy only New API"
svc = spec["services"]["new-api"]
assert svc["image"] == "calciumion/new-api:v1.0.0-rc.37", "unexpected/unreviewed image"
assert len(svc["ports"]) == 1, "unexpected exposed ports"
port = svc["ports"][0]
assert port["host_ip"] == "127.0.0.1", "service must be loopback-only"
assert int(port["published"]) == 3000 and int(port["target"]) == 3000
assert any(v["target"] == "/data" and v["type"] == "bind" for v in svc["volumes"])
assert int(svc["mem_limit"]) <= 512 * 1024 * 1024, "2 GiB host budget exceeded"
print("Mira config contract: OK (no runtime or network verification)")
PY

# Guard the deployment authentication contract without executing a real SSH login.
python3 - <<'PY'
from pathlib import Path

workflow = Path(".github/workflows/deploy.yml").read_text()
assert "branches: [prod]" in workflow
assert "github.ref == 'refs/heads/prod'" in workflow
assert "environment: production" in workflow
assert "secrets.DEPLOY_PASSWORD" in workflow
assert "secrets.DEPLOY_KNOWN_HOSTS" in workflow
assert "sshpass -e" in workflow
assert "StrictHostKeyChecking=yes" in workflow
assert "UserKnownHostsFile=" in workflow
assert "DEPLOY_SSH_PRIVATE_KEY" not in workflow, "legacy private-key contract"
assert "StrictHostKeyChecking=no" not in workflow
print("Mira SSH deployment contract: password + pinned host key (static check only)")
PY
