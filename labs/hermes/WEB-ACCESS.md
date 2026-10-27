# Hermes remote dashboard — OAuth gate, no direct exposure

The remote HTTPS origin is operator-provisioned, not stored in this public repository. The application is a high-trust management surface: it can read or modify credentials, invoke agent tools and affect files. **Do not use password-only authentication on the public internet** and never publish container port 9119 to 0.0.0.0.

Official docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard

## Before public HTTPS

1. Register a Nous Research dashboard in the logged-in portal's **Local Dashboards** area, with an HTTPS redirect URI matching `<public-origin>/auth/callback`. Obtain public client ID `agent:...`. Alternatively run `hermes dashboard register --redirect-uri <public-origin>/auth/callback` after logging in to Nous Portal on the Hermes host.
2. Put the OAuth client ID in the host-only `/opt/hermes-lab/data/.env` as `HERMES_DASHBOARD_OAUTH_CLIENT_ID=agent:...`, or use `dashboard.oauth.client_id` in the private `data/config.yaml`. Never include a model API key, Nous login session, or other credentials in public GitHub files.
3. Set the public HTTPS origin as `HERMES_PUBLIC_ORIGIN` in the host-only Compose environment, e.g. a private `/opt/hermes-lab/.env`. Ensure Caddy has a valid certificate and reverse-proxies the hostname to `127.0.0.1:9119` only.
4. `docker compose -f compose.yaml -f compose.web.yaml config --quiet` and inspect effective host port bindings. Preflight must confirm OAuth is registered. Only then run `docker compose -f compose.yaml -f compose.web.yaml up -d --no-deps --pull never`.
5. Verify `/api/status` reports `auth_required=true` and `auth_providers` includes `nous`, and `/api/auth/me` without a cookie is rejected (401). Do not deploy Caddy reverse proxy before those gates pass. Browser login through Nous Portal must complete to accept the service.
6. Continue verifying the already-running NewAPI and Cloud Auth local health endpoints, HTTPS from a real client, and that no external port 9119 is allowed. Preserve the Gateway's 1GiB RAM limit and no-autorestart experimental setting.

## Fail closed / rollback

`docker compose -f compose.yaml -f compose.web.yaml down` stops only Hermes. Use the base `compose.yaml` to return to private Gateway-only runtime; its model config, memory and sessions remain in `./data`. Restore backed-up Caddy main file and remove only the Hermes snippet if ingress checks fail, then `caddy validate` and reload. Do not modify existing ingress sites to compensate.

Do **not** conflate the public Nous OAuth client ID with the model-provider NewAPI API token. They are independent.
