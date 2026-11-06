#!/usr/bin/env bash
# Retire only Moyu's legacy domestic Caddy vhost after the ESA cutover decision.
# This is invoked by the protected Infra production Action, never by a web request.
set -Eeuo pipefail
umask 022

cfg=/etc/caddy/Caddyfile
site_vhost=/etc/caddy/moyu-static-site.caddy
origin_line='import /etc/caddy/moyu-static-site.caddy'
retired_line='# retired for Moyu ESA cutover: import /etc/caddy/moyu-static-site.caddy'

[[ "$(id -u)" -eq 0 ]] || { echo 'MOYU_RETIRE_REQUIRES_ROOT' >&2; exit 1; }
test -f "$cfg"
test -f "$site_vhost"
grep -Fq '6260381.xyz {' "$site_vhost"
# These unrelated production ingress routes must remain in the source Caddyfile.
grep -Fxq 'mira-api.tomz.io, api.6260381.xyz {' "$cfg"
grep -Fxq 'import /etc/caddy/mira-cloud-auth.caddy' "$cfg"
grep -Fxq 'import /etc/caddy/tomzlab-web.caddy' "$cfg"
systemctl is-active --quiet caddy
caddy validate --config "$cfg" --adapter caddyfile >/dev/null

adapted="$(mktemp /tmp/moyu-retire-adapt.XXXXXXXX)"
verify_routes() {
  caddy adapt --config "$1" --adapter caddyfile > "$adapted" 2>/dev/null
  python3 - "$adapted" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text())
hosts = set()

def walk(value):
    if isinstance(value, dict):
        if isinstance(value.get("host"), list):
            hosts.update(item for item in value["host"] if isinstance(item, str))
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)

walk(config)
retired = {"6260381.xyz", "www.6260381.xyz"}
preserved = {"api.6260381.xyz", "mira-api.tomz.io", "tomzlab.cn"}
if retired & hosts:
    raise SystemExit("Retired Moyu host remains in adapted Caddy configuration")
if not preserved <= hosts:
    raise SystemExit("Unrelated ingress hosts missing: " + ", ".join(sorted(preserved - hosts)))
PY
}

if ! grep -Fxq "$origin_line" "$cfg"; then
  if grep -Fxq "$retired_line" "$cfg"; then
    verify_routes "$cfg"
    rm -f -- "$adapted"
    echo 'MOYU_ORIGIN_ALREADY_DISABLED=YES'
    echo 'UNRELATED_INGRESS_PRESERVED=YES'
    exit 0
  fi
  rm -f -- "$adapted"
  echo 'MOYU_IMPORT_NOT_IN_EXPECTED_STATE: refusing to edit' >&2
  exit 1
fi

# The original file and a timestamped root-owned backup survive the change.
backup="$(mktemp /etc/caddy/Caddyfile.before-moyu-esa.XXXXXXXX)"
cp -p -- "$cfg" "$backup"
stage="$(mktemp /etc/caddy/.Caddyfile.moyu-esa.XXXXXXXX)"
changed=no
committed=no
restore_on_failure() {
  rc=$?
  trap - EXIT
  if [[ "$changed" == yes && "$committed" != yes ]]; then
    echo 'MOYU_RETIRE_FAILED_RESTORING_CADDY' >&2
    cp -p -- "$backup" "$cfg" || rc=1
    if caddy validate --config "$cfg" --adapter caddyfile >/dev/null 2>&1; then
      systemctl reload caddy || rc=1
    else
      rc=1
    fi
  fi
  rm -f -- "$stage" "$adapted"
  exit "$rc"
}
trap restore_on_failure EXIT

python3 - "$cfg" "$stage" <<'PY'
import sys
from pathlib import Path

source, destination = map(Path, sys.argv[1:])
old = "import /etc/caddy/moyu-static-site.caddy"
new = "# retired for Moyu ESA cutover: " + old
lines = source.read_text().splitlines(keepends=True)
matches = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == old]
if len(matches) != 1:
    raise SystemExit(f"Expected exactly one Moyu import, found {len(matches)}")
i = matches[0]
lines[i] = lines[i].replace(old, new, 1)
destination.write_text("".join(lines))
PY

chown --reference="$cfg" "$stage"
chmod --reference="$cfg" "$stage"
caddy validate --config "$stage" --adapter caddyfile >/dev/null
verify_routes "$stage"
changed=yes
mv -f -- "$stage" "$cfg"
systemctl reload caddy
systemctl is-active --quiet caddy
caddy validate --config "$cfg" --adapter caddyfile >/dev/null
verify_routes "$cfg"
committed=yes

echo "MOYU_ORIGIN_DISABLED=YES"
echo "CADDY_ACTIVE=YES"
echo "UNRELATED_INGRESS_PRESERVED=YES"
echo "ROLLBACK_BACKUP=$(basename "$backup")"
