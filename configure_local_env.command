#!/bin/zsh
set -e

cd "$(dirname "$0")"
python3 scripts/configure_local_env.py

echo
echo "Pulsa Enter para cerrar esta ventana."
read
