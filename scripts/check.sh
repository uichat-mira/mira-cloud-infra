#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
bash -n scripts/deploy.sh
bash -n scripts/check.sh
bash -n scripts/deploy-moyu-site.sh
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
assert svc["image"] == "calciumion/new-api:v1.0.0-rc.47", "unexpected/unreviewed image"
assert len(svc["ports"]) == 1, "unexpected exposed ports"
port = svc["ports"][0]
assert port["host_ip"] == "127.0.0.1", "service must be loopback-only"
assert int(port["published"]) == 3000 and int(port["target"]) == 3000
assert any(v["target"] == "/data" and v["type"] == "bind" for v in svc["volumes"])
assert int(svc["mem_limit"]) <= 512 * 1024 * 1024, "2 GiB host budget exceeded"
print("Mira config contract: OK (no runtime or network verification)")
PY

# Check password-based Appleboy, deployment guard, and no additional fingerprint preflight.
python3 - <<'PY'
from pathlib import Path
deploy = Path(".github/workflows/deploy.yml").read_text()
diagnose = Path(".github/workflows/diagnose.yml").read_text()
for name, source in [("deploy", deploy), ("diagnose", diagnose)]:
    assert "branches: [prod]" in source, f"{name}: prod-only trigger missing"
    assert "github.ref == 'refs/heads/prod'" in source, f"{name}: prod-only job guard missing"
    assert "environment: production" in source, f"{name}: production environment missing"
    for secret in ["DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_PASSWORD", "DEPLOY_PORT"]:
        assert "secrets." + secret in source, f"{name}: {secret} missing"
    assert "appleboy/ssh-action@v1" in source, f"{name}: SSH action missing"
    assert "password: ${{ secrets.DEPLOY_PASSWORD }}" in source
    assert "fingerprint:" not in source, f"{name}: unexpected fingerprint"
    assert "resolve-host-fingerprint" not in source
    assert "sshpass" not in source
    assert "DEPLOY_SSH_PRIVATE_KEY" not in source
assert "vars.MIRA_DEPLOY_ENABLED == 'true'" in deploy
assert "appleboy/scp-action@v1" in deploy
assert "workflow_dispatch:" in diagnose
assert "DOCKER=NOT_INSTALLED" in diagnose
assert not Path("scripts/resolve-host-fingerprint.sh").exists()
print("Mira Appleboy password SSH, unattended diagnose and guarded deploy: OK (static only)")
PY
