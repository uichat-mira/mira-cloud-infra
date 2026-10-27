#!/usr/bin/env bash
# One-time password-gated Hermes HTTPS deployment. All secrets stay on the host.
set -Eeuo pipefail
umask 077
cd /opt/hermes-lab
ready=no
backup_dir=""
rollback() {
  rc=$?
  trap - EXIT
  if [ "$ready" != yes ] && [ -n "$backup_dir" ]; then
    echo 'HERMES_TRIAL_ROLLBACK_STARTED'
    if test -f "$backup_dir/Caddyfile"; then
      cp -p "$backup_dir/Caddyfile" /etc/caddy/Caddyfile
      rm -f /etc/caddy/mira-hermes.caddy
      caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null && systemctl reload caddy || true
    fi
    docker compose -f compose.yaml -f compose.web.yaml down >/dev/null 2>&1 || true
    cp -p "$backup_dir/hermes.env" data/.env
    if test -f "$backup_dir/compose.env"; then cp -p "$backup_dir/compose.env" .env; else rm -f .env; fi
    docker compose -f compose.yaml up -d --no-deps --pull never >/dev/null 2>&1 || true
    rm -f private/initial-login.txt
    echo 'HERMES_TRIAL_ROLLED_BACK'
  fi
  exit "$rc"
}
trap rollback EXIT
test "$(id -u)" -eq 0
test -s compose.yaml && test -s data/.env && test -s data/config.yaml
test -s incoming/labs/hermes/compose.web.yaml
test "$(systemctl is-active caddy)" = active
test "$(docker inspect -f '{{.State.Running}}' mira-hermes-lab)" = true
test ! -e /etc/caddy/mira-hermes.caddy
! grep -Fq 'mira-hermes.caddy' /etc/caddy/Caddyfile
test "$(awk 'NR>1 {s+=$3} END{print s+0}' /proc/swaps)" -ge 2000000
test "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)" -gt 500000
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:3000/api/status >/dev/null
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8788/ready >/dev/null
domain="$(python3 - <<'PY'
from pathlib import Path
import re
matches=re.findall(r'(?m)^\s*mira-ai\.([a-z0-9.-]+)\s*\{',Path('/etc/caddy/Caddyfile').read_text())
assert len(set(matches))==1
print('hermes.'+matches[0])
PY
)"
python3 - "$domain" "$DEPLOY_HOST_IP" <<'PY'
import socket,sys,ipaddress
host,expected=sys.argv[1:]
assert ipaddress.ip_address(expected).is_global
assert expected in {i[4][0] for i in socket.getaddrinfo(host,443,family=socket.AF_INET)}
print('HERMES_DNS_MATCHES_DEPLOY_HOST')
PY
addr="$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++)if($i=="src"){print $(i+1);exit}}')"
python3 - "$addr" <<'PY'
import ipaddress,sys
assert ipaddress.ip_address(sys.argv[1]).is_private
PY
mkdir -p private
chmod 700 private
test ! -e private/initial-login.txt
backup_dir="$(mktemp -d /opt/hermes-lab/private/hermes-trial-backup.XXXXXXXX)"
cp -p data/.env "$backup_dir/hermes.env"
if test -f .env; then cp -p .env "$backup_dir/compose.env"; fi
install -m 0600 incoming/labs/hermes/compose.web.yaml compose.web.yaml
p1="$(openssl rand -hex 24)"
p2="$(openssl rand -hex 24)"
p3="$(openssl rand -hex 24)"
h1="$(caddy hash-password --plaintext "$p1")"
h2="$(caddy hash-password --plaintext "$p2")"
h3="$(HERMES_TEMP_PW="$p3" python3 - <<'PY'
import os,secrets,hashlib,base64
salt=secrets.token_bytes(16)
key=hashlib.scrypt(os.environ['HERMES_TEMP_PW'].encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
print('scrypt$16384$8$1$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(key).decode())
PY
)"
secret="$(openssl rand -hex 32)"
{
printf 'URL=https://%s\n' "$domain"
printf 'CADDY_USER_1=tomz\nCADDY_PASSWORD_1=%s\n' "$p1"
printf 'CADDY_USER_2=laohuizhang\nCADDY_PASSWORD_2=%s\n' "$p2"
printf 'HERMES_USER=admin\nHERMES_PASSWORD=%s\n' "$p3"
printf 'SHARED_WORKSPACE=YES\n'
} > private/initial-login.txt
chmod 600 private/initial-login.txt
unset p1 p2 p3
{
printf '\nHERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin\n'
printf 'HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH=%s\n' "$h3"
printf 'HERMES_DASHBOARD_BASIC_AUTH_SECRET=%s\n' "$secret"
printf 'HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS=3600\n'
} >> data/.env
chmod 600 data/.env
printf 'HERMES_PUBLIC_ORIGIN=https://%s\n' "$domain" > .env
chmod 600 .env
docker compose -f compose.yaml -f compose.web.yaml config --quiet
docker compose -f compose.yaml -f compose.web.yaml config --format json | python3 -c '
import json,sys
s=json.load(sys.stdin)["services"]["hermes"]
p=s["ports"]
assert len(p)==1 and p[0]["host_ip"]=="127.0.0.1" and p[0]["published"]=="9119"
assert s["mem_limit"]==1073741824 and s["memswap_limit"]==1610612736
assert s["environment"]["HERMES_DASHBOARD_HOST"]=="0.0.0.0"
assert s["environment"]["GATEWAY_ALLOW_ALL_USERS"]=="false"
'
docker compose -f compose.yaml -f compose.web.yaml up -d --no-deps --pull never
good=no
for i in $(seq 1 30); do
  if curl --noproxy '*' -sS --max-time 3 http://127.0.0.1:9119/api/status 2>/dev/null | python3 -c '
import sys,json
try:
 a=json.load(sys.stdin); assert a.get("auth_required") is True; assert "basic" in a.get("auth_providers",[])
except Exception: sys.exit(1)
' >/dev/null 2>&1; then good=yes; break; fi
  sleep 2
done
test "$good" = yes || { echo 'HERMES_BASIC_PROVIDER_MISSING'; exit 1; }
code="$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9119/api/auth/me)"
test "$code" = 401 || { echo 'HERMES_AUTH_BYPASS_DETECTED'; exit 1; }
test "$(docker inspect -f '{{.State.OOMKilled}}' mira-hermes-lab)" = false
test "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)" -gt 256000
echo 'HERMES_INNER_PASSWORD_GATE_VERIFIED'

install -d -o caddy -g caddy -m 0750 /var/log/caddy
mkdir -p /opt/mira-cloud-infra/backups
cp -p /etc/caddy/Caddyfile "$backup_dir/Caddyfile"
cat > /etc/caddy/mira-hermes.caddy <<EOF
$domain {
    bind $addr
    log {
        output file /var/log/caddy/hermes-access.json {
            roll_size 5MiB
            roll_keep 5
        }
        format json
    }
    basic_auth {
        tomz $h1
        laohuizhang $h2
    }
    reverse_proxy 127.0.0.1:9119 {
        header_up -Authorization
    }
}
EOF
chmod 644 /etc/caddy/mira-hermes.caddy
printf '\n# Hermes password-gated trial, independent of Cloud Auth.\nimport /etc/caddy/mira-hermes.caddy\n' >> /etc/caddy/Caddyfile
caddy fmt --overwrite /etc/caddy/mira-hermes.caddy
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy
test "$(systemctl is-active caddy)" = active
code="$(curl --noproxy '*' -ksS --max-time 8 -o /dev/null -w '%{http_code}' --resolve "$domain:443:$addr" "https://$domain/")"
test "$code" = 401 || { echo 'CADDY_ANONYMOUS_REQUEST_NOT_BLOCKED'; exit 1; }
p1="$(sed -n 's/^CADDY_PASSWORD_1=//p' private/initial-login.txt)"
code="$(curl --noproxy '*' -ksS --max-time 10 -o /dev/null -w '%{http_code}' -u "tomz:$p1" --resolve "$domain:443:$addr" "https://$domain/api/status")"
unset p1
test "$code" = 200 || { echo 'CADDY_VALID_PASSWORD_REJECTED'; exit 1; }
code="$(curl --noproxy '*' -ksS --max-time 8 -o /dev/null -w '%{http_code}' -u 'tomz:wrong' --resolve "$domain:443:$addr" "https://$domain/")"
test "$code" = 401 || { echo 'CADDY_BAD_PASSWORD_ACCEPTED'; exit 1; }
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:3000/api/status >/dev/null
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8788/ready >/dev/null
# Ensure server-side HTTPS validates with a real trusted certificate.
tls_ok=no
for i in $(seq 1 10); do
  if curl --noproxy '*' -sS --connect-timeout 3 --max-time 9 -o /dev/null --resolve "$domain:443:$addr" "https://$domain/" 2>/dev/null; then tls_ok=yes; break; fi
  sleep 4
done
test "$tls_ok" = yes || { echo 'HERMES_HTTPS_TRUST_CHECK_FAILED'; exit 1; }
test "$(docker inspect -f '{{.State.Running}}' mira-hermes-lab)" = true
test "$(docker inspect -f '{{.State.OOMKilled}}' mira-hermes-lab)" = false
echo 'HERMES_TRIAL_TWO_PASSWORD_GATES_AND_TLS_VERIFIED'
echo 'HERMES_CREDENTIALS_LOCATION=/opt/hermes-lab/private/initial-login.txt'
ready=yes
trap - EXIT
