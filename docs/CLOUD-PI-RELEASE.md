# Cloud Pi release via Mira Cloud Infra

Cloud Pi code, Dockerfile and Compose live in `uichat-mira/cloud-pi`.
This Infra repository owns **the remote deployment process**, not another
copy of Cloud Pi's Compose source.

A reviewed immutable SHA is stored in `cloud-pi/version.txt`. Infra's
`prod` workflow downloads the matching release image and Compose to the
**GitHub Actions runner**, verifies SHA-256 and ships over the existing Infra
SCP/SSH transport. The Guangzhou server never has to fetch a 123 MB
GitHub Release asset or compile Node dependencies.

**Deployment is currently disarmed.** It requires promotion through
`feat → dev → test → prod` and the existing protected production environment,
plus the repository variable `MIRA_CLOUD_PI_DEPLOY_ENABLED=true`.
Nothing deploys from feature, dev or main.

Before arming: ensure `/opt/cloud-pi/secrets/agent.env` has all real
credentials and is readable by the container's UID 1000; provision a
writable persistent `/opt/cloud-pi/data`; confirm the competing Windows
Feishu/WeCom instances are stopped. Do not commit or print secrets.

Cloud Pi is an independent Compose project under `/opt/cloud-pi`.
New API's existing Compose/workflow, Cloud Auth and Caddy are unchanged.
After start, a loopback health check is only a liveness check; genuine
Feishu, WeCom and Guanlan use must be observed after the switchover.
Short-lived Guanlan JWTs cannot substitute for background delegation.

The prior image remains present, previous Compose is backed up before
transfer, prior Cloud Pi state is archived before replacement, and the last
release SHA is recorded. No `down -v`, cross-service restart or DB mutation.

This uses Infra's current Appleboy password SSH contract, including its
documented host-verification risk. Hardening that transport should be
a separate scoped change, not silently weakened or misrepresented here.
