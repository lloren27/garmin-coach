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

## 3b. Automate Mac sync

Install the macOS LaunchAgent:

```bash
./configure_macos_sync.command
```

It runs:

- when your user session starts, including after starting the Mac and logging in;
- every 4 hours while the Mac is awake;
- at 08:20 and 08:50, after the usual morning session;
- at 18:30, 21:15, and 21:45, around the usual evening training window.

If the MacBook is asleep with the lid closed, sync does not run during deep
sleep. It will catch up when the user session starts or at the next interval
while the Mac is awake.

Immediate manual sync:

```bash
scripts/run_sync.sh
```

Logs:

```text
~/Library/Logs/garmin-coach-sync.out.log
~/Library/Logs/garmin-coach-sync.err.log
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

## Telegram commands

- `/hoy`
- `/semana`
- `/ultima`
- `/proximo`
- `/fatiga`
- `/carga`
- `/tendencia`
- `/feedback`
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
/perfil sexo hombre edad 44 altura 176 peso 72 fcmax 178 fcreposo 52 fcumbral 162 ftp 230 ritmo_umbral 4:50 objetivo_maraton 3:40 marca_maraton 3:40
/perfil peso 71.5 ftp 235
/checkin rpe 6 sueno 7 energia 6 sin molestias nota piernas algo cargadas
/checkin rpe 8 sueno 4 energia 3 molestia gemelo
/ajustar
/ajustar hoy estoy cansado y dormi mal
```

Check-ins are stored in Postgres and used by `/feedback` and `/ajustar`.
The athlete profile is stored in Postgres and used by `/feedback`, `/bici`,
`/carga`, `/ajustar`, and `/malaga`.

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
