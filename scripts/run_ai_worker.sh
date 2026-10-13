#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="${GARMIN_COACH_PROJECT_ROOT:-/Users/lloren27/Projects/garmin-coach}"
SYNC_DIR="$PROJECT_ROOT/apps/sync-local"
ENV_FILE="${GARMIN_COACH_ENV_FILE:-$PROJECT_ROOT/.env}"
LOG_DIR="$HOME/Library/Logs"
LOCK_DIR="$HOME/Library/Application Support/Garmin Coach/ai-worker.lock"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$LOCK_DIR")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$STAMP] AI worker already running, skipping"
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

cd "$SYNC_DIR"

echo "[$STAMP] Checking Garmin Coach AI jobs"

if [[ -n "${GARMIN_COACH_PYTHON:-}" ]]; then
  PYTHON_BIN="$GARMIN_COACH_PYTHON"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "[$STAMP] Configured worker Python is missing or not executable: $PYTHON_BIN" >&2
    exit 1
  fi
elif [[ ! -x ".venv/bin/python" ]]; then
  if [[ -x "/opt/homebrew/bin/python3.13" ]]; then
    /opt/homebrew/bin/python3.13 -m venv .venv
  else
    python3 -m venv .venv
  fi
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN=".venv/bin/python"
fi

if ! "$PYTHON_BIN" -c "import garminconnect, httpx, dotenv, faster_whisper, pydantic, pypdf, docx" >/dev/null 2>&1; then
  if [[ -n "${GARMIN_COACH_PYTHON:-}" ]]; then
    echo "[$STAMP] Configured worker Python is missing required dependencies" >&2
    exit 1
  fi
  .venv/bin/python -m pip install -r requirements.txt
fi

PYTHONPATH="$SYNC_DIR${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -c \
  'import runpy, sys; from dotenv import load_dotenv; load_dotenv(sys.argv[1], override=False); runpy.run_module("garmin_sync.ai_worker", run_name="__main__")' \
  "$ENV_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Garmin Coach AI worker finished"
