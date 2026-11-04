#!/usr/bin/env python3
"""Generate Cloud Pi private runtime config from protected environment secrets.
Never echo values; output path must be outside the repository.
"""
import os
import re
import stat
import sys
from pathlib import Path

REQUIRED = {
    "FEISHU_APP_ID": "CLOUD_PI_FEISHU_APP_ID",
    "FEISHU_APP_SECRET": "CLOUD_PI_FEISHU_APP_SECRET",
    "WECOM_BOT_ID": "CLOUD_PI_WECOM_BOT_ID",
    "WECOM_BOT_SECRET": "CLOUD_PI_WECOM_BOT_SECRET",
    "WECOM_BOT_NAME": "CLOUD_PI_WECOM_BOT_NAME",
    "CLOUD_PI_MODEL_API_KEY": "CLOUD_PI_MODEL_API_KEY",
    "CLOUD_AGENT_OWNER_ACCOUNT_ID": "CLOUD_PI_OWNER_ACCOUNT_ID",
}
OPTIONAL = {
    "FEISHU_ALLOWED_CHAT_IDS": "CLOUD_PI_FEISHU_ALLOWED_CHAT_IDS",
    "WECOM_ALLOWED_USER_IDS": "CLOUD_PI_WECOM_ALLOWED_USER_IDS",
    "WECOM_ALLOWED_CHAT_IDS": "CLOUD_PI_WECOM_ALLOWED_CHAT_IDS",
}
FIXED = {
    "CLOUD_AGENT_CHANNELS": "feishu,wecom",
    "CLOUD_AGENT_STATE_DIR": "/var/lib/cloud-pi/state",
    "RESEARCH_RUNS_DIR": "/var/lib/cloud-pi/runs",
    "CLOUD_AGENT_API_HOST": "127.0.0.1",
    "CLOUD_AGENT_API_PORT": "8787",
    "CLOUD_PI_MODEL_BASE_URL": "http://127.0.0.1:3000/v1",
    "CLOUD_PI_MODEL_MAX_OUTPUT_TOKENS": "2048",
    "CLOUD_PI_MAX_TOOL_CALLS": "6",
    "FEISHU_RESEARCH_MAX_CONCURRENT": "1",
    "CLOUD_AGENT_PORTAL_ORIGIN": "https://cloud-auth.tomzlab.cn",
    "CLOUD_AGENT_OWNER_GATEWAY_PORT": "8793",
}
def quote(key, value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(key + " must have a bounded value")
    if any(ch in value for ch in ('"', "'", "\\", "#", "\n", "\r", "\0")):
        raise ValueError(key + " contains unsupported env-file characters")
    return '"' + value + '"' if " " in value else value

def render(env):
    missing = [v for v in REQUIRED.values() if not env.get(v, "").strip()]
    if missing:
        raise ValueError("Missing GitHub Environment Secrets: " + ", ".join(missing))
    vals = dict(FIXED)
    vals.update({key: env[source] for key, source in REQUIRED.items()})
    vals.update({key: env[source] for key, source in OPTIONAL.items() if env.get(source, "").strip()})
    vals["CLOUD_PI_MODEL_ID"] = env.get("CLOUD_PI_MODEL_ID", "").strip() or "deepseek-chat"
    if not re.fullmatch(r"cli_[A-Za-z0-9]+", vals["FEISHU_APP_ID"]):
        raise ValueError("CLOUD_PI_FEISHU_APP_ID must be cli_... format")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,128}", vals["CLOUD_AGENT_OWNER_ACCOUNT_ID"]):
        raise ValueError("CLOUD_PI_OWNER_ACCOUNT_ID invalid")
    if len(vals["CLOUD_PI_MODEL_ID"]) > 200:
        raise ValueError("CLOUD_PI_MODEL_ID invalid")
    return "# Created by protected Infra workflow; never check into Git.\n" + "".join(
        key + "=" + quote(key, value) + "\n" for key, value in vals.items()
    )

def main():
    if len(sys.argv) != 2:
        print("Provide one private output path", file=sys.stderr)
        return 2
    try:
        dest = Path(sys.argv[1]).resolve()
        repo = Path(os.environ.get("GITHUB_WORKSPACE", os.getcwd())).resolve()
        if repo == dest or repo in dest.parents:
            raise ValueError("refusing output inside checkout")
        result = render(dict(os.environ))
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(dest, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(result)
        os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)
    except (ValueError, OSError) as err:
        print("Private configuration refused: " + str(err), file=sys.stderr)
        return 2
    print("Private Cloud Pi configuration validated; values not displayed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
