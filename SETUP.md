# Exam Slot Alert – setup (about 15 minutes, no coding)

The bot checks the Berlin VHS site about every 15 minutes for **"Sprachtest zur Einbürgerung"**, from **1 Dec 2026 to 31 Jan 2027**, in all districts. It sends you a Telegram message when:

- 🟢 an exam in that period shows **free places**, or
- 🆕 a **new exam date** in that period is published, even when it's already full (you can still join the waitlist).

It runs on GitHub's servers, so your laptop can stay off. **It only alerts you. You book the seat yourself on the VHS site.**

---

## Step 1 – Get your Telegram chat ID

1. In Telegram, open your bot and send it any message, e.g. `hi`.
2. In your browser, open this address. Replace `<TOKEN>` with your bot token:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789` and copy that number. This is your **chat ID**.
   (If the page shows `"result":[]`, send the bot another message and reload.)

## Step 2 – Create the GitHub repository

1. Sign in at github.com and click **New repository**.
2. Name: `vhs-slot-alert`. Choose **Public**, which gives free unlimited run time. Your token stays hidden either way (see Step 3).
   If you choose **Private**, open `.github/workflows/exam-alert.yml` later and change `*/15` to `*/30`.
3. Click **Create repository**.

## Step 3 – Add your two secrets

In the repository, go to **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | the number from Step 1 |

## Step 4 – Upload the files

1. In the repository, click **Add file → Upload files**.
2. Drag in `check_slots.py`, then click **Commit changes**.
3. Add the workflow. Click **Add file → Create new file**, type the name exactly:
   `.github/workflows/exam-alert.yml`
   Paste in the contents of the `exam-alert.yml` file, then click **Commit changes**.
   (Do it this way because uploading by drag-and-drop often drops the hidden `.github` folder.)

## Step 5 – Test it

1. Open the **Actions** tab. If GitHub asks, click **"I understand… enable workflows"**.
2. Click **Exam slot alert** on the left, then **Run workflow**.
3. After about 1 minute you should get a Telegram message: *"🤖 Exam-slot bot is running"* with the current list.

From then on it runs by itself. Normally you'll only hear from it when something changes.

---

## Changing things later

Edit `.github/workflows/exam-alert.yml` on GitHub (pencil icon):

- **Date range:** change `WINDOW_START` / `WINDOW_END` (format `YYYY-MM-DD`).
- **How often:** change the `cron` line (`*/15` = every 15 min, `*/30` = every 30 min).
- **Stop the bot:** Actions tab → Exam slot alert → "…" menu → **Disable workflow**.

## Good to know

- **Registration deadline:** it closes **3 weeks before** each exam date. A free seat after that date can't be booked.
- If the bot can't read the VHS website 3 times in a row, it sends you a ⚠️ warning. This usually means the site changed.
- GitHub can delay scheduled runs by a few minutes when it's busy.
