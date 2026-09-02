#!/usr/bin/env python3
"""Uninstall the macOS LaunchAgent for Garmin Coach sync."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


LABEL = "com.lloren27.garmin-coach.sync"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def main() -> int:
    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"Uninstalled LaunchAgent: {LABEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
