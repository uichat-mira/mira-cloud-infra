#!/usr/bin/env python3
"""OPS-027: root-only Aliyun controller SSH identity/target bootstrap.

A verified server SSH host-key file must be supplied by an operator. We never
automatically trust ssh-keyscan results, and never print private keys.
"""
from __future__ import annotations

import ipaddress
import json
import os
import stat
import subprocess
from pathlib import Path

DEST = Path("/etc/mira-dc-remote")
IDENTITY = DEST / "id_ed25519"
TARGET = DEST / "target.json"
KNOWN = DEST / "known_hosts"


def ensure(condition: bool, error: str) -> None:
    if not condition:
        raise SystemExit(error)


def main() -> None:
    ensure(os.geteuid() == 0, "ROOT_REQUIRED")
    try:
        host = str(ipaddress.IPv4Address(os.environ["MIRA_DC_TENCENT_IPV4"]))
    except (KeyError, ValueError):
        raise SystemExit("INVALID_TENCENT_TARGET") from None
    # First iteration deliberately uses the existing SSH 22 port.
    verified_path = Path(os.environ.get("MIRA_DC_VERIFIED_HOSTKEY_FILE", ""))
    ensure(verified_path.is_file() and not verified_path.is_symlink(), "VERIFIED_HOST_KEY_FILE_REQUIRED")
    info = verified_path.stat()
    ensure(info.st_uid == 0 and not info.st_mode & 0o022, "VERIFIED_HOST_KEY_FILE_MUST_BE_ROOT_OWNED")
    ensure(any(
        line.split()[0] == host for line in verified_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and len(line.split()) >= 3
    ), "VERIFIED_FILE_MISSING_TARGET_HOST")
    verified = subprocess.run(
        ["/usr/bin/ssh-keygen", "-F", host, "-f", str(verified_path)],
        check=False, capture_output=True, text=True, timeout=5,
    )
    ensure(verified.returncode == 0, "VERIFIED_HOST_KEY_LOOKUP_FAILED")
    if DEST.exists():
        item = DEST.lstat()
        ensure(stat.S_ISDIR(item.st_mode) and item.st_uid == 0 and not item.st_mode & 0o077,
               "INSECURE_EXISTING_CONTROLLER_DIR")
    else:
        DEST.mkdir(mode=0o700)
    os.chmod(DEST, 0o700)
    if IDENTITY.exists():
        info = IDENTITY.lstat()
        ensure(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077,
               "INSECURE_EXISTING_PRIVATE_KEY")
        ensure((DEST / "id_ed25519.pub").is_file(), "CONTROLLER_PUBLIC_KEY_MISSING")
    else:
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                        "-f", str(IDENTITY), "-C", "mira-dc-ops027"],
                       check=True, timeout=15, capture_output=True)
    os.chmod(IDENTITY, 0o600)
    os.chmod(DEST / "id_ed25519.pub", 0o644)
    tmp = DEST / ".known_hosts.tmp"
    tmp.write_text(verified_path.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, KNOWN)
    tmp = DEST / ".target.json.tmp"
    tmp.write_text(json.dumps({"host": host, "port": 22}) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, TARGET)
    print("ALIYUN_REMOTE_TARGET_PINNED=YES")
    print("PRIVATE_KEY_ROOT_ONLY=YES")
    print("SHARE_ONLY_PUBLIC_KEY_FILE=/etc/mira-dc-remote/id_ed25519.pub")
    print("TENANT_SSH_ACCESS_NOT_IMPLIED=YES")


if __name__ == "__main__":
    main()
