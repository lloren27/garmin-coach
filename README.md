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

## 7. Local wattwise-core analytics

`wattwise-core` runs as a separate local Docker service. It is not deployed to
Railway. Garmin Coach will use it from the Mac for cycling analytics once the
integration layer is enabled.

Install and start it:

```bash
./install_wattwise_core.command
```

Defaults:

```text
WATTWISE_API_URL=http://127.0.0.1:8010
WATTWISE_DOCKER_CONTAINER=garmin-coach-wattwise
WATTWISE_DOCKER_VOLUME=garmin_coach_wattwise_data
```

The installer clones the official source into `data/wattwise-core`, builds a
local Docker image, generates local secrets, starts the API, waits for
`/readyz`, mints an access token, and stores the values in `.env`.

Useful checks:

```bash
curl http://127.0.0.1:8010/readyz
docker logs garmin-coach-wattwise
docker stop garmin-coach-wattwise
docker start garmin-coach-wattwise
```

Import recent Garmin activities into wattwise-core:

```bash
scripts/run_wattwise_bridge.sh
```

Bridge defaults:

```text
WATTWISE_BRIDGE_DAYS=60
WATTWISE_BRIDGE_LIMIT=12
WATTWISE_BRIDGE_SPORTS=running,cycling
WATTWISE_BRIDGE_RUNNING_FORMAT=tcx
WATTWISE_BRIDGE_CYCLING_FORMAT=original
WATTWISE_BRIDGE_AFTER_SYNC=1
WATTWISE_AI_CONTEXT=1
WATTWISE_AI_LOOKBACK_DAYS=28
```

The bridge can import both running and cycling into wattwise-core. Running uses
TCX by default because some Garmin FIT exports contain invalid speed sentinel
values that wattwise-core correctly quarantines. Cycling keeps the original FIT
by default because that usually preserves power data for NP, IF, TSS, CP/W',
and W'bal. Garmin Coach's own sync remains the primary source for running pace,
distance, heart rate, and marathon coaching while Wattwise adds deeper cycling
load context.

When `WATTWISE_BRIDGE_AFTER_SYNC=1`, every successful local Garmin sync also
tries to push new eligible activities into wattwise-core. If wattwise-core is
not running, the normal Garmin-to-Railway sync still completes.

When `WATTWISE_AI_CONTEXT=1`, the local Ollama worker adds a compact
wattwise-core summary to natural-language coaching jobs. That gives `/coach`
and free-text Telegram questions access to cycling TSS, IF, VI, and load while
keeping Railway isolated from the local Wattwise service.

After each bridge run, the Mac also publishes a compact Wattwise snapshot to
Railway. The snapshot contains calculated metrics, never Wattwise credentials
or activity files, and remains available while the Mac is asleep. Telegram uses
it in `/bici`, `/feedback`, `/carga`, `/fatiga`, and `/potencia` (`/wattwise` is
an alias). TSS is shown as cycling load, IF as relative intensity, VI as effort
variability, and fitness/fatigue/form as planning context.
The local bridge renews Wattwise's short-lived access token automatically using
`WATTWISE_OWNER_SECRET`; no periodic manual token replacement is needed.

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
- `/prueba_esfuerzo`
- `/pruebas`
- `/ver_prueba`
- `/zonas`
- `/aplicar_prueba`
- `/corregir_prueba`
- `/descartar_prueba`
- `/checkin`
- `/ajustar`
- `/bici`
- `/potencia` (alias `/wattwise`)
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
Adjunta un PDF o DOCX con /prueba_esfuerzo en el comentario del archivo
/zonas
/corregir_prueba fcmax 181 fcreposo 52 vt1 142 vt2 164 vo2max 52.3 ritmo_umbral 4:45
/aplicar_prueba
/descartar_prueba
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
Lab test PDF/DOCX files can be uploaded from Telegram. Add `/prueba_esfuerzo`
as the file caption, then the Mac processes the document locally and stores a
pending proposal. Review it with `/ver_prueba` or `/pruebas`, preview zones with
`/zonas`, correct values with `/corregir_prueba`, discard the pending proposal
with `/descartar_prueba`, and apply it to the athlete profile with
`/aplicar_prueba`.
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
