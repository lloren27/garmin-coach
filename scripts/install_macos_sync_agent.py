#!/usr/bin/env python3
"""Install a macOS LaunchAgent for Garmin Coach sync."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path


PROJECT_ROOT = Path("/Users/lloren27/Projects/garmin-coach")
LABEL = "com.lloren27.garmin-coach.sync"
WATCH_LABEL = "com.lloren27.garmin-coach.sync-watch"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
WATCH_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{WATCH_LABEL}.plist"
RUN_SCRIPT = PROJECT_ROOT / "scripts" / "run_sync.sh"
WATCH_SCRIPT = PROJECT_ROOT / "scripts" / "run_requested_sync.sh"
LOG_DIR = Path.home() / "Library" / "Logs"
OUT_LOG = LOG_DIR / "garmin-coach-sync.out.log"
ERR_LOG = LOG_DIR / "garmin-coach-sync.err.log"
WATCH_OUT_LOG = LOG_DIR / "garmin-coach-sync-watch.out.log"
WATCH_ERR_LOG = LOG_DIR / "garmin-coach-sync-watch.err.log"


def build_plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": ["/bin/zsh", str(RUN_SCRIPT)],
        "RunAtLoad": True,
        "StartInterval": 4 * 60 * 60,
        "StartCalendarInterval": [
            {"Hour": 8, "Minute": 20},
            {"Hour": 8, "Minute": 50},
            {"Hour": 18, "Minute": 30},
            {"Hour": 21, "Minute": 15},
            {"Hour": 21, "Minute": 45},
        ],
        "StandardOutPath": str(OUT_LOG),
        "StandardErrorPath": str(ERR_LOG),
        "WorkingDirectory": str(PROJECT_ROOT),
        "ThrottleInterval": 300,
    }


def build_watch_plist() -> dict:
    return {
        "Label": WATCH_LABEL,
        "ProgramArguments": ["/bin/zsh", str(WATCH_SCRIPT)],
        "RunAtLoad": True,
        "StartInterval": 5 * 60,
        "StandardOutPath": str(WATCH_OUT_LOG),
        "StandardErrorPath": str(WATCH_ERR_LOG),
        "WorkingDirectory": str(PROJECT_ROOT),
        "ThrottleInterval": 300,
    }


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def install_agent(label: str, plist_path: Path, plist: dict, domain: str) -> None:
    with plist_path.open("wb") as file:
        plistlib.dump(plist, file, sort_keys=False)
    plist_path.chmod(0o600)

    target = f"{domain}/{label}"
    run(["launchctl", "bootout", domain, str(plist_path)], check=False)
    run(["launchctl", "bootstrap", domain, str(plist_path)])
    run(["launchctl", "enable", target], check=False)


def main() -> int:
    if not RUN_SCRIPT.exists():
        raise SystemExit(f"Missing sync script: {RUN_SCRIPT}")
    if not WATCH_SCRIPT.exists():
        raise SystemExit(f"Missing sync watch script: {WATCH_SCRIPT}")

    RUN_SCRIPT.chmod(0o700)
    WATCH_SCRIPT.chmod(0o700)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    uid = os.getuid()
    domain = f"gui/{uid}"
    install_agent(LABEL, PLIST_PATH, build_plist(), domain)
    install_agent(WATCH_LABEL, WATCH_PLIST_PATH, build_watch_plist(), domain)

    print(f"Installed LaunchAgent: {PLIST_PATH}")
    print(f"Installed LaunchAgent: {WATCH_PLIST_PATH}")
    print(f"Label: {LABEL}")
    print(f"Label: {WATCH_LABEL}")
    print(f"stdout log: {OUT_LOG}")
    print(f"stderr log: {ERR_LOG}")
    print(f"watch stdout log: {WATCH_OUT_LOG}")
    print(f"watch stderr log: {WATCH_ERR_LOG}")
    print("Schedule: login/start, every 4 hours while awake, 08:20, 08:50, 18:30, 21:15, 21:45.")
    print("Watch: every 5 minutes while awake; runs sync if /sync was requested or data is older than 30 minutes.")
    print("Run scripts/run_sync.sh for an immediate manual sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
