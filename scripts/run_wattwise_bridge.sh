#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/lloren27/Projects/garmin-coach"
SYNC_DIR="$PROJECT_ROOT/apps/sync-local"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

cd "$SYNC_DIR"

echo "[$STAMP] Starting Garmin -> wattwise-core bridge"

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

.venv/bin/python -m garmin_sync.wattwise_bridge

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Garmin -> wattwise-core bridge finished"
