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

# Check deployment permissions and SSH identity requirements without a real login.
python3 - <<'PY'
from pathlib import Path

deploy = Path(".github/workflows/deploy.yml").read_text()
diagnose = Path(".github/workflows/diagnose.yml").read_text()
for name, source in [("deploy", deploy), ("diagnose", diagnose)]:
    assert "branches: [prod]" in source, f"{name}: prod-only workflow missing"
    assert "github.ref == 'refs/heads/prod'" in source, f"{name}: prod-only job guard missing"
    assert "environment: production" in source, f"{name}: prod environment missing"
    assert "secrets.DEPLOY_PASSWORD" in source, f"{name}: password secret missing"
    assert "secrets.DEPLOY_KNOWN_HOSTS" in source, f"{name}: verified host key secret missing"
    assert "appleboy/ssh-action@v1" in source, f"{name}: expected SSH action missing"
    assert "fingerprint: ${{ steps.hostkey.outputs.fingerprint }}" in source, f"{name}: SSH fingerprint missing"
    assert "ssh-keygen -F" in source and "ssh-keygen -lf" in source
    assert "DEPLOY_SSH_PRIVATE_KEY" not in source
    assert "sshpass" not in source
assert "appleboy/scp-action@v1" in deploy, "deploy: SCP action missing"
assert "workflow_dispatch:" in diagnose, "diagnose: manual rerun missing"
assert "on:" in deploy and "on:" in diagnose
print("Mira Appleboy/password/pinned-host contracts OK (static check only)")
PY
