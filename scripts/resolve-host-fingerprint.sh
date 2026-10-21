#!/usr/bin/env bash
set -euo pipefail

# Appleboy's Go SSH client may negotiate ECDSA, while our trusted known_hosts
# entry pins ED25519. Retrieve ECDSA's fingerprint over a separately verified
# ED25519/password SSH session; never accept an unverified ssh-keyscan result.
for key in HOST SSH_LOGIN SSH_PASSWORD PINNED_HOSTS; do
  [[ -n "${!key:-}" ]] || { echo "Missing SSH credential/config: $key" >&2; exit 1; }
done
[[ "${SSH_PORT:-22}" =~ ^[0-9]+$ ]] || { echo "Invalid SSH port" >&2; exit 1; }
command -v sshpass >/dev/null 2>&1 || {
  sudo apt-get update -qq
  sudo apt-get install -y -qq sshpass
}
umask 077
known_hosts="$RUNNER_TEMP/mira-known-hosts"
printf '%s\n' "$PINNED_HOSTS" > "$known_hosts"
ssh-keygen -F "$HOST" -f "$known_hosts" | grep -F 'ssh-ed25519 ' >/dev/null || {
  echo "Pinned ED25519 host key is missing" >&2; exit 1;
}
output="$(SSHPASS="$SSH_PASSWORD" sshpass -e ssh -T -F /dev/null \
  -p "${SSH_PORT:-22}" \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$known_hosts" \
  -o HostKeyAlgorithms=ssh-ed25519 \
  -o PreferredAuthentications=password,keyboard-interactive \
  -o PubkeyAuthentication=no \
  -o NumberOfPasswordPrompts=1 \
  -o ConnectTimeout=12 \
  -o ConnectionAttempts=1 \
  "${SSH_LOGIN}@${HOST}" \
  'ssh-keygen -lf /etc/ssh/ssh_host_ecdsa_key.pub -E sha256')"
fingerprint="$(printf '%s\n' "$output" | awk '/\(ECDSA\)/ { print $2; exit }')"
[[ "$fingerprint" == SHA256:* ]] || {
  echo "Could not verify the server ECDSA fingerprint" >&2; exit 1;
}
printf 'fingerprint=%s\n' "$fingerprint" >> "$GITHUB_OUTPUT"
echo "SSH login and ED25519-pinned host verification succeeded; ECDSA fingerprint attested"
