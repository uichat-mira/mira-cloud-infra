#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export HERMES_PUBLIC_ORIGIN=https://hermes.example.invalid
docker compose -f labs/hermes/compose.yaml -f labs/hermes/compose.web.yaml config --quiet
python3 - <<'PY'
import json, subprocess
cfg=json.loads(subprocess.check_output([
    'docker','compose','-f','labs/hermes/compose.yaml',
    '-f','labs/hermes/compose.web.yaml','config','--format','json'], text=True))
svc=cfg['services']['hermes']
ports=svc.get('ports', [])
assert len(ports)==1, ports
assert ports[0]['target']==9119
assert ports[0]['published']=='9119'
assert ports[0]['host_ip']=='127.0.0.1'
assert int(svc['mem_limit'])==1024**3
assert int(svc['memswap_limit'])==1536*1024**2
assert svc['restart']=='no'
assert not svc.get('privileged', False)
env=svc['environment']
assert env['HERMES_DASHBOARD']=='1'
assert env['HERMES_DASHBOARD_HOST']=='0.0.0.0'
assert env['HERMES_DASHBOARD_PUBLIC_URL']=='https://hermes.example.invalid'
assert env['API_SERVER_ENABLED']=='false'
assert env['GATEWAY_ALLOW_ALL_USERS']=='false'
assert env.get('HERMES_DASHBOARD_INSECURE') is None
print('Hermes OAuth web overlay: loopback-only, resource bounded, no auth bypass')
PY
