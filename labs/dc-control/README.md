# DC Control Console · V1

A minimal responsive operator console for the **existing Aliyun Guangzhou DC** with an optional, explicitly pinned **Tencent DC** node (OPS-027). It is not a replacement agent, Docker manager, or new account system.

## What V1 does
- Read the current systemd DC state, memory usage and remaining time.
- Start a fixed DC service with bounded runtime, memory limit and CPU quota; stop this or either of the prior one-time DC trial services.
- Save a validated policy for the next launch. Defaults: 30 minutes / 384 MiB / 50% of one CPU / require 512 MiB available.
- Reuse Mira Cloud Account session on the SAME browser origin/tab, requiring an explicit configured owner account ID; no second password system.
- Use one responsive page for desktop and mobile browsers, without offering arbitrary Shell or Docker calls from the page.

Intentionally NOT implemented: boot auto-start, unbounded mode, autonomous restart, cron windows, editing arbitrary unit names, control of unrelated containers, notifications. The page marks these capabilities unavailable.

## Integration boundary

The original single-node controller is already deployed on the existing Aliyun host. New multi-node changes remain source candidates until explicitly reviewed, promoted and deployed. The established Cloud Auth HTTPS origin remains:

    https://cloud-auth.tomzlab.cn/dc/ -> Caddy /dc/* -> 127.0.0.1:8792

This handler must take precedence over the existing Cloud Auth SPA fallback, must forward Authorization and Origin, must not publish port 8792, and must not change existing Cloud Auth routes, Caddy bindings or other domains. The Cloud Auth frontend currently keeps its Cloud Session in sessionStorage with the key mira.cloud-auth.session.v1; this is shared with the control page ONLY in the same origin and browser tab.

The process refuses to start without MIRA_DC_OWNER_ACCOUNT_ID set to a real administrator account ID in a protected server-side environment. Never include this value or any bearer token in GitHub/public source. Every API call forwards the presented Cloud Session bearer to loopback Cloud Auth GET /v1/auth/session, then compares the authenticated account ID to the owner allowlist. Mutations additionally demand the exact MIRA_DC_ALLOWED_ORIGIN, default https://cloud-auth.tomzlab.cn. No CORS wildcard, no browser-stored administrator key.

## API contract

GET /dc/api/status — current systemd state and persisted policy.
POST /dc/api/start — body {}, starts DC with preset policy.
POST /dc/api/stop — body {}, stops fixed DC session/trial unit.
PUT /dc/api/policy — validated preset selections only.

On Aliyun, only mira-dc-control-session, mira-dc-docker-verify and mira-dc-pairing-poc service units are ever controlled. Launch uses fixed pinned paths, the existing mira-dc-poc account, and its intentionally granted docker group. HTTP requests cannot select a unit or arbitrary executable. systemd RuntimeMaxSec is the authoritative time limit; UI countdown is informational.

## Security and deployment notes
- Loopback only. Never expose port 8792 directly or add an unprotected public route.
- Auth and owner allowlist are mandatory. A valid session belonging to another Cloud Account must be denied.
- The HTTP listener runs as a dedicated unprivileged mira-dc-control account, without Docker group membership. Its authenticated fixed-action requests pass through a root-owned Python helper via a narrowly-scoped sudoers rule. The helper validates SUDO_UID and accepts only status/start/stop/policy. Service code and sudoers must be root-owned and non-writable by the HTTP account. Deployment still requires explicit review, backup, and rollback.
- Docker group access is effectively root access. Restrictions on the DC process do not limit what it can cause the external Docker daemon to do.
- Boot auto-start is disabled and DC has a finite runtime by default.
- Reject attempts to start if available RAM falls below the chosen threshold; do not reconfigure other Docker services.
- No sensitive headers or login material should appear in logs or API responses.
- Do not install or publish this app during the source-only phase. After review, a separate guarded deployment must install the systemd unit and coordinate Caddy routing with cloud-auth.
- Existing trial sessions may be stopped, but do not display a fabricated remaining-time countdown for them.
- systemd active means running process, not guaranteed Remote MCP cloud connectivity.

## Verification

    python3 -m unittest discover -s labs/dc-control -p 'test_*.py' -v
    python3 -m py_compile labs/dc-control/server.py
    node --check labs/dc-control/app.js

After an authorized deployment, separately verify successful owner login, rejected other owner, cross-origin POST refusal, DC start/stop and adjacent New API/Cloud Auth health.

## OPS-027 · Tencent as an opt-in bounded node

**Architecture:** The existing Cloud Auth HTTPS origin authenticates the owner
Cloud Session and forwards `/dc/api/*` to the Aliyun controller's loopback listener.
The Aliyun controller preserves its original local endpoints. New literal
`/dc/api/nodes/tencent/{status,start,stop,policy}` endpoints permit exactly one
additional node. The frontend selects between these two fixed endpoints, and
never sends a target host, user, systemd unit or shell command.

For Tencent, the Aliyun root-owned fixed-action helper uses the root-only
`/etc/mira-dc-remote` SSH identity and a **pre-verified, pinned SSH host key**
to connect as `miraops`. Tencent's `authorized_keys` entry has a **forced
Python command**, a single controller source IP allowlist, and SSH `restrict`.
The root-owned `remote_agent.py` binary accepts only JSON
`status/start/stop/policy`. It executes `systemd-run --user`, never systemd as
root, never Docker, and never an arbitrary command. No new network port is
opened on Tencent.

**Tencent policy:** A normal login systemd user-manager can remain available
using `loginctl enable-linger miraops`, but the actual DC transient unit
`mira-dc-session.service` is neither enabled at boot nor allowed to restart:
`Restart=no`, `RuntimeMaxSec` is mandatory. Default 30 minutes / 384MiB /
50% of one CPU / require 512MiB available. The original 15/30/60/120/240
minute presets remain. An existing manually run `npx ... remote` process is
treated as legacy, is **never killed by the controller**, and blocks starting
another instance; close that original terminal explicitly before accepting
new starts. DC process active does not prove the remote cloud session is online.

### Provisioning gates (reviewed manual root path only)

Do **not** run these scripts from an unchecked local download or a feature
branch directly on production. Stage the reviewed release candidate at
`/tmp/mira-dc-control-release/labs/dc-control` and verify its commit SHA.
Do not automate `prod` promotion solely from a green CI check.

1. On **Tencent root console**, confirm `miraops` already owns a DC pairing
   (`~miraops/.desktop-commander-device/device.json`) and has neither sudo
   nor Docker-group privileges. Record the Ed25519 SSH **host public-key**
   fingerprint from the local console. On **Aliyun**, compare that fingerprint
   with the candidate host key independently; **do not simply accept
   `ssh-keyscan` as trusted**.
2. On **Aliyun root**, stage a root-owned file containing the verified exact
   OpenSSH host-key line for the new server, with its actual IPv4 address
   (not committed). Set `MIRA_DC_TENCENT_IPV4` and
   `MIRA_DC_VERIFIED_HOSTKEY_FILE`; run reviewed
   `python3 install_aliyun_target.py`. It generates/reuses a root-only
   SSH key at `/etc/mira-dc-remote/id_ed25519`, with no passwordless
   system-wide root login or auto-trust. **Only its public key** may be
   transferred to the Tencent console.
3. On **Tencent root console**, stage that public key in a local file; set
   `MIRA_DC_CONTROLLER_PUBKEY_FILE` and
   `MIRA_DC_CONTROLLER_IP` (the verified *egress* IPv4 of the Aliyun
   controller, not necessarily its private NIC address). Run the reviewed
   `python3 install_tencent_node.py`. It installs the pinned 0.3.1 DC
   package with npm lifecycle scripts disabled, the root-owned forced
   command, and the unprivileged user-manager prerequisites. It does **not**
   start DC or stop the existing npx session.
4. From **Aliyun root**, use the configured SSH key/known_hosts to send only
   the JSON `{"action":"status","payload":{}}` via stdin. Expect structured
   bounded status, not a shell. Verify an unknown SSH command is rejected.
   Only after this succeeds may the Aliyun controller's reviewed candidate
   and the same-origin Cloud Auth UI be promoted under the normal environment
   rules.
5. In a **real authorized Cloud Account browser session**, verify each
   node's status, the negative owner/Origin cases, Tencent 15-minute (or
   approved 30-minute) start, systemd unit properties, strict expiry,
   and Aliyun independent status. Check Cloud Auth `/ready`, New API
   `/api/status`, and public TLS response body before/after promotion.

The remote transport returns a clear 503 if target configuration, SSH pinning,
user-manager, or remote connectivity is missing. It does not silently fall
back to the local Aliyun unit. Production secrets, target IPs, key fingerprints,
Cloud Session material and pairing files must remain outside Git.

### Verification and rollback

Run offline checks:
```bash
python3 -m unittest discover -s labs/dc-control -p 'test_*.py' -v
python3 -m py_compile labs/dc-control/server.py labs/dc-control/helper.py labs/dc-control/remote_node.py labs/dc-control/remote_agent.py
node --check labs/dc-control/app.js
bash scripts/check.sh
```

Before production setup, back up the existing Aliyun controller, Caddy routing
and root-only state and record the exact deployed SHA. On failure, remove only
the newly introduced Tencent fixed-route handling and restore the prior
controller build; the original local DC actions remain unchanged. On Tencent,
the managed `authorized_keys` line marked `mira-dc-ops027` can be revoked
by the root operator without touching other SSH keys. Do not delete the paired
DC device, existing home directory or unrelated `systemd` units. Disabling
linger is separate and must not interrupt other user services.
