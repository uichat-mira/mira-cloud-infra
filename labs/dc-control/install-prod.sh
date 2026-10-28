#!/usr/bin/env bash
set -euo pipefail
# Install the fixed-action single-owner DC control API; NO public Caddy route.
RELEASE=/tmp/mira-dc-control-release/labs/dc-control
TARGET=/opt/mira-dc-control
ENV_FILE=/etc/mira-dc-control.env
UNIT=mira-dc-control.service
umask 077

[[ "$(id -u)" == 0 ]]
[[ -f "$RELEASE/server.py" && -f "$RELEASE/helper.py" ]]
[[ -f "$RELEASE/mira-dc-control.sudoers" ]]
[[ -x /opt/mira-dc-poc/v0.3.1/node ]]
[[ -r /opt/mira-dc-poc/v0.3.1/node_modules/@wonderwhy-er/desktop-commander/dist/index.js ]]
[[ -S /var/run/docker.sock ]]
command -v visudo >/dev/null
command -v systemd-run >/dev/null
command -v python3 >/dev/null
[[ "$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)" -gt 390000 ]]
curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:8788/ready >/dev/null
curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:3000/api/status >/dev/null

# No account identifier or credential is logged.
# An explicit administrator is required: other allowed Cloud Accounts remain valid
# for normal Cloud Auth features, but must not manage DC.
[[ -n "${MIRA_DC_CONTROL_OWNER_USERNAME:-}" ]] || {
  echo "DC_CONTROL_OWNER_USERNAME_NOT_CONFIGURED"
  exit 1
}
OWNER_ID="$(python3 - <<'PY'
import os, re, sqlite3, sys, unicodedata
user = unicodedata.normalize("NFKC", os.environ["MIRA_DC_CONTROL_OWNER_USERNAME"].strip()).lower()
if len(user) < 3 or len(user) > 64:
    sys.exit("DC_CONTROL_INVALID_OWNER_USERNAME")
con = sqlite3.connect("file:/opt/cloud-auth/data/auth.sqlite?mode=ro", uri=True, timeout=3)
try:
    rows = con.execute(
        "SELECT id FROM accounts WHERE username_normalized=? AND is_allowed=1 AND disabled_at IS NULL",
        (user,),
    ).fetchall()
finally:
    con.close()
if len(rows) != 1:
    sys.exit("DC_CONTROL_SPECIFIED_OWNER_NOT_FOUND_OR_NOT_ALLOWED")
value = rows[0][0]
if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{4,128}", value) is None:
    sys.exit("DC_CONTROL_INVALID_ACCOUNT_ID")
print(value)
PY
)"
[[ -n "$OWNER_ID" ]]
echo "DC_CONTROL_EXPLICIT_OWNER_SELECTED=YES"

if ! getent passwd mira-dc-control >/dev/null; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin mira-dc-control
fi
[[ "$(id -u mira-dc-control)" != 0 ]]
if id -nG mira-dc-control | tr ' ' '\n' | grep -qx docker; then
  echo "DC_CONTROL_HTTP_USER_MUST_NOT_BE_IN_DOCKER_GROUP"; exit 1
fi
getent passwd mira-dc-poc >/dev/null
id -nG mira-dc-poc | tr ' ' '\n' | grep -qx docker

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/opt/mira-dc-control-backups/$STAMP"
install -d -m 0700 -o root -g root "$BACKUP"
for f in server.py helper.py index.html styles.css app.js README.md; do
  [[ -f "$RELEASE/$f" ]]
  if [[ -f "$TARGET/$f" ]]; then cp -p "$TARGET/$f" "$BACKUP/$f"; fi
done
for spec in /etc/systemd/system/mira-dc-control.service /etc/sudoers.d/mira-dc-control "$ENV_FILE"; do
  if [[ -f "$spec" ]]; then cp -p "$spec" "$BACKUP/$(basename "$spec")"; fi
done
echo "DC_CONTROL_ROLLBACK_BACKUP_READY=YES"

install -d -m 0755 -o root -g root "$TARGET"
install -d -m 0700 -o root -g root /var/lib/mira-dc-control
for f in server.py helper.py index.html styles.css app.js README.md; do
  install -m 0644 -o root -g root "$RELEASE/$f" "$TARGET/$f"
done
python3 -m py_compile "$TARGET/server.py" "$TARGET/helper.py"
install -m 0440 -o root -g root "$RELEASE/mira-dc-control.sudoers" /etc/sudoers.d/mira-dc-control
visudo -cf /etc/sudoers.d/mira-dc-control >/dev/null

ENV_TMP="$(mktemp /etc/mira-dc-control.env.XXXXXX)"
printf 'MIRA_DC_OWNER_ACCOUNT_ID=%s\n' "$OWNER_ID" > "$ENV_TMP"
printf 'MIRA_DC_ALLOWED_ORIGIN=https://cloud-auth.tomzlab.cn\n' >> "$ENV_TMP"
chown root:root "$ENV_TMP"
chmod 0600 "$ENV_TMP"
mv -f "$ENV_TMP" "$ENV_FILE"
unset OWNER_ID
install -m 0644 -o root -g root "$RELEASE/mira-dc-control.service" /etc/systemd/system/mira-dc-control.service
systemctl daemon-reload
systemctl enable --now "$UNIT"
systemctl restart "$UNIT"
systemctl is-active --quiet "$UNIT"

STATIC=000
for attempt in $(seq 1 25); do
  STATIC="$(curl --noproxy '*' -s --max-time 3 -o /tmp/dc-control-index-check -w '%{http_code}' http://127.0.0.1:8792/dc/ || true)"
  if [[ "$STATIC" == 200 ]]; then break; fi
  if ! systemctl is-active --quiet "$UNIT"; then break; fi
  sleep 0.5
done
if [[ "$STATIC" != 200 ]]; then
  echo "DC_CONTROL_LOCAL_READY_FAILED_HTTP=$STATIC"
  systemctl status "$UNIT" --no-pager -n 15 || true
  journalctl -u "$UNIT" --no-pager -n 15 -o cat || true
  exit 1
fi
grep -q 'DC 控制台' /tmp/dc-control-index-check
rm -f /tmp/dc-control-index-check
STATUS="$(curl --noproxy '*' -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8792/dc/api/status)"
[[ "$STATUS" == 401 ]]
curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:8788/ready >/dev/null
curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:3000/api/status >/dev/null
echo "DC_CONTROL_LOOPBACK_UI_HTTP=$STATIC"
echo "DC_CONTROL_UNAUTHENTICATED_API_HTTP=$STATUS"
echo "DC_CONTROL_SERVICE_ACTIVE=YES"
echo "DC_CONTROL_ADJACENT_SERVICES_HEALTHY=YES"
echo "DC_REMOTE_DEVICE_NOT_AUTO_STARTED=YES"
