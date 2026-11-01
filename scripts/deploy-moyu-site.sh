#!/usr/bin/env bash
# Production-only static-site release, invoked via Infra's protected prod Action.
set -Eeuo pipefail
umask 022

SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid Moyu release SHA' >&2; exit 2; }
[[ "$(id -u)" -eq 0 ]] || { echo 'Infra production release requires the authorized root SSH operator' >&2; exit 1; }

SITE=6260381.xyz
BASE="/srv/www/$SITE"
RELEASE="$BASE/releases/$SHA"
CURRENT="$BASE/current"
ARCHIVE="/tmp/moyu-site-$SHA.tar.gz"
VHOST="/etc/caddy/moyu-static-site.caddy"
CADDY_MAIN=/etc/caddy/Caddyfile
IMPORT="import $VHOST"

test -s "$ARCHIVE"
test -f "$CADDY_MAIN"
test -f /etc/caddy/tomzlab-web.caddy
systemctl is-active --quiet caddy
caddy validate --config "$CADDY_MAIN" --adapter caddyfile >/dev/null 2>&1
[[ ! -L "$BASE" ]]
[[ ! -e "$CURRENT" || -L "$CURRENT" ]]
# The static site must own its separate directory. Existing unrelated content
# is not a migration candidate: fail rather than adopt it.
if [[ -d "$BASE" && ! -f "$BASE/.moyu-site-root" ]]; then
  echo 'Unexpected pre-existing Moyu directory without ownership marker' >&2; exit 1
fi
if [[ -e "$VHOST" ]] && ! grep -Fq '# Managed by Infra Moyu release workflow' "$VHOST"; then
  echo 'Refusing to replace an unowned Caddy vhost' >&2; exit 1
fi

# Resolve the private Caddy listening interface from the working website,
# not a server address baked into this public repository.
BIND_IP=$(awk '/^[[:space:]]*bind[[:space:]]/ {print $2; exit}' /etc/caddy/tomzlab-web.caddy)
[[ "$BIND_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'Unable to resolve existing Caddy interface' >&2; exit 1;
}

# Reject tar path traversal, hard/symbolic links and special files.
python3 - "$ARCHIVE" <<'PY'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1], "r:gz") as ar:
    names = set()
    for item in ar:
        p = PurePosixPath(item.name)
        if p.is_absolute() or ".." in p.parts or not (item.isdir() or item.isfile()):
            raise SystemExit("Unsafe member in Moyu static archive")
        names.add(str(p).lstrip("./"))
    for must in ("index.html", "404.html", "blogs/index.html",
                 "projects/index.html", "sitemap.xml"):
        if must not in names:
            raise SystemExit("Missing static output: " + must)
PY

mkdir -p "$BASE/releases" "$BASE/backups"
touch "$BASE/.moyu-site-root"
STAGE=$(mktemp -d "$BASE/releases/.stage-XXXXXXXX")
NEXT="$BASE/.next-$SHA-$$"
MAIN_BACKUP=$(mktemp /tmp/moyu-caddy-main.XXXXXXXX)
cp -p "$CADDY_MAIN" "$MAIN_BACKUP"
HAD_VHOST=no
if [[ -e "$VHOST" ]]; then
  HAD_VHOST=yes
  VHOST_BACKUP=$(mktemp /tmp/moyu-vhost.XXXXXXXX)
  cp -p "$VHOST" "$VHOST_BACKUP"
else
  VHOST_BACKUP=''
fi
PREVIOUS=''
if [[ -L "$CURRENT" ]]; then
  PREVIOUS=$(readlink "$CURRENT")
fi
SWITCHED=no
CONFIG_CHANGED=no
DONE=no
cleanup() {
  rc=$?
  trap - EXIT
  if [[ "$DONE" != yes ]]; then
    echo "MOYU_RELEASE_FAILED_ROLLBACK_START" >&2
    if [[ "$SWITCHED" == yes ]]; then
      if [[ -n "$PREVIOUS" ]]; then
        ln -s -- "$PREVIOUS" "$NEXT"
        mv -Tf -- "$NEXT" "$CURRENT" || rc=1
      else
        rm -f -- "$CURRENT"
      fi
    fi
    if [[ "$CONFIG_CHANGED" == yes ]]; then
      cp -p "$MAIN_BACKUP" "$CADDY_MAIN" || rc=1
      if [[ "$HAD_VHOST" == yes ]]; then
        cp -p "$VHOST_BACKUP" "$VHOST" || rc=1
      else
        rm -f -- "$VHOST"
      fi
      caddy validate --config "$CADDY_MAIN" --adapter caddyfile >/dev/null 2>&1 &&
        systemctl reload caddy || rc=1
    fi
  fi
  rm -f -- "$NEXT" "$MAIN_BACKUP"
  [[ -z "$VHOST_BACKUP" ]] || rm -f -- "$VHOST_BACKUP"
  [[ -d "$STAGE" ]] && rm -rf -- "$STAGE"
  exit "$rc"
}
trap cleanup EXIT

tar -xzf "$ARCHIVE" -C "$STAGE" --no-same-owner --no-same-permissions
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f -exec chmod 644 {} +
test -s "$STAGE/index.html"

if [[ -e "$RELEASE" ]]; then
  # Idempotent retry of an already uploaded SHA. Never overwrite its files.
  test -s "$RELEASE/index.html"
else
  mv -T -- "$STAGE" "$RELEASE"
fi

# Append only this site's separately managed vhost. Never replace tomzlab
# or any other Caddy block, and never disable the current running service.
cat > "$VHOST" <<EOF
# Managed by Infra Moyu release workflow
$SITE {
    bind $BIND_IP
    root * $CURRENT
    encode zstd gzip
    handle_errors {
        @missing expression {err.status_code} == 404
        rewrite @missing /404.html
        file_server
    }
    file_server
}
www.$SITE {
    bind $BIND_IP
    redir https://$SITE{uri} 308
}
EOF
CONFIG_CHANGED=yes
if ! grep -Fxq "$IMPORT" "$CADDY_MAIN"; then
  printf '\n%s\n' "$IMPORT" >> "$CADDY_MAIN"
fi
caddy validate --config "$CADDY_MAIN" --adapter caddyfile >/dev/null

ln -s -- "$RELEASE" "$NEXT"
mv -Tf -- "$NEXT" "$CURRENT"
SWITCHED=yes
systemctl reload caddy

# Real HTTPS TLS vhost probe. DNS caches can lag behind authoritative DNS:
# the explicit resolve checks the intended origin, with certificate validation.
for attempt in $(seq 1 12); do
  if curl -fsSL --connect-timeout 5 --max-time 15 \
    --resolve "$SITE:443:$BIND_IP" "https://$SITE/?release=$SHA" |
    grep -Fq '摸鱼划水记录'; then
    break
  fi
  if [[ "$attempt" -eq 12 ]]; then echo 'MOYU_ORIGIN_HTTPS_SMOKE_FAILED' >&2; exit 1; fi
  sleep 5
done
for page in /blogs/ /projects/ /docs/about/ /blogs/ai-agent-ux-rant/; do
  curl -fsSL --connect-timeout 5 --max-time 20 \
    --resolve "$SITE:443:$BIND_IP" "https://$SITE$page" >/dev/null
done
printf '%s\n' "$SHA" > "$BASE/.deployed-sha"
DONE=yes
rm -f -- "$ARCHIVE"
echo "MOYU_ORIGIN_HTTPS_SMOKE=PASS"
echo "MOYU_RELEASE_SUCCESS_SHA=$SHA"
