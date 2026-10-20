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
