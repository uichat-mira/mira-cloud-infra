# Mira Cloud Infrastructure — Repository Instructions

Follow current `uichat-mira/.github/AGENTS.md` and the related Organization engineering documents.

## Purpose
This public repository manages a small Mira-owned cloud node and its reproducible, auditable deployment configuration. Do not import company-specific domain, certificates, credentials, hosts, or deployment paths.

## Environment model
`feat/* → dev → test → prod`. `main` is a non-production bootstrap branch. Changes to `prod` are production-impacting and require authorized promotion, backups, and post-deployment verification.

## Security and operations
- Never commit secrets, server addresses, credentials, SQLite databases, account data, certificates' private keys, or production logs.
- Keep New API bound to the server's loopback interface until a separate, reviewed public HTTPS/domain/ICP plan exists.
- Do not weaken SSH host-key validation, expand public ports, auto-enable public account registration, or broaden provider/model reachability without explicit authorization.
- Keep the host small: New API + SQLite only for the first slice. Add other services independently after resource measurements.
- Treat deploy scripts, GitHub Actions, persistence, and secrets as high-risk surfaces.
- Production deployment must originate on `prod`, never `main` or a feature branch. A successful CI check does not imply deployment health.
- Docker data under `/opt/mira-cloud-infra/data` persists independently of source deployments. Back up before upgrades and record a rollback anchor.

## Testing
`bash scripts/check.sh` is the fast, credentials-free repository check. It verifies shell syntax, Docker Compose parseability, loopback port binding, expected service shape, and version pinning.
`Mira Gate` must fail if this check is skipped or fails.
A real runtime smoke of `/api/status` is required after an authorized production deployment; do not claim it passed unless observed.
