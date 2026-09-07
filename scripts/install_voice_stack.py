#!/usr/bin/env python3
"""Install local voice dependencies for Garmin Coach."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC_DIR = ROOT / "apps" / "sync-local"
VENV = SYNC_DIR / ".venv"
ENV_FILE = ROOT / ".env"
VOICE_DIR = Path.home() / "Library" / "Application Support" / "Garmin Coach" / "piper"
PIPER_MODEL = VOICE_DIR / "es_ES-mls_10246-low.onnx"
PIPER_CONFIG = VOICE_DIR / "es_ES-mls_10246-low.onnx.json"
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/mls_10246/low"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def ensure_venv() -> None:
    if VENV.exists():
        return
    python = "/opt/homebrew/bin/python3.13" if Path("/opt/homebrew/bin/python3.13").exists() else sys.executable
    run([python, "-m", "venv", str(VENV)])


def ensure_python_deps() -> None:
    run([str(VENV / "bin" / "python"), "-m", "pip", "install", "-U", "pip"])
    run([str(VENV / "bin" / "python"), "-m", "pip", "install", "-r", "requirements.txt"], cwd=SYNC_DIR)


def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    brew = shutil.which("brew")
    if not brew:
        print("ffmpeg not found and Homebrew is not available. Install ffmpeg manually.")
        return "ffmpeg"
    try:
        run([brew, "install", "ffmpeg"])
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg install failed ({exc.returncode}). Trying imageio-ffmpeg from the local venv.")
        return ensure_python_ffmpeg()
    return shutil.which("ffmpeg") or "ffmpeg"


def ensure_python_ffmpeg() -> str:
    try:
        output = subprocess.check_output(
            [
                str(VENV / "bin" / "python"),
                "-c",
                "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())",
            ],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return "ffmpeg"
    return output or "ffmpeg"


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return
    print(f"Downloading {destination.name}")
    urllib.request.urlretrieve(url, destination)


def ensure_piper_voice() -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    download(f"{HF_BASE}/{PIPER_MODEL.name}", PIPER_MODEL)
    download(f"{HF_BASE}/{PIPER_CONFIG.name}", PIPER_CONFIG)


def load_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def save_env(path: Path, updates: dict[str, str]) -> None:
    lines, existing = load_env(path)
    seen = set()
    new_lines = []
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    missing = [key for key in updates if key not in seen and not existing.get(key)]
    if missing and new_lines and new_lines[-1].strip():
        new_lines.append("")
    for key in missing:
        new_lines.append(f"{key}={updates[key]}")
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def smoke_test_piper() -> None:
    piper = VENV / "bin" / "piper"
    if not piper.exists():
        print("Piper CLI not found in the venv. Voice output will fall back to text.")
        return
    output = VOICE_DIR / "voice-test.wav"
    command = [str(piper), "--model", str(PIPER_MODEL), "--output_file", str(output)]
    print("+ " + " ".join(command))
    subprocess.run(
        command,
        input="Garmin Coach preparado para responder por voz.",
        text=True,
        cwd=ROOT,
        check=True,
        timeout=60,
    )
    print("Prueba de voz local generada en:")
    print(output)


def main() -> int:
    ensure_venv()
    ensure_python_deps()
    ffmpeg = ensure_ffmpeg()
    ensure_piper_voice()
    piper = VENV / "bin" / "piper"
    save_env(
        ENV_FILE,
        {
            "WHISPER_MODEL": os.getenv("WHISPER_MODEL", "small"),
            "WHISPER_DEVICE": os.getenv("WHISPER_DEVICE", "auto"),
            "WHISPER_COMPUTE_TYPE": os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            "PIPER_BIN": str(piper),
            "PIPER_VOICE_MODEL": str(PIPER_MODEL),
            "PIPER_LENGTH_SCALE": os.getenv("PIPER_LENGTH_SCALE", "1.12"),
            "PIPER_NOISE_SCALE": os.getenv("PIPER_NOISE_SCALE", "0.45"),
            "PIPER_NOISE_W_SCALE": os.getenv("PIPER_NOISE_W_SCALE", "0.55"),
            "PIPER_SENTENCE_SILENCE": os.getenv("PIPER_SENTENCE_SILENCE", "0.25"),
            "PIPER_VOLUME": os.getenv("PIPER_VOLUME", "1.0"),
            "FFMPEG_BIN": ffmpeg,
        },
    )
    smoke_test_piper()
    print("Voice stack ready. Restart or reinstall the LaunchAgent if the worker was already running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
