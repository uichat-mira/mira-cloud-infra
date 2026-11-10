# Tencent Cloud node host baseline

This is a **host-only bootstrap**, not the Mira Cloud application. It does not
deploy Cloud Auth, Cloud Pi, PostgreSQL, or any application containers.

- Ubuntu 26.04 LTS, existing paired Desktop Commander (miraops) untouched.
- Ubuntu-signed Docker Engine (docker.io) and Compose v2 installed as system services.
- Caddy from its signed official stable apt repository; Caddyfile is explicitly
  bound to 127.0.0.1:8090 with a local-only /healthz.
- No published Docker ports, HTTPS domain, firewall rule, external container
  API, root-equivalent docker membership for miraops, or newly opened 80/443.
- /opt/mira-cloud-node/stacks and restricted data/backups are reserved for
  independently reviewed service deployments.
- Deliberately no new app container, database, task scheduler, or reboot.
- Package installation uses temporary Debian policy-rc.d to prevent Caddy's
  package default config from listening on public port 80.
- The temporary production manual workflow consumes existing TX_DEPLOY_*
  GitHub secrets; it pins the Tencent ED25519 host identity verified from
  the server console. Remove it after the one-time install.

Verification as authorized admin:
docker info; docker compose version; systemctl is-active docker caddy;
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile;
curl --noproxy '*' http://127.0.0.1:8090/healthz; ss -lnt;
id -nG miraops (must not include docker).

The source can be rerun in inspect mode without modifying anything.
Install intentionally refuses an already installed or partially configured
host rather than blindly replaying a privileged installer.

## Caddy listener correction

The initial v0 Caddyfile used `http://127.0.0.1:8090` without a
`bind` directive. In Caddy this matched the HTTP host header but actually
listened on `*:8090`; the original install correctly failed its listener
check after packages had already been installed. Never rerun `install` in
that partially provisioned state. The scoped `repair` operation compares the
exact old Caddyfile, backs it up under restricted root-owned storage, adds
`bind 127.0.0.1`, restarts Caddy, and fails closed (stops Caddy) if the
real socket is not loopback-only. Docker and the DC user session are untouched.
