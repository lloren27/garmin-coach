#!/usr/bin/env python3
"""Install a macOS LaunchAgent for Garmin Coach sync."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path


PROJECT_ROOT = Path("/Users/lloren27/Projects/garmin-coach")
LABEL = "com.lloren27.garmin-coach.sync"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
RUN_SCRIPT = PROJECT_ROOT / "scripts" / "run_sync.sh"
LOG_DIR = Path.home() / "Library" / "Logs"
OUT_LOG = LOG_DIR / "garmin-coach-sync.out.log"
ERR_LOG = LOG_DIR / "garmin-coach-sync.err.log"


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


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def main() -> int:
    if not RUN_SCRIPT.exists():
        raise SystemExit(f"Missing sync script: {RUN_SCRIPT}")

    RUN_SCRIPT.chmod(0o700)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    with PLIST_PATH.open("wb") as file:
        plistlib.dump(build_plist(), file, sort_keys=False)
    PLIST_PATH.chmod(0o600)

    uid = os.getuid()
    domain = f"gui/{uid}"
    target = f"{domain}/{LABEL}"

    run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
    run(["launchctl", "bootstrap", domain, str(PLIST_PATH)])
    run(["launchctl", "enable", target], check=False)

    print(f"Installed LaunchAgent: {PLIST_PATH}")
    print(f"Label: {LABEL}")
    print(f"stdout log: {OUT_LOG}")
    print(f"stderr log: {ERR_LOG}")
    print("Schedule: login/start, every 4 hours while awake, 08:20, 08:50, 18:30, 21:15, 21:45.")
    print("Run scripts/run_sync.sh for an immediate manual sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
