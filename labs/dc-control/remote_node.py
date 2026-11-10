#!/usr/bin/env python3
"""Root-only, fixed-destination SSH client for the Tencent DC remote agent.

No user-controlled host, port, shell command, SSH option or target unit is
accepted. Configuration and pinned host key live outside the public repo.
"""
from __future__ import annotations

import ipaddress
import json
import os
import stat
import subprocess
from pathlib import Path

CONFIG_DIR = Path("/etc/mira-dc-remote")
CONFIG = CONFIG_DIR / "target.json"
IDENTITY = CONFIG_DIR / "id_ed25519"
KNOWN_HOSTS = CONFIG_DIR / "known_hosts"
USER = "miraops"
ACTIONS = frozenset({"status", "start", "stop", "policy"})


class RemoteError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def protected(path: Path, *, secret: bool = True) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise RemoteError(503, "腾讯云 SSH 控制身份尚未安装") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RemoteError(503, "远程控制配置文件权限不安全")
    if secret and info.st_mode & 0o077:
        raise RemoteError(503, "远程控制私钥或配置文件权限不安全")


def target() -> tuple[str, int]:
    try:
        info = CONFIG_DIR.lstat()
    except OSError:
        raise RemoteError(503, "远程控制未配置") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise RemoteError(503, "远程控制目录权限不安全")
    protected(CONFIG)
    protected(IDENTITY)
    protected(KNOWN_HOSTS, secret=False)
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict) or set(cfg) != {"host", "port"}:
            raise ValueError("unrecognized config")
        host = str(ipaddress.IPv4Address(cfg["host"]))
        port = cfg["port"]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid port")
        return host, port
    except (ValueError, TypeError, OSError, KeyError):
        raise RemoteError(503, "远程控制目标配置无效") from None


def request(action: str, payload: dict) -> dict:
    if action not in ACTIONS or not isinstance(payload, dict):
        raise RemoteError(400, "不支持的远程操作")
    if action != "policy" and payload:
        raise RemoteError(400, "远程操作不接受参数")
    host, port = target()
    # No shell, no user-provided remote command. The authorized_keys forced
    # command on Tencent executes only remote_agent.py as unprivileged miraops.
    argv = [
        "/usr/bin/ssh", "-F", "/dev/null", "-T",
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no",
        "-o", "RequestTTY=no", "-o", "ConnectTimeout=5",
        "-p", str(port), "-i", str(IDENTITY), f"{USER}@{host}",
    ]
    try:
        result = subprocess.run(
            argv, input=json.dumps({"action": action, "payload": payload}),
            text=True, capture_output=True, timeout=17, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RemoteError(503, "腾讯云节点连接失败") from None
    if result.returncode or len(result.stdout) > 8192:
        raise RemoteError(503, "腾讯云节点未响应（检查 SSH 身份与连通性）")
    try:
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise ValueError("unexpected agent response")
        if not response["ok"]:
            code = response.get("code")
            if type(code) is not int or code not in (400, 403, 404, 409, 503):
                code = 503
            error = response.get("error")
            if not isinstance(error, str) or len(error) > 120:
                error = "腾讯云节点操作失败"
            raise RemoteError(code, error)
        data = response.get("data")
        if not isinstance(data, dict):
            raise ValueError("missing status")
        if type(data.get("running")) is not bool or type(data.get("legacyRunning")) is not bool:
            raise ValueError("invalid status booleans")
        if not isinstance(data.get("policy"), dict):
            raise ValueError("missing policy")
        policy = data["policy"]
        allowed = {
            "durationMinutes": (15, 30, 60, 120, 240),
            "memoryMiB": (256, 384, 512),
            "cpuPercent": (25, 50, 100),
            "minAvailableMiB": (384, 512, 640),
        }
        if set(policy) != set(allowed) or any(type(policy[k]) is not int or policy[k] not in vals for k, vals in allowed.items()):
            raise ValueError("invalid remote policy")
        for key in ("remainingSeconds", "memoryBytes"):
            value = data.get(key)
            if value is not None and (type(value) not in (int, float) or value < 0 or value > 2**60):
                raise ValueError("invalid remote resource")
        if not isinstance(data.get("at"), str) or len(data["at"]) > 64:
            raise ValueError("invalid timestamp")
        # Return only the existing DC status response fields.
        return {
            "running": data["running"],
            "legacyRunning": data["legacyRunning"],
            "remainingSeconds": data.get("remainingSeconds"),
            "memoryBytes": data.get("memoryBytes"),
            "policy": data["policy"],
            "at": data.get("at"),
        }
    except (TypeError, ValueError, KeyError):
        raise RemoteError(503, "腾讯云节点返回了无效响应") from None
