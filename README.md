# Mira Cloud Infrastructure

Public, reproducible deployment configuration for Mira's first small shared cloud node.

## Scope (v0)

- **New API**: a single Docker container with a persistent SQLite data directory. The image is version-pinned.
- **GitHub Actions**: offline configuration checks and guarded `prod` deployment over SSH.
- **GitHub engineering notifications**: planned separately; no WeChat automation is included in this bootstrap.

The current target is a **2 vCPU / 2 GiB** Ubuntu host. A standalone PostgreSQL or Redis service is deliberately out of scope.

## Safety boundaries

- Docker publishes New API **only to `127.0.0.1:3000`** on the server.
- **No domain, public HTTP endpoint, password, private key, IP address, or provider API credential is checked in.**
- The `production` GitHub environment must be configured and protected before a `prod` deployment is enabled.
- Changes promote through `feat/* → dev → test → prod`. Historical `main` does **not** deploy.
- New API's upstream model reachability, service eligibility, and any future public access must be verified separately from basic container health.
- A 2 GiB host must **not** be used for heavy local model inference, Chromium workers, or parallel builds.

See [the runbook](docs/RUNBOOK.md) for SSH provisioning, deployment prerequisites, verification, backups, rollback and GitHub environment setup.

## Current source of truth

`docker-compose.yml` owns the current local deployment topology.
The `prod` workflow owns the prospective production action.
Runtime health is **not** established until a deployment has been explicitly authorized and checked on the host.

This repository is new. It is **not** a fork or migration of any company's deployment repository.
