#!/usr/bin/env python3
"""Tencent DC fixed-action SSH endpoint; runs as miraops, never as root.

Install this file root-owned and expose it ONLY via an authorized_keys forced
command. Its only effects are controlling one systemd *user* transient unit
and storing the bounded policy in miraops' private home directory.
"""
from __future__ import annotations

import fcntl
import json
import os
import pwd
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

USER = "miraops"
UNIT = "mira-dc-session.service"
UNIT_NAME = "mira-dc-session"
NODE = "/usr/bin/node"
ENTRY = "/opt/mira-dc-remote/node_modules/@wonderwhy-er/desktop-commander/dist/index.js"
DURATIONS = (15, 30, 60, 120, 240)
MEMORY = (256, 384, 512)
CPU = (25, 50, 100)
HEADROOM = (384, 512, 640)
DEFAULT_POLICY = {"durationMinutes": 30, "memoryMiB": 384, "cpuPercent": 50, "minAvailableMiB": 512}


class ControlError(Exception):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code


def home() -> Path:
    return Path(pwd.getpwnam(USER).pw_dir)


def state_dir() -> Path:
    return home() / ".config" / "mira-dc-agent"


def require_user() -> None:
    if os.geteuid() != pwd.getpwnam(USER).pw_uid or os.environ.get("SSH_ORIGINAL_COMMAND", ""):
        raise ControlError(403, "不允许的调用身份")


def user_env() -> dict[str, str]:
    uid = pwd.getpwnam(USER).pw_uid
    runtime = Path(f"/run/user/{uid}")
    bus = runtime / "bus"
    if not runtime.is_dir() or not bus.exists() or runtime.stat().st_uid != uid:
        raise ControlError(503, "DC 用户管理器不可用；需要管理员启用 linger")
    env = os.environ.copy()
    env["HOME"] = str(home())
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    return env


def command(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(argv, text=True, capture_output=True, timeout=10, env=user_env())
    except (OSError, subprocess.TimeoutExpired):
        raise ControlError(503, "DC 本机服务执行失败") from None
    if check and completed.returncode:
        raise ControlError(503, "DC 本机服务执行失败")
    return completed


@contextmanager
def locked():
    directory = state_dir()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (directory / "lock").open("a+b") as handle:
        os.chmod(directory / "lock", 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(filename: str, value: dict) -> None:
    import tempfile
    directory = state_dir()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as dest:
            os.fchmod(dest.fileno(), 0o600)
            json.dump(value, dest, ensure_ascii=False)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(tmp, directory / filename)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def validate_policy(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY):
        raise ControlError(400, "运行策略字段不合法")
    for key, allowed in (
        ("durationMinutes", DURATIONS),
        ("memoryMiB", MEMORY),
        ("cpuPercent", CPU),
        ("minAvailableMiB", HEADROOM),
    ):
        if type(value[key]) is not int or value[key] not in allowed:
            raise ControlError(400, "运行策略超出允许范围")
    return value.copy()


def policy() -> dict:
    try:
        value = json.loads((state_dir() / "policy.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_POLICY.copy()
    except (ValueError, OSError):
        raise ControlError(503, "保存的运行策略损坏") from None
    return validate_policy(value)


def active() -> bool:
    return command(["systemctl", "--user", "is-active", "--quiet", UNIT], check=False).returncode == 0


def unmanaged_process() -> bool:
    output = command(["ps", "-u", USER, "-o", "args="], check=False).stdout
    return any("desktop-commander" in line and " remote" in line for line in output.splitlines())


def memory_current() -> int | None:
    value = command(["systemctl", "--user", "show", UNIT, "-p", "MemoryCurrent", "--value"], check=False).stdout.strip()
    return int(value) if value.isdigit() and int(value) < 2**60 else None


def status() -> dict:
    running = active()
    legacy = not running and unmanaged_process()
    try:
        record = json.loads((state_dir() / "session.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        record = {}
    deadline = record.get("deadline")
    seconds = max(0, int(deadline - time.time())) if running and type(deadline) in (int, float) else None
    return {
        "running": running,
        "legacyRunning": legacy,
        "remainingSeconds": seconds,
        "memoryBytes": memory_current() if running else None,
        "policy": policy(),
        "at": datetime.now(timezone.utc).isoformat(),
    }


def available_memory_mib() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 0


def start() -> dict:
    with locked():
        if active() or unmanaged_process():
            raise ControlError(409, "DC 已在运行；不要同时启动两份实例")
        chosen = policy()
        if available_memory_mib() < chosen["minAvailableMiB"]:
            raise ControlError(409, "可用内存不足，拒绝启动")
        if not Path(NODE).is_file() or not Path(ENTRY).is_file():
            raise ControlError(503, "固定版本 DC 尚未安装")
        if not (home() / ".desktop-commander-device" / "device.json").is_file():
            raise ControlError(409, "DC 设备身份尚未配对")
        command(["systemctl", "--user", "reset-failed", UNIT], check=False)
        command([
            "systemd-run", "--user", "--quiet", "--collect", f"--unit={UNIT_NAME}",
            "-p", f"WorkingDirectory={home()}",
            "-p", f"Environment=HOME={home()}",
            "-p", f"MemoryMax={chosen['memoryMiB']}M",
            "-p", f"CPUQuota={chosen['cpuPercent']}%",
            "-p", f"RuntimeMaxSec={chosen['durationMinutes'] * 60}",
            "-p", "Restart=no",
            NODE, ENTRY, "remote",
        ])
        for _ in range(10):
            if active():
                break
            time.sleep(0.2)
        if not active():
            raise ControlError(503, "DC 受限运行器没有启动")
        atomic_json("session.json", {"deadline": time.time() + chosen["durationMinutes"] * 60})
        return status()


def stop() -> dict:
    with locked():
        if active():
            command(["systemctl", "--user", "stop", UNIT])
        elif unmanaged_process():
            raise ControlError(409, "正在运行手工启动的 DC，请先从原终端退出")
        return status()


def dispatch(request: object) -> dict:
    if not isinstance(request, dict) or set(request) != {"action", "payload"}:
        raise ControlError(400, "指令格式不合法")
    action, payload = request["action"], request["payload"]
    if action == "status" and payload == {}:
        return status()
    if action == "start" and payload == {}:
        return start()
    if action == "stop" and payload == {}:
        return stop()
    if action == "policy":
        checked = validate_policy(payload)
        with locked():
            atomic_json("policy.json", checked)
            return status()
    raise ControlError(404, "不支持的操作")


def main() -> None:
    try:
        require_user()
        raw = sys.stdin.buffer.read(2049)
        if not raw or len(raw) > 2048:
            raise ControlError(400, "请求大小不合法")
        result = dispatch(json.loads(raw.decode("utf-8")))
        reply = {"ok": True, "data": result}
    except ControlError as exc:
        reply = {"ok": False, "code": exc.code, "error": str(exc)}
    except (UnicodeError, ValueError):
        reply = {"ok": False, "code": 400, "error": "请求格式不合法"}
    except Exception:
        reply = {"ok": False, "code": 503, "error": "DC 节点处理失败"}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
