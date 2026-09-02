# Architecture

## Option 3: Mac sync + Railway bot

```text
Garmin Connect
  -> Mac local sync
  -> Railway API
  -> Telegram bot
```

The Mac owns Garmin authentication. Railway receives only summarized training
data through a shared `SYNC_SECRET`.

## Data policy

- Garmin password is never stored.
- Garmin tokens stay in `~/.garminconnect` on the Mac.
- Raw activity dumps should stay local unless explicitly needed.
- Railway stores latest summarized metrics and selected activity summaries.
