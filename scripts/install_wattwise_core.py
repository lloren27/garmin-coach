#!/usr/bin/env python3
"""Install wattwise-core locally for Garmin Coach."""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import subprocess
import time
import http.client
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
SOURCE_DIR = ROOT / "data" / "wattwise-core"
REPO_URL = "https://github.com/bepcyc/wattwise-core.git"
IMAGE = "garmin-coach-wattwise:local"
CONTAINER = "garmin-coach-wattwise"
VOLUME = "garmin_coach_wattwise_data"
PORT = os.getenv("WATTWISE_PORT", "8010")
BASE_URL = f"http://127.0.0.1:{PORT}"


def run(command: list[str], cwd: Path | None = None, display: list[str] | None = None) -> None:
    print("+ " + " ".join(display or command))
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def update_env(path: Path, updates: dict[str, str]) -> None:
    seen: set[str] = set()
    lines = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    seen.add(key)
                    continue
            lines.append(line)
    if lines and lines[-1].strip():
        lines.append("")
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def ensure_tools() -> None:
    for binary in ("git", "docker"):
        if not shutil.which(binary):
            raise SystemExit(f"Falta {binary}. Instalalo antes de continuar.")


def ensure_source() -> None:
    SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if (SOURCE_DIR / ".git").exists():
        run(["git", "pull", "--ff-only"], cwd=SOURCE_DIR)
        return
    run(["git", "clone", "--depth", "1", REPO_URL, str(SOURCE_DIR)])


def ensure_image() -> None:
    run(["docker", "build", "-t", IMAGE, "."], cwd=SOURCE_DIR)


def stop_existing_container() -> None:
    existing = capture(["docker", "ps", "-aq", "--filter", f"name=^{CONTAINER}$"])
    if existing:
        run(["docker", "rm", "-f", CONTAINER])


def start_container(values: dict[str, str]) -> None:
    env_args = [
        "-e",
        "WATTWISE_DATABASE_DSN=sqlite+aiosqlite:////var/lib/wattwise/wattwise.sqlite",
        "-e",
        f"WATTWISE_ENCRYPTION_ROOT_KEY={values['WATTWISE_ENCRYPTION_ROOT_KEY']}",
        "-e",
        f"WATTWISE_TOKEN_SIGNING_KEY={values['WATTWISE_OWNER_SECRET']}",
    ]
    if values.get("WATTWISE_LLM_API_KEY"):
        env_args.extend(["-e", f"WATTWISE_LLM_API_KEY={values['WATTWISE_LLM_API_KEY']}"])
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-p",
        f"127.0.0.1:{PORT}:8000",
        "-v",
        f"{VOLUME}:/var/lib/wattwise",
        *env_args,
        IMAGE,
    ]
    display = [
        part
        if not part.startswith(("WATTWISE_ENCRYPTION_ROOT_KEY=", "WATTWISE_TOKEN_SIGNING_KEY=", "WATTWISE_LLM_API_KEY="))
        else part.split("=", 1)[0] + "=<hidden>"
        for part in command
    ]
    run(command, display=display)


def wait_ready() -> None:
    url = f"{BASE_URL}/readyz"
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = response.read().decode("utf-8")
            data = json.loads(payload)
            if data.get("status") in {"ready", "ok"}:
                print(payload)
                return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, http.client.RemoteDisconnected):
            pass
        time.sleep(2)
    raise SystemExit("wattwise-core no llego a readyz. Revisa docker logs garmin-coach-wattwise")


def mint_token(owner_secret: str) -> str:
    request = urllib.request.Request(
        f"{BASE_URL}/v1/auth/token",
        data=json.dumps({"owner_secret": owner_secret}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["access_token"])


def main() -> int:
    ensure_tools()
    values = load_env(ENV_FILE)
    values["WATTWISE_API_URL"] = values.get("WATTWISE_API_URL") or BASE_URL
    values["WATTWISE_OWNER_SECRET"] = values.get("WATTWISE_OWNER_SECRET") or secrets.token_hex(32)
    values["WATTWISE_ENCRYPTION_ROOT_KEY"] = values.get("WATTWISE_ENCRYPTION_ROOT_KEY") or base64.b64encode(
        secrets.token_bytes(32)
    ).decode()
    values["WATTWISE_DOCKER_IMAGE"] = IMAGE
    values["WATTWISE_DOCKER_CONTAINER"] = CONTAINER
    values["WATTWISE_DOCKER_VOLUME"] = VOLUME

    ensure_source()
    ensure_image()
    stop_existing_container()
    start_container(values)
    wait_ready()
    values["WATTWISE_ACCESS_TOKEN"] = mint_token(values["WATTWISE_OWNER_SECRET"])
    update_env(
        ENV_FILE,
        {
            "WATTWISE_API_URL": values["WATTWISE_API_URL"],
            "WATTWISE_OWNER_SECRET": values["WATTWISE_OWNER_SECRET"],
            "WATTWISE_ENCRYPTION_ROOT_KEY": values["WATTWISE_ENCRYPTION_ROOT_KEY"],
            "WATTWISE_ACCESS_TOKEN": values["WATTWISE_ACCESS_TOKEN"],
            "WATTWISE_DOCKER_IMAGE": IMAGE,
            "WATTWISE_DOCKER_CONTAINER": CONTAINER,
            "WATTWISE_DOCKER_VOLUME": VOLUME,
        },
    )
    print()
    print(f"wattwise-core listo en {BASE_URL}")
    print(f"Contenedor: {CONTAINER}")
    print(f"Fuente local: {SOURCE_DIR}")
    print("Variables guardadas en .env con permisos 600")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
