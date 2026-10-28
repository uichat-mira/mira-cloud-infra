#!/usr/bin/env python3
"""Minimal DC operator console. Do not expose directly to the Internet."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PREFIX = "/dc"
ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("MIRA_DC_STATE_DIR", "/var/lib/mira-dc-control"))
OWNER_ID = os.environ.get("MIRA_DC_OWNER_ACCOUNT_ID", "").strip()
ORIGIN = os.environ.get("MIRA_DC_ALLOWED_ORIGIN", "https://cloud-auth.tomzlab.cn")
AUTH_URL = "http://127.0.0.1:8788/v1/auth/session"
NODE = "/opt/mira-dc-poc/v0.3.1/node"
ENTRY = "/opt/mira-dc-poc/v0.3.1/node_modules/@wonderwhy-er/desktop-commander/dist/index.js"
DEVICE_HOME = "/var/lib/mira-dc-poc"
UNIT = "mira-dc-control-session.service"
LEGACY_UNITS = ("mira-dc-docker-verify.service", "mira-dc-pairing-poc.service")
DURATIONS = (15, 30, 60, 120, 240)
MEMORY = (256, 384, 512)
CPU = (25, 50, 100)
MIN_AVAILABLE = (384, 512, 640)
DEFAULT_POLICY = {"durationMinutes": 30, "memoryMiB": 384, "cpuPercent": 50, "minAvailableMiB": 512}
LOCK = Lock()


class ControlError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, check=check, text=True, capture_output=True, timeout=8)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        raise ControlError(503, "系统服务操作失败，请检查主机日志") from None


def atomic_json(name: str, data: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix=".dc-state-", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, STATE_DIR / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def policy() -> dict:
    try:
        raw = json.loads((STATE_DIR / "policy.json").read_text(encoding="utf-8"))
        return validate_policy(raw)
    except FileNotFoundError:
        return DEFAULT_POLICY.copy()


def validate_policy(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != set(DEFAULT_POLICY):
        raise ControlError(400, "策略字段不合法")
    for k, choices in (("durationMinutes", DURATIONS), ("memoryMiB", MEMORY),
                       ("cpuPercent", CPU), ("minAvailableMiB", MIN_AVAILABLE)):
        if type(data[k]) is not int or data[k] not in choices:
            raise ControlError(400, f"{k} 超出允许范围")
    return data.copy()


def active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def unit_memory() -> int | None:
    try:
        p = run(["systemctl", "show", UNIT, "-p", "MemoryCurrent", "--value"], check=False)
        v = p.stdout.strip()
        return int(v) if v.isdigit() and int(v) < 2**60 else None
    except ControlError:
        return None


def status() -> dict:
    running = active(UNIT)
    legacy = [unit for unit in LEGACY_UNITS if active(unit)]
    try:
        record = json.loads((STATE_DIR / "session.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        record = {}
    now = time.time()
    return {
        "running": running,
        "legacyRunning": bool(legacy),
        "legacyUnitNames": legacy,
        "remainingSeconds": max(0, int(record.get("deadline", 0) - now)) if running else None,
        "memoryBytes": unit_memory() if running else None,
        "policy": policy(),
        "at": datetime.now(timezone.utc).isoformat(),
    }


def start_session() -> dict:
    with LOCK:
        if active(UNIT) or any(active(unit) for unit in LEGACY_UNITS):
            raise ControlError(409, "DC 已在运行，请先停止当前会话")
        p = policy()
        avail = 0
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) // 1024
                break
        if avail < p["minAvailableMiB"]:
            raise ControlError(409, "可用内存不足，已拒绝启动 DC")
        if not (Path(NODE).is_file() and Path(ENTRY).is_file()):
            raise ControlError(503, "DC 运行环境不存在")
        if not (Path(DEVICE_HOME) / ".desktop-commander-device/device.json").is_file():
            raise ControlError(409, "DC 尚未完成设备配对")
        run(["systemctl", "reset-failed", UNIT], check=False)
        args = [
            "systemd-run", "--quiet", "--collect", "--unit=mira-dc-control-session",
            "-p", "User=mira-dc-poc", "-p", "Group=mira-dc-poc",
            "-p", "SupplementaryGroups=docker",
            "-p", f"WorkingDirectory={DEVICE_HOME}", "-p", f"Environment=HOME={DEVICE_HOME}",
            "-p", f"MemoryMax={p['memoryMiB']}M",
            "-p", f"CPUQuota={p['cpuPercent']}%",
            "-p", f"RuntimeMaxSec={p['durationMinutes'] * 60}",
            "-p", "Restart=no",
            NODE, ENTRY, "remote",
        ]
        run(args)
        for _ in range(10):
            if active(UNIT):
                break
            time.sleep(0.15)
        if not active(UNIT):
            raise ControlError(503, "DC 启动失败，请查看 systemd 日志")
        atomic_json("session.json", {"deadline": time.time() + p["durationMinutes"] * 60})
        return status()


def stop_session() -> dict:
    with LOCK:
        for unit in (UNIT, *LEGACY_UNITS):
            if active(unit):
                run(["systemctl", "stop", unit])
        return status()


def get_account(bearer: str) -> dict:
    if not OWNER_ID:
        raise ControlError(503, "管理员账户未配置")
    if not re.fullmatch(r"Bearer mcs_v1\.[A-Za-z0-9._-]{12,1024}", bearer):
        raise ControlError(401, "需要登录 Mira Cloud Account")
    try:
        req = Request(AUTH_URL, headers={"Authorization": bearer, "Accept": "application/json"})
        with urlopen(req, timeout=3) as response:
            if response.status != 200:
                raise ControlError(401, "云账号会话无效")
            body = json.loads(response.read(4096))
    except HTTPError as error:
        raise ControlError(401 if error.code == 401 else 503, "云账号会话校验失败") from None
    except (URLError, ValueError, TimeoutError, OSError):
        raise ControlError(503, "云认证服务暂不可用") from None
    account = body.get("account")
    if not isinstance(account, dict) or account.get("id") != OWNER_ID:
        raise ControlError(403, "当前账号无权管理这台服务器")
    return account


class Handler(BaseHTTPRequestHandler):
    server_version = "MiraDCControl/1.0"
    sys_version = ""

    def send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, file: str, mime: str) -> None:
        body = (ROOT / file).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self, method: str) -> None:
        try:
            p = self.path.split("?", 1)[0]
            static = {
                PREFIX + "/": ("index.html", "text/html; charset=utf-8"),
                PREFIX + "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                PREFIX + "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            }
            if method == "GET" and p in static:
                return self.send_static(*static[p])
            if not p.startswith(PREFIX + "/api/"):
                return self.send_json(404, {"error": "not_found"})
            get_account(self.headers.get("Authorization", ""))
            if method == "GET" and p == PREFIX + "/api/status":
                return self.send_json(200, status())
            if method not in ("POST", "PUT") or self.headers.get("Origin") != ORIGIN:
                raise ControlError(403, "不允许的操作来源")
            size = self.headers.get("Content-Length", "")
            if not size.isdigit() or int(size) > 2048:
                raise ControlError(400, "请求大小不合法")
            body = self.rfile.read(int(size))
            try:
                data = json.loads(body)
            except ValueError:
                raise ControlError(400, "请求格式无效") from None
            if method == "POST" and p == PREFIX + "/api/start" and data == {}:
                return self.send_json(200, start_session())
            if method == "POST" and p == PREFIX + "/api/stop" and data == {}:
                return self.send_json(200, stop_session())
            if method == "PUT" and p == PREFIX + "/api/policy":
                with LOCK:
                    checked = validate_policy(data)
                    atomic_json("policy.json", checked)
                return self.send_json(200, status())
            raise ControlError(404, "不支持的接口")
        except ControlError as error:
            self.send_json(error.code, {"error": str(error)})
        except Exception:
            self.send_json(503, {"error": "控制台内部错误"})

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def log_message(self, fmt: str, *args) -> None:
        # Do not log requests that could carry credentials; log only status.
        pass


def main() -> None:
    if not OWNER_ID or not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", OWNER_ID):
        raise SystemExit("MIRA_DC_OWNER_ACCOUNT_ID must be configured")
    host, port = "127.0.0.1", 8792
    print(f"DC control listening on {host}:{port} (loopback only)", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
