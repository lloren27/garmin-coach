#!/bin/zsh
set -e

cd "$(dirname "$0")"
apps/sync-local/.venv/bin/python scripts/configure_strava.py

echo
echo "Pulsa Enter para cerrar esta ventana."
read
