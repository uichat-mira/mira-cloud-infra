# OPS-027 · Tencent DC Actions release path

This is an **interim, manually dispatched deployment workflow** for the existing
Tencent DC node, **not** the intended long-term peer-agent authentication
protocol for Mira Cloud Account. The owner-approved future target is independently
authenticated Aliyun/Tencent node agents.

## Credential scope

The organization already has these three secrets:

- `TX_DEPLOY_HOST` — Tencent SSH host;
- `TX_DEPLOY_USER` — deploy SSH user; currently a root context is required;
- `TX_DEPLOY_PASSWORD` — corresponding SSH password.

No additional **secret** is required for this workflow. It pins the public
Tencent Ed25519 SSH host-key fingerprint, independently confirmed at the
Tencent console and from the Aliyun connection, inside the workflow.
A host-key rotation needs a reviewed update to that pin; never replace it with
unauthenticated `ssh-keyscan`.

Org-level secrets scoped to **Public repositories** can be inherited by multiple
public repos. Prefer restricting them to selected repositories when operationally
possible; do not print the values, paste credentials into issues, or copy them
into source.

## Operations

Workflow: `.github/workflows/tencent-dc-node.yml`

1. The candidate passes the normal `feat/* → dev → test → prod` progression
   and relevant checks. The workflow executes only by manual
   `workflow_dispatch` from **`prod`** with environment `production`.
   Pushing to `dev`, `test`, or `prod` never activates the Tencent workflow.
2. Choose `verify` (default). It makes a pinned SSH connection using the three
   TX secrets, confirms the existing root-owned Agent/paired user files, and
   invokes only the non-mutating `{"action":"status","payload":{}}`. The workflow
   **does not start, stop, or extend** a DC session.
3. After an approved, reviewed remote-agent source update, choose
   `deploy-agent`. It first runs the same read-only preflight, then transfers
   **only** `labs/dc-control/remote_agent.py` from the exact `prod` commit.
   The remote side checks its SHA-256, creates a root-private backup, atomically
   swaps that one file, verifies status as `miraops`, and restores the backup
   automatically if the status smoke fails.
4. A completed deploy writes `/opt/mira-dc-remote/.deployed-sha`; a successful
   identical-commit retry is a no-op. A partial failed attempt with an existing
   backup must be inspected and reconciled instead of silently overwritten.

## Scope boundaries

- **No** process restart, service start, systemd policy change, npm reinstall,
  SSH authorized_keys rewrite, Cloud Session mutation, Caddy change, new TCP
  port, or modification of the Aliyun deployment.
- The existing systemd `RuntimeMaxSec` remains authoritative; the action
  does **not** change the currently running session's time limit or promise a
  six-hour session.
- The read-only remote smoke proves only that the fixed Agent can report its
  systemd status. It does **not** prove Remote MCP online state, authenticated
  Mira Cloud Account controls, or automatic shutdown at the deadline.
- Missing secrets, wrong deploy user, mismatch in the pinned SSH host key, bad
  version hash, missing Agent files, and unsafe preflight all **fail closed**.
- Promotion and T5 production smoke must be recorded separately with source
  SHA, actual workflow run, and observed result.
