# Garmin Coach

Private Garmin-to-Telegram coaching assistant for marathon training.

## Architecture

- `apps/sync-local`: runs on the Mac, reads Garmin Connect with local tokens, and sends summarized data to the backend.
- `apps/bot`: FastAPI app for Railway. It stores the latest sync and serves Telegram bot commands.
- Railway stays online 24/7 and answers with the latest data it has.
- Garmin credentials and Garmin tokens stay on the Mac.

```text
Garmin Connect -> Mac sync-local -> Railway API -> Telegram bot
```

## 1. Configure local secrets

Do not paste secrets into chat. Run:

```bash
./configure_local_env.command
```

The script asks for the BotFather token in Terminal, verifies the bot with
Telegram, generates `SYNC_SECRET`, and tries to discover your Telegram user id
after you send `/start` to the bot.

## 2. Run the backend locally

```bash
cd apps/bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 3. Run a local Garmin sync

```bash
cd apps/sync-local
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m garmin_sync.sync
```

The sync reads `~/.garminconnect` by default and posts summarized data to
`GARMIN_COACH_API_URL`.
Each successful sync updates the latest state and appends one compact snapshot
to history when Postgres is enabled.
The payload includes activities plus Garmin wellness and physiology signals that
can affect training: resting heart rate, calories, sleep, HRV, body battery,
stress, respiration, SpO2, intensity minutes, body composition, training status,
race predictions, lactate threshold, FTP, endurance score, and hill score when
available for the account/device.

## 3b. Automate Mac sync

Install the macOS LaunchAgent:

```bash
./configure_macos_sync.command
```

It runs:

- when your user session starts, including after starting the Mac and logging in;
- every 4 hours while the Mac is awake;
- at 08:20 and 08:50 Spain time, after the usual morning session;
- at 18:30, 21:15, and 21:45 Spain time, around the usual evening training window.
- every 5 minutes it checks whether Telegram requested a sync or whether the
  latest data is older than 30 minutes.
- every minute it checks whether Telegram has natural-language jobs for the
  local Ollama coach.

If the MacBook is asleep with the lid closed, sync does not run during deep
sleep. It will catch up after the Mac wakes, while the user session is active,
through the 5-minute watcher.

Telegram responses display dates as Spain time using `dd/mm/yyyy` and
`dd/mm/yyyy hh:mm` for synchronization timestamps.

Immediate manual sync:

```bash
scripts/run_sync.sh
```

Logs:

```text
~/Library/Logs/garmin-coach-sync.out.log
~/Library/Logs/garmin-coach-sync.err.log
~/Library/Logs/garmin-coach-sync-watch.out.log
~/Library/Logs/garmin-coach-sync-watch.err.log
~/Library/Logs/garmin-coach-ai-worker.out.log
~/Library/Logs/garmin-coach-ai-worker.err.log
```

Uninstall:

```bash
python3 scripts/uninstall_macos_sync_agent.py
```

## 4. Deploy bot API to Railway

The root `Dockerfile` deploys `apps/bot`.

Set these Railway variables:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_ALLOWED_USER_ID
SYNC_SECRET
PUBLIC_BASE_URL
DATABASE_URL
```

Keep the same `SYNC_SECRET` locally and in Railway.
`DATABASE_URL` is provided automatically if you add a Railway Postgres database.
Without Postgres, Railway stores the latest sync in the service filesystem, which
can be lost on redeploys.

## 5. Register Telegram webhook

After Railway gives you the public HTTPS URL, set `PUBLIC_BASE_URL` in `.env`,
then run:

```bash
python3 scripts/set_telegram_webhook.py
```

## 6. Local Ollama coach

The Railway bot does not call paid LLM APIs for natural-language coaching. It
stores a pending job, and the Mac processes it locally with Ollama.

Defaults:

```text
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:2b
GARMIN_COACH_AI_MAX_JOBS=3
```

Voice messages are also processed locally on the Mac. Railway only queues the
Telegram `file_id`; the Mac downloads the audio, transcribes it with
`faster-whisper`, asks the local coach, and returns a Piper voice response when
the Piper model is configured. If Piper is not available, the answer falls back
to text.

Install the local voice stack:

```bash
./install_voice_stack.command
```

Voice defaults:

```text
WHISPER_MODEL=small
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=int8
PIPER_BIN=/Users/lloren27/Projects/garmin-coach/apps/sync-local/.venv/bin/piper
PIPER_VOICE_MODEL=~/Library/Application Support/Garmin Coach/piper/es_ES-mls_10246-low.onnx
FFMPEG_BIN=ffmpeg
```

If Homebrew cannot install `ffmpeg`, the installer falls back to the
`imageio-ffmpeg` binary inside the local sync virtualenv.

Check Ollama:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

Run the worker manually:

```bash
scripts/run_ai_worker.sh
```

## Telegram commands

- `/hoy`
- `/semana`
- `/ultima`
- `/proximo`
- `/fatiga`
- `/salud`
- `/carga`
- `/tendencia`
- `/feedback`
- `/coach`
- `/sync`
- `/perfil`
- `/checkin`
- `/ajustar`
- `/bici`
- `/fuerza`
- `/status`
- `/malaga`
- `/syncinfo`

The bot stores compact summaries only: recent activities, current week, sport
breakdowns, fatigue estimate, next-workout suggestion, and selected wellness
signals. Garmin tokens and passwords stay local on the Mac.

Examples:

```text
/feedback
/coach que hago manana si estoy cansado?
/manda una nota de voz con una pregunta de entrenamiento
/sync
/salud
/perfil sexo hombre edad 44 altura 176 peso 72 fcmax 178 fcreposo 52 fcumbral 162 ftp 230 ritmo_umbral 4:50 objetivo_maraton 3:40 marca_maraton 3:40
/perfil peso 71.5 ftp 235
/checkin sin molestias nota piernas normales
/checkin molestia gemelo derecho nota aparece al subir ritmo
/ajustar
/ajustar hoy estoy cansado y dormi mal
```

Check-ins are stored in Postgres and used by `/feedback` and `/ajustar`.
Recovery decisions prioritize objective Garmin wellness data when available:
sleep, HRV, readiness, body battery, stress, resting heart rate, and recent load.
Check-ins are treated as subjective context, with pain and injury signals getting
strong priority because Garmin cannot reliably detect them.
The athlete profile is stored in Postgres and used by `/feedback`, `/bici`,
`/carga`, `/ajustar`, and `/malaga`.
`/sync` requests a Garmin sync from Telegram. The Railway bot stores the request,
and the local Mac watcher executes it while the Mac is awake.
`/coach` and natural-language messages create a local AI job processed by Ollama
on the Mac. Commands stay deterministic and do not need AI.
Common natural-language training questions are answered immediately with
deterministic coach readings before falling back to Ollama. This keeps answers
short, Spanish, and grounded in the computed Garmin data.

Useful `/perfil` fields:

- `sexo`: hombre, mujer, otro.
- `edad`: years.
- `altura`: centimeters or meters, for example `176` or `1.76`.
- `peso`: kilograms.
- `fcmax`: maximum heart rate.
- `fcreposo`: resting heart rate.
- `fcumbral`: threshold heart rate, if known.
- `ftp`: cycling functional threshold power in watts.
- `ritmo_umbral`: running threshold pace, for example `4:50`.
- `objetivo_maraton`: marathon goal time, for example `3:40`.
- `marca_maraton`: marathon personal best, for example `3:40`.
- `nota`: free profile note.
# garmin-coach
