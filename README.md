# Garmin Coach

Private Garmin-to-Telegram coaching assistant for marathon training.

## Architecture

- `apps/sync-local`: runs on the Mac, reads Garmin Connect with local tokens, and sends summarized data to the backend.
- `apps/bot`: FastAPI app for Railway. It stores the latest sync and serves Telegram bot commands.
- Railway stays online 24/7, serves operational commands, and queues coaching requests for the Mac using the latest stored data.
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
OLLAMA_MODEL=garmin-coach:9b
GARMIN_COACH_AI_MAX_JOBS=3
OLLAMA_NUM_CTX=32768
OLLAMA_NUM_PREDICT=900
OLLAMA_PLAN_NUM_PREDICT=1400
OLLAMA_TIMEOUT_SECONDS=600
GARMIN_COACH_ANSWER_MAX_CHARS=3200
TELEGRAM_ACTION_INTERVAL_SECONDS=4
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
PIPER_VOICE_MODEL=~/Library/Application Support/Garmin Coach/piper/es_ES-carlfm-x_low.onnx
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
- `/plan_semana` (alias `/plan`)
- `/ultima`
- `/proximo`
- `/fatiga`
- `/salud`
- `/carga`
- `/running` (aliases `/correr`, `/carga_running`)
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
/plan_semana
/fuerza
/fuerza A
/fuerza add sentadilla 60kg 8/8 rir2
/fuerza fin
```

Check-ins are stored in Postgres and used by `/feedback` and `/ajustar`, but only
for pain, soreness, and relevant notes. Sleep, energy, stress, and recovery come
from objective Garmin wellness data: sleep, HRV, readiness, body battery, stress,
resting heart rate, and recent load. Historical subjective RPE, sleep, or energy
scores are ignored by coaching decisions.
`/feedback` aggregates every activity from the latest training day and produces a
combined conclusion using running load, cycling/Wattwise, strength, weekly load,
and Garmin recovery. `/semana` combines the completed-week balance with an
adaptive seven-day plan; `/plan_semana` shows the plan directly. `/fuerza`
provides full-body A/B sessions and can register the active circuit, weights,
repetitions and RIR so strength work is saved separately from Garmin's compact
activity summary. Manual strength logs are converted into a simple muscular-load
score by volume, series, muscle group and effort; `/feedback`, `/carga` and
`/ajustar` use that score when deciding whether to protect the next running
session.
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
All coaching questions now follow one flow: text, `/coach`, coaching commands
(such as `/feedback`, `/semana`, `/ajustar`, and `/fuerza` without arguments),
and transcribed voice enter the same local Ollama analysis. The Mac must be
awake; answers can take several minutes. Operational commands such as `/sync`,
profile/check-in updates, strength logging (`/fuerza A`, `add`, `fin`), and lab
review/application remain immediate and deterministic.

The model receives calculated readings plus every activity in the latest sync
(currently up to 25), weekly aggregates, up to 28 history snapshots including
recovery (keeping the latest snapshot per day to avoid repetition), the athlete profile, applied lab tests, injury check-ins, manual
strength load, and cached and live Wattwise data with source dates. These are
the available summaries, not the full Garmin archive. It is instructed to cross
check evidence, distinguish stale or missing data, and explain a concrete
training recommendation without inventing medical diagnoses. The worker also
adds an explicit date notice when the sync is from a previous day, missing or
future-dated; this does not depend on the model remembering to mention it. Only applied lab
tests may inform confirmed profile values; pending proposals remain in review.

Every coaching request uses one generation with the complete compact context.
The backend supplies calculated evidence and the model crosses sports, recovery,
profile, dates and limitations before returning only the useful conclusion.
Native thinking is disabled to keep latency predictable. Normal questions use
`OLLAMA_NUM_PREDICT`; weekly plans use the larger
`OLLAMA_PLAN_NUM_PREDICT` budget. Both use the configured context window.
The response uses natural Spanish paragraphs with punctuation and normally
100–180 words. Weekly plans have more room to cover every day. Text and voice share the same final
answer: TTS expands units and adds pauses without imposing a shorter answer
limit. Long voice answers also include the full text because Telegram captions
are limited. If Ollama fails or returns an incomplete/invalid answer, a clearly
labelled basic calculated reading is returned. If voice synthesis fails, the
full answer is sent as text.

Telegram confirms the queued request immediately with the expected wait. Once
the Mac claims the job, the worker refreshes Telegram's native `typing` action
every four seconds until processing completes or fails. This interval can be
changed with `TELEGRAM_ACTION_INTERVAL_SECONDS`.

Review the [current validation results](docs/coach-validation.md). Run the
updated local worker after deploying compatible backend changes. Existing `.env` values override the defaults; update previous
short answer limits or timeouts if present. `GARMIN_COACH_VOICE_ANSWER_MAX_CHARS`
is no longer used. A larger context increases local memory use and latency.
These parameters can be adjusted with the environment variables above.
Ollama documents [thinking](https://docs.ollama.com/capabilities/thinking) and
[context/generation limits](https://docs.ollama.com/modelfile).

## P0.3: persisted plan-change proposals

Explicit requests such as `/ajustar mañana` can now produce an audited pending
proposal. Python controls authorization, binds the job to its original plan and
revision, validates the response twice, and persists at most one proposal per job.
Reading the plan or reporting fatigue alone never enables proposals. This phase
does not apply any changes to `planned_sessions`.

See [P0.3 behavior, schema changes and tests](docs/p03-pending-changes.md), including
the effective worker permission, replacement semantics and voice limitation.

## Running load analytics

The running analytics model adapts the normalization, weekly aggregation, ACWR,
readiness-context, and compact AI-context ideas from the MIT-licensed
[`garmin-running-analytics`](https://github.com/mgilangjanuar/garmin-running-analytics)
project to the existing Python sync. The upstream project is a standalone
Next.js dashboard rather than a Python package, so Garmin Coach does not run or
deploy that second application.

For each run, the Mac estimates Banister TRIMP from duration and average heart
rate when the athlete profile has sex, maximum HR, and resting HR. This keeps a
single comparable scale across the history. If TRIMP cannot be calculated, the
sync uses Garmin's `activityTrainingLoad` only and never mixes both scales.
The sync stores running acute load (7 days), weekly chronic load (28 days),
ACWR, monotony, strain, source provenance, and per-activity load. `/running`,
`/carga`, `/fatiga`, and `/feedback` make those values visible. ACWR is treated
as a description of load change, not as a standalone injury predictor.

Method references: [Banister TRIMP](https://journals.physiology.org/doi/abs/10.1152/japplphysiol.00482.2003),
[training monotony and strain](https://pmc.ncbi.nlm.nih.gov/articles/PMC5673663/),
and [ACWR limitations](https://pubmed.ncbi.nlm.nih.gov/32502973/).

No Anthropic or Claude call is used. Deterministic calculations run in Python;
free-text explanation and planning continue through the existing local Ollama
worker and its configured `OLLAMA_MODEL`.

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
