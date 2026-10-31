#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

SITE_SHA="${1:-}"
[[ "$SITE_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid pinned site commit' >&2; exit 2; }

BASE=/srv/www/tomzlab.cn
CURRENT="$BASE/current"
ARCHIVE="/tmp/tomzlab-site-${SITE_SHA}.tar.gz"
RELEASE="$BASE/releases/$SITE_SHA"
BACKUPS="$BASE/backups"

[[ $(id -u) -eq 0 ]] || { echo 'Deployment requires the authorized root operator' >&2; exit 1; }
[[ -f /etc/caddy/Caddyfile ]] && command -v caddy >/dev/null
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1
systemctl is-active --quiet caddy
# Identify the existing site; never create or replace Caddy configuration.
grep -RFlq --include='Caddyfile' --include='*.caddy' -- 'tomzlab.cn' /etc/caddy
grep -RFlq --include='Caddyfile' --include='*.caddy' -- "$CURRENT" /etc/caddy
[[ -d "$BASE" && ! -L "$BASE" && -L "$CURRENT" && -f "$CURRENT/index.html" ]]
[[ -f "$ARCHIVE" && ! -e "$RELEASE" ]]
tar -tzf "$ARCHIVE" >/dev/null

mkdir -p "$BASE/releases" "$BACKUPS"
STAGE=$(mktemp -d "$BASE/releases/.tomzlab-stage-XXXXXXXX")
NEXT="$BASE/.tomzlab-next-${SITE_SHA}-$$"
BACKUP="$BACKUPS/current-before-${SITE_SHA}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
SWITCHED=no
HOME_FILE=''
WEEK_FILE=''
cleanup() {
  rc=$?
  trap - EXIT
  [[ -z "$HOME_FILE" ]] || rm -f -- "$HOME_FILE"
  [[ -z "$WEEK_FILE" ]] || rm -f -- "$WEEK_FILE"
  if [[ "$SWITCHED" == yes ]]; then
    echo 'TOMZLAB_SMOKE_FAILED_ROLLING_BACK'
    if mv -Tf -- "$BACKUP" "$CURRENT"; then
      echo 'TOMZLAB_ROLLBACK_RESTORED'
    else
      echo 'TOMZLAB_ROLLBACK_REQUIRES_OPERATOR' >&2
      rc=1
    fi
  fi
  [[ -L "$NEXT" ]] && rm -f -- "$NEXT"
  [[ -d "$STAGE" ]] && rm -rf -- "$STAGE"
  exit "$rc"
}
trap cleanup EXIT

tar -xzf "$ARCHIVE" -C "$STAGE" --no-same-owner --no-same-permissions
for file in index.html notes.html weekly.html projects.html about.html 404.html robots.txt sitemap.xml assets/css/site.css assets/js/nav.js assets/js/feed-sync.js assets/icons/logo.svg assets/og.png; do
  [[ -f "$STAGE/$file" ]] || { echo "Missing release asset: $file" >&2; exit 1; }
done
[[ -z $(find "$STAGE" -type l -print -quit) ]] || { echo 'Unexpected symlink in release' >&2; exit 1; }
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f -exec chmod 644 {} +
mv -T -- "$STAGE" "$RELEASE"
# Preserve the original symlink, not the previous release directory.
cp -P -- "$CURRENT" "$BACKUP"
ln -s -- "$RELEASE" "$NEXT"
mv -Tf -- "$NEXT" "$CURRENT"
SWITCHED=yes

# Production T5: public hostname, DNS, TLS and Caddy, not local file existence.
HOME_FILE=$(mktemp)
WEEK_FILE=$(mktemp)
curl -fsSL --connect-timeout 5 --max-time 20 "https://tomzlab.cn/?released=$SITE_SHA" -o "$HOME_FILE"
curl -fsSL --connect-timeout 5 --max-time 20 "https://tomzlab.cn/weekly.html?released=$SITE_SHA" -o "$WEEK_FILE"
grep -Fq 'tomzlab' "$HOME_FILE"
grep -Fq '见π 周刊' "$WEEK_FILE"
grep -Fq '粤ICP备2026168682号' "$WEEK_FILE"
for resource in /assets/js/feed-sync.js /assets/js/nav.js /assets/icons/logo.svg /assets/og.png; do
  curl -fsSL --connect-timeout 5 --max-time 15 "https://tomzlab.cn$resource?released=$SITE_SHA" -o /dev/null
done

printf '%s\n' "$SITE_SHA" > "$BASE/.deployed-sha"
SWITCHED=no
rm -f -- "$ARCHIVE"
echo "TOMZLAB_RELEASE_SUCCESS_SHA=$SITE_SHA"
echo 'TOMZLAB_PUBLIC_HTTP_T5=PASS'
echo 'TOMZLAB_ROLLBACK_ANCHOR_SAVED=yes'
