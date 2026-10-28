# DC Control Console · V1

A minimal responsive operator console for the **existing Guangzhou DC device**, not a replacement agent, Docker manager, or new account system.

## What V1 does
- Read the current systemd DC state, memory usage and remaining time.
- Start a fixed DC service with bounded runtime, memory limit and CPU quota; stop this or either of the prior one-time DC trial services.
- Save a validated policy for the next launch. Defaults: 30 minutes / 384 MiB / 50% of one CPU / require 512 MiB available.
- Reuse Mira Cloud Account session on the SAME browser origin/tab, requiring an explicit configured owner account ID; no second password system.
- Use one responsive page for desktop and mobile browsers, without offering arbitrary Shell or Docker calls from the page.

Intentionally NOT implemented: boot auto-start, unbounded mode, autonomous restart, cron windows, editing arbitrary unit names, control of unrelated containers, notifications. The page marks these capabilities unavailable.

## Integration boundary

Source and tested candidate only — **not yet a public endpoint**. A separate audited release must install the server and add routing from the existing Cloud Auth HTTPS origin:

    https://cloud-auth.tomzlab.cn/dc/ -> Caddy /dc/* -> 127.0.0.1:8792

This handler must take precedence over the existing Cloud Auth SPA fallback, must forward Authorization and Origin, must not publish port 8792, and must not change existing Cloud Auth routes, Caddy bindings or other domains. The Cloud Auth frontend currently keeps its Cloud Session in sessionStorage with the key mira.cloud-auth.session.v1; this is shared with the control page ONLY in the same origin and browser tab.

The process refuses to start without MIRA_DC_OWNER_ACCOUNT_ID set to a real administrator account ID in a protected server-side environment. Never include this value or any bearer token in GitHub/public source. Every API call forwards the presented Cloud Session bearer to loopback Cloud Auth GET /v1/auth/session, then compares the authenticated account ID to the owner allowlist. Mutations additionally demand the exact MIRA_DC_ALLOWED_ORIGIN, default https://cloud-auth.tomzlab.cn. No CORS wildcard, no browser-stored administrator key.

## API contract

GET /dc/api/status — current systemd state and persisted policy.
POST /dc/api/start — body {}, starts DC with preset policy.
POST /dc/api/stop — body {}, stops fixed DC session/trial unit.
PUT /dc/api/policy — validated preset selections only.

Only mira-dc-control-session, mira-dc-docker-verify and mira-dc-pairing-poc service units are ever controlled. Launch uses fixed pinned paths, the existing mira-dc-poc account, and its intentionally granted docker group. HTTP requests cannot select a unit or arbitrary executable. systemd RuntimeMaxSec is the authoritative time limit; UI countdown is informational.

## Security and deployment notes
- Loopback only. Never expose port 8792 directly or add an unprotected public route.
- Auth and owner allowlist are mandatory. A valid session belonging to another Cloud Account must be denied.
- The backend executes fixed systemd calls as an elevated service and is **high risk**. Deployment requires specific authorization, review, backup and rollback. Consider a subsequent non-root HTTP listener plus fixed-command privileged helper.
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
