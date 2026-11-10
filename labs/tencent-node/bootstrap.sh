#!/usr/bin/env bash
# Tencent Mira Cloud node: Ubuntu host-only Docker + Caddy bootstrap.
# This script is deliberately not a service deployment or DC installer.
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none
export NEEDRESTART_MODE=l

die() { echo "MIRA_NODE_BOOTSTRAP_ERROR=$*" >&2; exit 1; }
test "$(id -u)" = 0 || die "ROOT_REQUIRED"
test "$( . /etc/os-release; echo "$ID:$VERSION_ID" )" = "ubuntu:26.04" || die "UNEXPECTED_OS"
operation="${1:-inspect}"
case "$operation" in inspect|install|repair) ;; *) die "UNKNOWN_OPERATION" ;; esac

echo "NODE_HOSTNAME=$(hostname)"
echo "NODE_DOCKER_PRESENT=$(command -v docker >/dev/null && echo yes || echo no)"
echo "NODE_CADDY_PRESENT=$(command -v caddy >/dev/null && echo yes || echo no)"
echo "NODE_DOCKER_COMPOSE_PRESENT=$(docker compose version >/dev/null 2>&1 && echo yes || echo no)"
echo "NODE_DISK_AVAILABLE_KIB=$(df -Pk / | awk 'NR==2 {print $4}')"
echo "NODE_MEM_AVAILABLE_KIB=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
if test "$operation" = inspect; then
  echo "NODE_READ_ONLY_INSPECTION=PASS"
  exit 0
fi

# Emergency correction for the Caddyfile's implicit wildcard listener.
# Match the exact v0 bootstrap Caddyfile before touching a running service.
if test "$operation" = repair; then
  test -f /etc/caddy/Caddyfile && test ! -L /etc/caddy/Caddyfile ||
    die "NO_EXPECTED_CADDY_CONFIG"
  command -v caddy >/dev/null || die "CADDY_NOT_INSTALLED"
  test -d /opt/mira-cloud-node/backups || die "BACKUP_DIRECTORY_MISSING"
  umask 077
  expected="$(mktemp)"
  replacement="$(mktemp /etc/caddy/.mira-caddy.XXXXXXXX)"
  trap 'rm -f "$expected" "$replacement"' EXIT
  cat > "$expected" <<'OLD_CADDY'
{
    admin off
    auto_https off
}

http://127.0.0.1:8090 {
    respond /healthz "ok" 200
    respond "Mira Cloud node ready (local-only)" 200
}
OLD_CADDY
  cmp -s /etc/caddy/Caddyfile "$expected" || die "CADDY_CONFIG_CHANGED_REVIEW_REQUIRED"
  cat > "$replacement" <<'FIXED_CADDY'
{
    admin off
    auto_https off
}

http://127.0.0.1:8090 {
    bind 127.0.0.1
    respond /healthz "ok" 200
    respond "Mira Cloud node ready (local-only)" 200
}
FIXED_CADDY
  caddy validate --config "$replacement" --adapter caddyfile >/dev/null ||
    die "CADDY_NEW_CONFIG_INVALID"
  backup="/opt/mira-cloud-node/backups/caddy-pre-bind-$(date -u +%Y%m%dT%H%M%SZ).Caddyfile"
  cp -p /etc/caddy/Caddyfile "$backup"
  chmod 600 "$backup"
  install -o root -g root -m 644 "$replacement" /etc/caddy/Caddyfile
  if ! systemctl restart caddy.service; then
    systemctl stop caddy.service || true
    die "CADDY_RESTART_FAILED_FAIL_CLOSED"
  fi
  if ! test "$(curl --noproxy '*' -fsS --max-time 6 http://127.0.0.1:8090/healthz)" = ok ||
     ! ss -lntH | awk '{print $4}' | grep -qx '127.0.0.1:8090' ||
     ss -lntH | awk '{print $4}' | grep -Eq '(^[*]:8090$|^0[.]0[.]0[.]0:8090$|^\[::\]:8090$)'; then
    systemctl stop caddy.service || true
    die "CADDY_LOCAL_BIND_VERIFICATION_FAILED_FAIL_CLOSED"
  fi
  echo "NODE_CADDY_BACKUP_CREATED=YES"
  echo "NODE_CADDY_LOCAL_BIND=PASS"
  echo "NODE_CADDY_PUBLIC_LISTENER=NO"
  echo "NODE_DC_RUNNER_MODIFIED=NO"
  exit 0
fi

# Never overwrite existing service configuration or a partially provisioned host.
if command -v docker >/dev/null || command -v caddy >/dev/null; then
  die "ALREADY_PROVISIONED_REVIEW_BEFORE_REAPPLY"
fi
test ! -e /etc/caddy/Caddyfile || die "EXISTING_CADDY_CONFIGURATION"
test ! -e /etc/apt/sources.list.d/caddy-stable.list || die "EXISTING_CADDY_APT_SOURCE"
test ! -e /usr/sbin/policy-rc.d || die "EXISTING_SERVICE_START_POLICY"
if ss -lntH | awk '{print $4}' | grep -Eq ':(80|443|2375|2376|8090)$'; then
  die "EXISTING_PUBLIC_OR_BASELINE_LISTENER"
fi

# Prevent either package from starting public default listeners during apt.
cat > /usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 755 /usr/sbin/policy-rc.d
cleanup_policy() { rm -f /usr/sbin/policy-rc.d; }
trap cleanup_policy EXIT

apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl gnupg docker.io docker-compose-v2
install -d -m 755 /usr/share/keyrings /etc/apt/sources.list.d
curl -fsSL --connect-timeout 8 --max-time 30 \
  https://dl.cloudsmith.io/public/caddy/stable/gpg.key |
  gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
chmod 644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL --connect-timeout 8 --max-time 30 \
  https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  -o /etc/apt/sources.list.d/caddy-stable.list
chmod 644 /etc/apt/sources.list.d/caddy-stable.list
apt-get update -qq
apt-get install -y --no-install-recommends caddy

# Caddy is local until DNS, TLS and public-service plans are approved.
# Never give miraops access to Docker's root-equivalent Unix socket.
install -d -m 755 /etc/caddy /opt/mira-cloud-node /opt/mira-cloud-node/stacks
install -d -m 700 /opt/mira-cloud-node/data /opt/mira-cloud-node/backups
cat > /etc/caddy/Caddyfile <<'CADDY'
{
    admin off
    auto_https off
}

http://127.0.0.1:8090 {
    bind 127.0.0.1
    respond /healthz "ok" 200
    respond "Mira Cloud node ready (local-only)" 200
}
CADDY
chown root:root /etc/caddy/Caddyfile
chmod 644 /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

cleanup_policy
trap - EXIT
systemctl enable --now docker.service
systemctl enable --now caddy.service
systemctl is-active --quiet docker.service || die "DOCKER_SERVICE_INACTIVE"
systemctl is-active --quiet caddy.service || die "CADDY_SERVICE_INACTIVE"
docker info --format 'NODE_DOCKER_SERVER={{.ServerVersion}}'
docker compose version
caddy version
test "$(curl --noproxy '*' -fsS --max-time 6 http://127.0.0.1:8090/healthz)" = ok ||
  die "CADDY_LOCAL_HEALTH_FAILED"
if ss -lntH | awk '{print $4}' | grep -Eq ':(80|443|2375|2376)$'; then
  die "UNEXPECTED_PUBLIC_LISTENER"
fi
ss -lntH | awk '{print $4}' | grep -qx '127.0.0.1:8090' ||
  die "CADDY_NOT_LOCAL_ONLY"
if ss -lntH | awk '{print $4}' | grep -Eq '(^[*]:8090$|^0[.]0[.]0[.]0:8090$|^\[::\]:8090$)'; then
  die "CADDY_WILDCARD_LISTENER_FORBIDDEN"
fi
echo "NODE_LOOPBACK_LISTENER_VERIFIED=YES"
test -r /etc/caddy/Caddyfile ||
  die "CADDY_CONFIG_MISSING"
# End loopback verification
if id -nG miraops 2>/dev/null | grep -qw docker; then
  die "MIRAOPS_MUST_NOT_HAVE_DOCKER_ACCESS"
fi
{
  echo "Provisioned UTC: $(date -u +%FT%TZ)"
  docker --version
  docker compose version
  caddy version
  echo "Caddy health: loopback-only http://127.0.0.1:8090/healthz"
  echo "Docker workloads: none"
} > /opt/mira-cloud-node/BASELINE.txt
chmod 644 /opt/mira-cloud-node/BASELINE.txt
echo "NODE_BOOTSTRAP_SUCCESS=YES"
echo "NODE_PUBLIC_HTTP_PORTS_OPENED=NO"
echo "NODE_DC_RUNNER_MODIFIED=NO"
