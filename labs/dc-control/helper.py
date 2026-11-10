#!/usr/bin/env python3
"""Fixed-action privileged helper. ONLY callable by the DC control service via sudo."""
from __future__ import annotations
import json
import os
import pwd
import sys
from pathlib import Path
from server import ControlError, atomic_json, policy, start_session, status, stop_session, validate_policy, LOCK
from remote_node import RemoteError, request as remote_request


def main() -> None:
    try:
        try:
            caller = pwd.getpwnam("mira-dc-control").pw_uid
        except KeyError:
            raise ControlError(403, "不允许的调用来源") from None
        if os.geteuid() != 0 or os.environ.get("SUDO_UID") != str(caller) or len(sys.argv) != 1:
            raise ControlError(403, "不允许的调用来源")
        raw = sys.stdin.buffer.read(2049)
        if len(raw) > 2048 or not raw:
            raise ControlError(400, "请求过大")
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) != {"action", "payload"}:
            raise ControlError(400, "指令格式无效")
        action, payload = request["action"], request["payload"]
        if action == "status" and payload == {}:
            result = status()
        elif action == "start" and payload == {}:
            result = start_session()
        elif action == "stop" and payload == {}:
            result = stop_session()
        elif action == "policy":
            with LOCK:
                atomic_json("policy.json", validate_policy(payload))
                result = status()
        elif action == "remote_status" and payload == {}:
            result = remote_request("status", {})
        elif action == "remote_start" and payload == {}:
            result = remote_request("start", {})
        elif action == "remote_stop" and payload == {}:
            result = remote_request("stop", {})
        elif action == "remote_policy":
            result = remote_request("policy", validate_policy(payload))
        else:
            raise ControlError(404, "不支持的操作")
        print(json.dumps({"ok": True, "data": result}, separators=(",", ":")))
    except (ControlError, RemoteError, ValueError) as error:
        code = error.code if isinstance(error, (ControlError, RemoteError)) else 400
        print(json.dumps({"ok": False, "code": code, "error": str(error) if isinstance(error, (ControlError, RemoteError)) else "无效请求"}))
    except Exception:
        print(json.dumps({"ok": False, "code": 503, "error": "系统控制失败"}))


if __name__ == "__main__":
    main()
