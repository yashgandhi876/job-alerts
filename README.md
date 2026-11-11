# Job alerts to Telegram / WhatsApp

Checks job sources every 10 minutes and sends new **Java + Spring Boot** roles
(Pune, Remote India, Remote Global; 5–9 years) to Telegram, and to WhatsApp
through CallMeBot when that is configured. Either channel works on its own.

## What it checks

| Source | Covers |
| --- | --- |
| RemoteOK, Remotive, Jobicy, Himalayas, We Work Remotely | Remote roles, global and India |
| 76 company career boards (Greenhouse, Lever, Ashby) | Pune and remote roles at the companies listed in `config.json` |
| Adzuna (optional, needs free keys) | India-wide postings, including Pune |

LinkedIn and Naukri are not scraped directly; both block automated access.

## One-time setup: Telegram

1. In Telegram, message **@BotFather**, send `/newbot`, pick a name and a username
   ending in `bot`. It replies with a token.
2. Run `python3 setup_telegram.py`, paste the token, then tap **Start** on your new bot.
   The script sends a test message and saves `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
   as GitHub secrets.

## Optional: WhatsApp via CallMeBot

CallMeBot sometimes stops accepting new users ("The bot is currently full").

1. **Get a CallMeBot key.** Save `+34 644 71 81 99` as a contact and send it the
   WhatsApp message `I allow callmebot to send me messages`. It replies with an API key.
   Check <https://www.callmebot.com/blog/free-api-whatsapp-messages/> first in case
   the number has changed.
2. **Add repository secrets** (GitHub repo → Settings → Secrets and variables → Actions):
   - `CALLMEBOT_PHONE`: your number with country code, e.g. `+9198…`
   - `CALLMEBOT_APIKEY`: the key from step 1
3. **Optional, for much better Pune coverage:** create a free app at
   <https://developer.adzuna.com/> and add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` as secrets.
4. **Test:** Actions tab → Job alerts → Run workflow → tick "Send a test WhatsApp message".

## Run locally

```bash
python3 job_alerts.py --dry-run
```

```bash
python3 job_alerts.py --dry-run --verbose --max-age-days 30
```

`--dry-run` prints matches and sends nothing. `--verbose` shows why each job was skipped.

## Tuning

Everything is in `config.json`: age window, messages per run, experience range,
title filters, and the company board lists. To add a company, find its board name
in its careers URL (for example `boards.greenhouse.io/<name>`) and add it to the
matching list.

Jobs already sent are recorded in `state/seen.json`, which the workflow commits back.
