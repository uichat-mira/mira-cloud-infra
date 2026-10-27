# Hermes Lab — isolated Docker experiment

This is a personal **experimental agent**, not a Mira product, service dependency, or multi-tenant agent platform. Do not make Cloud Auth or NewAPI depend on it. The lab must remain independent of the existing production Compose lifecycle.

## Official runtime

- Image: `nousresearch/hermes-agent:stable`; freeze the actual pulled digest before considering permanent deployment.
- Entrypoint: `gateway run` using the official image.
- Persistent data: host `./data` → `/opt/data`, including `.env`, configuration, credentials, memory, sessions, and skills.
- CPU limit 1 core, RAM limit 1 GiB, RAM+swap limit 1.5 GiB; no browser tools, parallel agents, API server, or dashboard in this experiment.
- No published ports, Docker socket mount, host home, Cloud Auth data, or provider/admin credential mounts.
- Dedicated Compose project. Reuses **only** NewAPI's existing Docker network `mira-cloud-infra_default` so a scoped dedicated token can call `http://new-api:3000/v1`. This network must exist at runtime; verify with `docker network inspect`.
- Service can make outbound requests and potentially access NewAPI over the shared internal bridge. Treat model-generated tool calls as untrusted; never give Hermes production admin tokens or unrestricted host terminal access. Initial model configuration must use a dedicated least-privilege, low-budget NewAPI token.

Official source: https://hermes-agent.nousresearch.com/docs/user-guide/docker

## Manual first-run checklist

1. Inspect host `free -h`, `swapon --show`, `df -h /` and existing service health. Confirm at least 2 GiB total host Swap and the Hermes image will fit on disk.
2. Use a **standalone server directory**, for example `/opt/hermes-lab`; place a copy of `compose.yaml` there. Do not run the lab Compose from `/opt/mira-cloud-infra`.
3. Verify `sudo docker network inspect mira-cloud-infra_default` and `sudo docker compose -f compose.yaml config --quiet`.
4. `mkdir -p data && chmod 700 data`. Pull image: `sudo docker compose -f compose.yaml pull`. Record `sudo docker image inspect nousresearch/hermes-agent:stable --format '{{index .RepoDigests 0}}'` as the release anchor.
5. **Human credential step, never log/chat the key:** create a dedicated NewAPI token with minimal allowed models/spend cap. Run `sudo docker compose -f compose.yaml run --rm hermes setup` interactively. Choose a custom OpenAI-compatible endpoint `http://new-api:3000/v1` and the dedicated token. Use a model supporting at least a 64K-token context window. Confirm `data/.env` is mode 600/owner-only; permissions must allow the container's runtime user to read it. Keep API and dashboard disabled.
6. Start only after setup: `sudo docker compose -f compose.yaml up -d`. Check `sudo docker compose -f compose.yaml ps`, `sudo docker logs --tail 100 mira-hermes-lab`, `free -h`, `swapon --show`, and `sudo docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' mira-hermes-lab`.
7. Run one short authorized model/tool test from inside the container, then stop and check both pre-existing services' local readiness endpoints. Gateway without a configured chat platform or enabled API server does not supply a remote chat interface: first-run can instead use `sudo docker compose -f compose.yaml run --rm hermes` interactively.
8. Do **not** add another Profile or enable scheduled work until the single-agent smoke demonstrates usable memory headroom, no OOM, no sustained swap churn, and existing services unaffected.

## Stop, rollback, and remove

From `/opt/hermes-lab`: `sudo docker compose -f compose.yaml down` (only this Compose project). Data directory is intentionally retained. To remove data permanently, manually review and back it up separately before deleting it.

If host `MemAvailable` persistently falls below ~250 MiB, the Hermes container OOMs, or NewAPI/Cloud Auth degrade, stop Hermes immediately and do not change their production limits to compensate.

**No unattended deployment:** this lab deliberately has no SSH deploy workflow. The existing NewAPI production action must not start/stop/recreate Hermes. A separate deploy-only workflow may be introduced after the first manual run proves image size, compatibility, and safe resource use.
