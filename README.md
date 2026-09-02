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

- `/status`
- `/malaga`
- `/syncinfo`

`/semana` and `/ultima` currently use the same summary as `/status`; they will
be expanded after the first Railway deployment is working.
# garmin-coach
