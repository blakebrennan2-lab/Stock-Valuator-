# Deploy the web app (all-GitHub, free) — step by step

You'll do this once (~10 min). The result: a 24/7 website you add to your iPhone
home screen, refreshed automatically every 2 days, with Telegram alerts intact.

> Your real secrets stay OUT of GitHub's code. The file `.env` (your tokens) is
> git-ignored and never uploaded. Secrets go in **GitHub Actions Secrets**
> instead (Step 4). The public site only contains `docs/results.json` (stock
> analysis — no secrets).

## 1. Make a free GitHub account
Go to https://github.com → **Sign up**.

## 2. Create a repository
- Top-right **+** → **New repository**.
- Name: `stock-valuator` · Visibility: **Public** · don't add anything else →
  **Create repository**.

## 3. Upload the project
Easiest (no terminal): install **GitHub Desktop** (https://desktop.github.com),
sign in, **File → Add Local Repository** → choose this folder
(`/Users/blakebrennan/Desktop/Stock-Valuator`) → **Publish** to the repo you made.

Or with the terminal, from the project folder:
```
git init
git add .
git commit -m "Stock valuator + web app"
git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/stock-valuator.git
git push -u origin main
```
(Check first that `.env` is NOT listed by `git status` — it should be ignored.)

## 4. Add your secrets
Repo → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**, add these (names exactly):
- `TELEGRAM_BOT_TOKEN` — your BotFather token
- `TELEGRAM_CHAT_ID` — your chat id
- `FMP_API_KEY` — optional (the app uses yfinance by default)

## 5. Run the scan once (and confirm it works)
Repo → **Actions** tab → if prompted, click **"I understand… enable workflows"**
→ pick **"Scan and refresh"** → **Run workflow**. It takes ~15 min, sends your
Telegram digest, and commits an updated `docs/results.json`.

## 6. Turn on the website (GitHub Pages)
Repo → **Settings** → **Pages** → **Source: Deploy from a branch** →
Branch **main**, folder **/docs** → **Save**. After ~1 minute your site is live at:
```
https://<YOUR-USERNAME>.github.io/stock-valuator/
```

## 7. Add to your iPhone home screen
Open that URL in **Safari** → tap **Share** → **Add to Home Screen** → **Add**.
Opens full-screen like an app, anytime, 24/7.

---

### How it runs after this
- **Every 2 days** GitHub runs the scan, sends Telegram, and refreshes the site
  data. (GitHub cron can fire a little late — that's normal.)
- The website is always up; it just shows the latest refreshed data.
- The scheduled workflow stays enabled as long as the repo sees activity — and it
  commits data every run, so it keeps itself alive.

### To change the screen later
Edit `config/profile.py` (thresholds) or `config/exclusions.py` (blacklist),
commit/push, and the next run uses it.

### Your Mac's launchd job
You can keep it or remove it (`./scripts/uninstall_schedule.sh`). With the cloud
run live, the Mac job is redundant — turn it off to avoid double Telegram alerts.
