#!/bin/zsh
set -e

cd "$(dirname "$0")"
python3 scripts/install_macos_sync_agent.py

echo
echo "Pulsa Enter para cerrar esta ventana."
read
