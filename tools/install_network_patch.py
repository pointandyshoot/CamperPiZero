#!/usr/bin/env python3
"""Update an existing HomeAssist-Camper network controller, preserving secrets."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"controller.py": Path("/usr/local/lib/camper-ha/controller.py"),
           "camper-network.service": Path("/etc/systemd/system/camper-network.service"),
           "network.json": Path("/etc/camper-ha/network.json")}


def run(*args):
    subprocess.run(args, check=True, capture_output=True, timeout=420)


def atomic_copy(source, target, mode):
    fd, temporary = tempfile.mkstemp(prefix=".camper-patch-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore(backup):
    for name, target in TARGETS.items():
        atomic_copy(backup / name, target, 0o755 if name == "controller.py" else 0o600 if name == "network.json" else 0o644)
    run("systemctl", "daemon-reload")
    run("systemctl", "restart", "camper-network.service")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate existing setup without changing it")
    parser.add_argument("--rollback", type=Path, help="Restore the private backup directory printed by installation")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")
    if args.rollback:
        if not all((args.rollback / name).is_file() for name in TARGETS):
            raise SystemExit("Incomplete backup directory")
        restore(args.rollback)
        print("Previous controller/config restored and service restarted", flush=True)
        return
    if not all(path.is_file() for path in TARGETS.values()):
        raise SystemExit("Expected existing camper network installation is missing; no changes made")
    spec = importlib.util.spec_from_file_location("network_patch_controller", ROOT / "networking/controller.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Parse and validate locally without displaying any credentials.
    config = module.read_config(TARGETS["network.json"])
    for executable in ("nmcli", "busctl", "arping"):
        if not shutil.which(executable):
            raise SystemExit(f"Required existing executable missing: {executable}; no changes made")
    for profile in (module.AP, module.STA):
        run("nmcli", "-g", "connection.uuid", "connection", "show", "uuid", profile)
    if args.check:
        print("Existing configuration, profiles and tools validated; no changes made", flush=True)
        return
    config.update(scan_interval=60, probe_interval=180, maximum_backoff=600)
    backup = Path("/var/backups/camper-network") / str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    for name, target in TARGETS.items():
        shutil.copy2(target, backup / name)
        os.chmod(backup / name, 0o600)
    print(f"Private rollback backup: {backup}", flush=True)
    try:
        # Launch installer through systemd-run so SSH loss cannot interrupt it.
        run("systemctl", "stop", "camper-network.service")
        atomic_copy(ROOT / "networking/controller.py", TARGETS["controller.py"], 0o755)
        atomic_copy(ROOT / "networking/camper-network.service", TARGETS["camper-network.service"], 0o644)
        fd, temporary = tempfile.mkstemp(dir=backup, prefix="new-config-")
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        try:
            atomic_copy(Path(temporary), TARGETS["network.json"], 0o600)
        finally:
            Path(temporary).unlink()
        run("systemctl", "daemon-reload")
        run("systemctl", "start", "camper-network.service")
        run("systemctl", "is-active", "--quiet", "camper-network.service")
        print("Network patch installed; controller is active", flush=True)
    except Exception:
        print("Patch activation failed; restoring the previous setup", flush=True)
        restore(backup)
        raise SystemExit("Previous setup restored; inspect controller journal")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit("Network patch failed; inspect service status. Secret values suppressed.")
