# Mira Cloud Node — first deployment runbook

## Intent
This is a small shared node, not a general production cluster. The first deployment is **New API + SQLite only**, bound to the host's loopback interface. GitHub Webhook processing and notification adapters are **future work**; do not confuse this gateway with a WeChat bot.

No public HTTP/HTTPS endpoint is configured until a separate domain/ICP/security decision is completed. SSH port forwarding is the supported initial access pattern.

## Bootstrap on Ubuntu
1. Use a non-root SSH account that accepts password authentication (initial target: `admin`). Use a long, unique password stored only in the protected GitHub `production` Environment Secret. A Docker-enabled account is effectively root-equivalent: tightly restrict workflow edit and deployment rights.
2. Install Docker Engine and the Docker Compose plugin from the vendor's supported Ubuntu installation instructions. Confirm `docker version`, `docker compose version`, disk and memory.
3. Do **not** open TCP 3000. Verify the selected SSH account supports password login. Disable root SSH login, use a strong unique password and rate limiting, and preserve an emergency cloud-console recovery path.
4. Allocate swap only after reviewing host disk/memory. Swap reduces short peaks, not sustained overload.
5. **Networking decision is not automatic:** normal GitHub-hosted Actions runners have changing source IPs. A direct password SSH deployment needs inbound SSH access reachable from the runner. A home-IP-only rule will block CI; exposing password SSH broadly increases brute-force risk. Do not loosen the firewall merely to make CI green; approve a hardened inbound or private/outbound deployment path first.
6. Allow the deploy SSH user to write `/opt/mira-cloud-infra` and access Docker; make `data/` and `backups/` private. Confirm `curl` and `gzip` are installed.

## GitHub production setup — required before creating/promoting prod
In repository **Settings → Environments**, create `production`. Restrict deployment branches to `prod`; enable required reviewers where supported.

Place these **environment secrets**, never repository files or comments:

| Name | Meaning |
| --- | --- |
| `DEPLOY_HOST` | SSH host (do not commit the server IP) |
| `DEPLOY_USER` | deploy account |
| `DEPLOY_PORT` | SSH port, normally `22` |
| `DEPLOY_PASSWORD` | SSH password for `DEPLOY_USER`, securely injected into `sshpass` using `SSHPASS` in the deploy step |
| `DEPLOY_KNOWN_HOSTS` | trusted, pre-verified OpenSSH known_hosts entry, including `[host]:port` format for nonstandard ports |

Obtain and independently verify the host's SSH public-key fingerprint **out of band** before recording `DEPLOY_KNOWN_HOSTS`. Do not silently accept a key obtained from the same untrusted network connection. The workflow enforces strict host-key checking.

Configure branch protection for `prod`, including required `Mira Gate`, reviews, and disallow direct pushes. This protection must be done by an authorized repository administrator; adding a YAML file does not create GitHub branch protection.

## Flow
`feat/* → dev → test → prod`, with CI on `dev/test/prod`. `main` never deploys. Only a production-authorized promotion to `prod` can trigger SSH deployment.

Production workflow:
1. Validate Compose and shell contracts; assert loopback-only service.
2. Pull the fixed New API image on GitHub Actions, save and gzip it to avoid requiring registry pulls from the Guangzhou host.
3. Authenticate with username/password from GitHub Environment Secrets, validate the pinned server host key, and upload the bundle to `/opt/mira-cloud-infra`.
4. Stop the running SQLite writer if present, take a restricted data snapshot, and load the image.
5. Start Compose without pulling, check `http://127.0.0.1:3000/api/status` from the host.
6. Record commit SHA on host. Production smoke is **local only**; this does not establish public HTTPS or upstream model connectivity.

## Initial private access
From an authorized workstation, create an SSH local tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 DEPLOY_USER@SERVER_HOST
```

Then visit `http://127.0.0.1:3000` locally and complete initial New API admin setup. Do not expose admin registration or the API port to the public Internet.

## Verification and rollback
After each deployment, inspect:
- `docker compose -f /opt/mira-cloud-infra/docker-compose.yml ps`;
- `curl -fsS http://127.0.0.1:3000/api/status`;
- disk free space, memory/swap, container restarts and log volume;
- a real authorized model-call smoke **only** after provider connectivity and regional permissions are verified.

The deployment script creates timestamped `backups/data-*.tar.gz` snapshots while the SQLite writer is stopped, before replacing a running application. Retain a verified copy off-host before major upgrades: one disk is not a backup strategy.

If a deployment breaks:
1. Stop the gateway and prevent further CI deployment.
2. Restore the last known-good compose/image tag and, **only if necessary**, its matched SQLite snapshot while stopped.
3. Bring the gateway up, repeat local health and authorized API smoke, and record the rollback commit.
4. Do not automatically reverse an application/database schema upgrade without checking compatibility.

## Known limits
- Public password-based SSH is an explicit operating tradeoff: enforce strong unique credentials, least privilege in GitHub, network controls and prompt password rotation after suspected exposure.
- Current pinned image: `calciumion/new-api:v1.0.0-rc.37` from the reference deployment. This is a release-candidate build and **not approved for broader external production use** without reviewing upstream advisories and upgrading in a separate verified task.
- `/api/status` verifies that the local gateway responds; it does not prove upstream model API availability.
- No domain, ICP, public HTTPS, WeChat-group integration, external user onboarding or paid API distribution is provided by this repository yet.
- Any gateway public exposure, cross-border API access and applicable service-provider/regulatory requirements require a separate approval and verification.
