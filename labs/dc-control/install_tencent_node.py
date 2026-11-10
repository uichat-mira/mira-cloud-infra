#!/usr/bin/env python3
"""OPS-027: controlled one-time Tencent node setup, run by root from reviewed source.

Only this bootstrap requires root. The actual Remote DC agent uses miraops'
systemd --user instance, never root or Docker.
"""
from __future__ import annotations

import base64
import grp
import ipaddress
import os
import pwd
import shutil
import stat
import subprocess
from pathlib import Path

RELEASE = Path(os.environ.get("MIRA_DC_RELEASE_DIR", "/root/mira-dc-control-release/labs/dc-control"))
DEST = Path("/opt/mira-dc-remote")
USER = "miraops"


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=180).stdout.strip()


def require_secure_root_path(path: Path) -> None:
    # A root-owned source file inside /tmp is not sufficient: a different
    # user can swap writable ancestor directories before root opens it.
    ensure(path.is_absolute(), "ABSOLUTE_RELEASE_PATH_REQUIRED")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except OSError:
            raise SystemExit("RELEASE_PATH_MISSING") from None
        ensure(info.st_uid == 0 and not (info.st_mode & 0o022),
               "RELEASE_PATH_MUST_BE_ROOT_OWNED_AND_NOT_WRITABLE_BY_OTHERS")
        ensure(stat.S_ISREG(info.st_mode) if item == path else stat.S_ISDIR(info.st_mode),
               "RELEASE_PATH_SYMLINK_OR_WRONG_TYPE")


def main() -> None:
    ensure(os.geteuid() == 0, "ROOT_REQUIRED")
    src = RELEASE / "remote_agent.py"
    require_secure_root_path(src)
    keyfile = Path(os.environ.get("MIRA_DC_CONTROLLER_PUBKEY_FILE", ""))
    ensure(keyfile.is_file() and not keyfile.is_symlink(), "CONTROLLER_PUBLIC_KEY_FILE_REQUIRED")
    try:
        controller_ip = str(ipaddress.IPv4Address(os.environ["MIRA_DC_CONTROLLER_IP"]))
    except (KeyError, ipaddress.AddressValueError):
        raise SystemExit("INVALID_CONTROLLER_IP") from None
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        raise SystemExit("MIRAOPS_USER_MISSING") from None
    ensure(account.pw_uid != 0 and account.pw_dir == "/home/miraops", "MIRAOPS_ACCOUNT_UNEXPECTED")
    group_names = {grp.getgrgid(g).gr_name for g in os.getgrouplist(USER, account.pw_gid)}
    ensure(not group_names.intersection({"sudo", "docker"}), "MIRAOPS_PRIVILEGED_GROUP_REJECTED")
    key = keyfile.read_text(encoding="ascii").strip().split()
    ensure(len(key) in (2, 3) and key[0] == "ssh-ed25519", "SSH_ED25519_PUBLIC_KEY_REQUIRED")
    try:
        ensure(len(base64.b64decode(key[1], validate=True)) >= 32, "INVALID_PUBLIC_KEY")
    except ValueError:
        raise SystemExit("INVALID_PUBLIC_KEY") from None
    paired_file = Path(account.pw_dir) / ".desktop-commander-device" / "device.json"
    ensure(paired_file.is_file(), "EXISTING_PAIRED_DEVICE_REQUIRED")
    ensure(run("/usr/bin/node", "-p", "process.versions.node.split('.')[0]").isdigit(), "NODE_MISSING")
    ensure(int(run("/usr/bin/node", "-p", "process.versions.node.split('.')[0]")) >= 22, "NODE_22_REQUIRED")
    ensure(shutil.which("npm") is not None, "NPM_REQUIRED")

    if DEST.exists() or DEST.is_symlink():
        item = DEST.lstat()
        ensure(stat.S_ISDIR(item.st_mode) and item.st_uid == 0 and not item.st_mode & 0o022,
               "INSECURE_EXISTING_AGENT_INSTALL_DIR")
    else:
        DEST.mkdir(mode=0o755, parents=True)
    os.chown(DEST, 0, 0)
    os.chmod(DEST, 0o755)
    ensure(not (DEST / "remote_agent.py").is_symlink(), "UNSAFE_AGENT_ENTRY_SYMLINK")
    shutil.copyfile(src, DEST / "remote_agent.py")
    os.chown(DEST / "remote_agent.py", 0, 0)
    os.chmod(DEST / "remote_agent.py", 0o644)
    run("/usr/bin/python3", "-m", "py_compile", str(DEST / "remote_agent.py"))
    # Pin to the already observed paired agent version; ignore postinstall scripts.
    run("npm", "install", "--prefix", str(DEST), "--omit=dev", "--ignore-scripts",
        "--no-audit", "--no-fund", "--save-exact", "@wonderwhy-er/desktop-commander@0.3.1")
    installed = run("/usr/bin/node", "-p",
        'require("/opt/mira-dc-remote/node_modules/@wonderwhy-er/desktop-commander/package.json").version')
    ensure(installed == "0.3.1", "PINNED_AGENT_VERSION_MISMATCH")
    for parent, dirs, files in os.walk(DEST):
        os.chown(parent, 0, 0)
        for name in dirs + files:
            item = Path(parent) / name
            if not item.is_symlink():
                os.chown(item, 0, 0)
                os.chmod(item, item.stat().st_mode & ~0o022)

    run("loginctl", "enable-linger", USER)
    run("systemctl", "start", f"user@{account.pw_uid}.service")
    ensure((Path("/run/user") / str(account.pw_uid) / "bus").exists(), "USER_SYSTEMD_BUS_NOT_READY")

    ssh_dir = Path(account.pw_dir) / ".ssh"
    ensure(not ssh_dir.is_symlink(), "UNSAFE_SSH_DIRECTORY")
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    os.chown(ssh_dir, account.pw_uid, account.pw_gid)
    os.chmod(ssh_dir, 0o700)
    authorized = ssh_dir / "authorized_keys"
    ensure(not authorized.is_symlink(), "UNSAFE_AUTHORIZED_KEYS")
    if not authorized.exists():
        authorized.touch(mode=0o600)
    os.chown(authorized, account.pw_uid, account.pw_gid)
    os.chmod(authorized, 0o600)
    pub = " ".join(key[:2])
    entry = (
        f'from="{controller_ip}",restrict,'
        f'command="/usr/bin/python3 /opt/mira-dc-remote/remote_agent.py" '
        f"{pub} mira-dc-ops027"
    )
    prior = authorized.read_text(encoding="utf-8")
    managed = [line for line in prior.splitlines() if "mira-dc-ops027" in line]
    ensure(not managed or managed == [entry], "CONFLICTING_MANAGED_SSH_KEY")
    if not managed:
        with authorized.open("a", encoding="utf-8") as stream:
            if prior and not prior.endswith("\n"):
                stream.write("\n")
            stream.write(entry + "\n")
    print("TENCENT_AGENT_INSTALLED=YES")
    print("FORCED_COMMAND_RESTRICTED=YES")
    print("USER_SYSTEMD_MANAGER_LINGER=YES")
    print("DC_BOOT_AUTOSTART=NO")
    print("EXISTING_INTERACTIVE_DC_UNCHANGED=YES")


if __name__ == "__main__":
    main()
