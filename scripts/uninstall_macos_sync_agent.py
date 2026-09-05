#!/usr/bin/env python3
"""Uninstall the macOS LaunchAgent for Garmin Coach sync."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


LABEL = "com.lloren27.garmin-coach.sync"
WATCH_LABEL = "com.lloren27.garmin-coach.sync-watch"
LABELS = (LABEL, WATCH_LABEL)


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def main() -> int:
    domain = f"gui/{os.getuid()}"
    for label in LABELS:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        run(["launchctl", "bootout", domain, str(plist_path)], check=False)
        if plist_path.exists():
            plist_path.unlink()
        print(f"Uninstalled LaunchAgent: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
