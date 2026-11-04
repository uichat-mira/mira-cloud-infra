# Cloud Pi private configuration on Mira server

This first-boot step works from GitHub. No home Windows computer is required.
It is not Cloud Auth UI secret management; the Cloud Auth management portal
can take over later once a safe write/rotation contract is implemented.

## Protected GitHub production Environment Secrets

In mira-cloud-infra / Settings / Environments / production, create the
following seven secret entries from the existing official bot and New API
control consoles, NEVER from ChatGPT, issues or PR comments:

- CLOUD_PI_FEISHU_APP_ID (existing Feishu robot App ID)
- CLOUD_PI_FEISHU_APP_SECRET
- CLOUD_PI_WECOM_BOT_ID
- CLOUD_PI_WECOM_BOT_SECRET
- CLOUD_PI_WECOM_BOT_NAME (name shown when group members mention the bot)
- CLOUD_PI_MODEL_API_KEY (restricted New API token; NOT master/admin key)
- CLOUD_PI_OWNER_ACCOUNT_ID (from Cloud Auth account page)

Optional secrets: CLOUD_PI_FEISHU_ALLOWED_CHAT_IDS,
CLOUD_PI_WECOM_ALLOWED_USER_IDS, CLOUD_PI_WECOM_ALLOWED_CHAT_IDS.
A blank Feishu group allowlist permits private chat only. WeCom requires
an explicit allowlist before owner-delegated external Guanlan tools can run.

REQUIRED GitHub production Environment variable CLOUD_PI_MODEL_ID selects the
model. The initial confirmed selection is deepseek-v4.1-flash-od. On the
2026-11-04 production node, an authorized New API /v1/models query returned
HTTP 200 with this model, followed by a real 16-token-max chat completion
probe (HTTP 200; response usage 49 tokens). This is model-gateway evidence,
not proof that either IM channel is connected. There is NO implicit fallback.

The already configured DEPLOY_HOST, DEPLOY_USER, DEPLOY_PASSWORD,
DEPLOY_PORT and DEPLOY_KNOWN_HOSTS from this GitHub Environment are reused.
The new provisioning path REQUIRES pinned SSH host-key verification.

## Install without starting anything

Run Actions / Provision Cloud Pi private configuration on branch prod.
Enter PROVISION in the confirmation field. The workflow checks presence and
shape without printing secret values, and streams the private file over pinned
SSH to /opt/cloud-pi/secrets/agent.env as root:1000 mode 0640. Node runs as
UID 1000 and can only read this mounted file, not change it. The private data
directory is created with mode 0700 and UID 1000. No image is loaded and no
bot or existing service is started by this workflow.

Once model availability and bot ownership are confirmed, explicitly enable
MIRA_CLOUD_PI_DEPLOY_ENABLED for the separately guarded Deploy Cloud Pi
workflow on prod. Verify both provider WebSockets, real model calls, restart
and memory. The owner management gateway health probe and Agent local health
probe are necessary but not sufficient to claim chat/Guanlan live.

Guanlan unattended delegated token renewal is NOT done by this bootstrap.
Do not paste a five-minute JWT or Cloud Session into these secrets. Leave the
private Guanlan MCP binding disabled until Cloud Auth delegation is actually
issued/renewed with caller/resource scope enforced.
