# Scripts

Utility scripts for local project setup.

- `configure_local_env.py`: prompts for Telegram secrets in Terminal, validates
  the bot, discovers your Telegram user id, and writes `.env`.
- `install_macos_sync_agent.py`: installs the scheduled sync agent and the
  5-minute watcher that picks up Telegram `/sync` requests.
- `run_sync.sh`: runs a full local Garmin sync immediately.
- `run_requested_sync.sh`: checks Railway for pending or stale sync state and
  runs a full sync only when needed.
- `run_ai_worker.sh`: checks Railway for natural-language jobs and processes
  them locally with Ollama.
- `install_wattwise_core.py`: clones, builds, and starts wattwise-core locally
  with Docker on `127.0.0.1:8010`, storing local secrets in `.env`.
- `run_wattwise_bridge.sh`: downloads recent Garmin activities, using TCX for
  running and FIT originals for cycling by default, imports them into local
  wattwise-core, and stores import state in ignored local data. The main Garmin
  sync runs this bridge automatically when `WATTWISE_BRIDGE_AFTER_SYNC=1`.
