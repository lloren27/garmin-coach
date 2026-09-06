#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/lloren27/Projects/garmin-coach"
SYNC_DIR="$PROJECT_ROOT/apps/sync-local"
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

if [[ ! -x ".venv/bin/python" ]]; then
  if [[ -x "/opt/homebrew/bin/python3.13" ]]; then
    /opt/homebrew/bin/python3.13 -m venv .venv
  else
    python3 -m venv .venv
  fi
fi

if ! .venv/bin/python -c "import garminconnect, httpx, dotenv" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi

.venv/bin/python -m garmin_sync.ai_worker

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Garmin Coach AI worker finished"
