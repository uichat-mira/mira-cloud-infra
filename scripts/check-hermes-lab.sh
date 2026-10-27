#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f labs/hermes/compose.yaml config --quiet
python3 - <<'PY'
import json
import subprocess

config = json.loads(subprocess.check_output(
    ["docker", "compose", "-f", "labs/hermes/compose.yaml", "config", "--format", "json"],
    text=True,
))
assert config["name"] == "hermes-lab"
assert set(config["services"]) == {"hermes"}
svc = config["services"]["hermes"]
assert svc["image"] == "nousresearch/hermes-agent:stable"
assert svc["command"] == ["gateway", "run"]
assert svc["restart"] == "no"
assert int(svc["mem_limit"]) == 1024**3
assert int(svc["memswap_limit"]) == 1536 * 1024**2
assert float(svc["cpus"]) == 1.0
assert not svc.get("ports") and not svc.get("privileged", False)
assert svc.get("security_opt") == ["no-new-privileges:true"]
mounts = svc["volumes"]
assert len(mounts) == 1 and mounts[0]["target"] == "/opt/data"
assert mounts[0]["type"] == "bind"
assert not any("docker.sock" in str(m) for m in mounts)
assert set(config["networks"]) == {"newapi"}
assert config["networks"]["newapi"]["external"] is True
assert config["networks"]["newapi"]["name"] == "mira-cloud-infra_default"
env = svc["environment"]
assert env["API_SERVER_ENABLED"] == "false"
assert env["GATEWAY_ALLOW_ALL_USERS"] == "false"
assert env["HERMES_DASHBOARD"] == "0"
print("Hermes lab compose/security envelope: OK (static only)")
PY
