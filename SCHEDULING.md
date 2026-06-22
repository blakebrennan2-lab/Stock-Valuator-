# Telegram delivery & every-2-days scheduling

## 1. Telegram credentials (one-time)

1. In Telegram, open **@BotFather** → send `/newbot` → pick a name + username →
   copy the **bot token** (treat it like a password).
2. Send your new bot any message (e.g. "hi"), then message **@userinfobot** →
   it replies with your **chat id** (a number).
3. Add both to `.env` (already git-ignored):

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token
   TELEGRAM_CHAT_ID=123456789
   ```

Test delivery without re-scanning (uses the latest `output/scan_*.csv`):

```
python3 run_notify.py --dry-run   # print the message, don't send
python3 run_notify.py             # actually send to Telegram
```

## 2. Run the full pipeline manually

```
python3 run_pipeline.py           # scan -> output/scan_<date>.csv -> Telegram
```

First run pulls all ~396 names from Yahoo (~10-12 min, polite delay + retry).
Subsequent runs within 24h are near-instant (yfinance cache in `cache/`).

## 3. Schedule it every 2 days (macOS launchd)

```
./scripts/install_schedule.sh     # load the job (every 172800s = 2 days)
launchctl list | grep stock-valuator   # verify it's loaded
./scripts/run_pipeline.sh         # optional: run once now to test end-to-end
./scripts/uninstall_schedule.sh   # remove the job
```

Logs: `output/schedule.log`, `output/launchd.out.log`, `output/launchd.err.log`.

Notes:
- `StartInterval` counts from when the job is loaded / last ran; it's a true
  48-hour cadence rather than a fixed clock time. Edit the plist's
  `StartInterval` to change cadence, or swap to `StartCalendarInterval` for a
  fixed time of day.
- The Mac must be awake (not shut down) for a scheduled run to fire; launchd
  will run a missed job shortly after wake.
