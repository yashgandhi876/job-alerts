#!/usr/bin/env python3
"""One-time Telegram setup: asks for your bot token (hidden), finds your chat ID
after you message the bot, sends a test message, and saves both values as
GitHub Actions secrets with `gh`.
"""
import getpass
import json
import subprocess
import sys
import time
import urllib.request

REPO = "yashgandhi876/job-alerts"


def api(token, method, **params):
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read() or b"{}")


def main():
    token = getpass.getpass("Paste your bot token from @BotFather (hidden): ").strip()
    me = api(token, "getMe")
    if not me.get("ok"):
        sys.exit(f"That token didn't work: {me.get('description', me)}")
    bot = me["result"]["username"]
    api(token, "deleteWebhook")
    print(f"\nToken OK. Now open Telegram, search @{bot}, tap Start (or send any message).")
    print("Waiting up to 3 minutes...")

    chat_id, offset, deadline = None, None, time.time() + 180
    while time.time() < deadline and chat_id is None:
        params = {"timeout": 25}
        if offset:
            params["offset"] = offset
        for update in api(token, "getUpdates", **params).get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message") or update.get("edited_message") or {}
            if msg.get("chat", {}).get("type") == "private":
                chat_id = msg["chat"]["id"]
    if chat_id is None:
        sys.exit("No message received. Run this again and message the bot while it waits.")

    sent = api(token, "sendMessage", chat_id=chat_id,
               text="✅ Connected. Java + Spring Boot job alerts will arrive here.")
    if not sent.get("ok"):
        sys.exit(f"Couldn't send the test message: {sent.get('description', sent)}")
    print("Test message sent to your Telegram.")

    for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", str(chat_id))):
        subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=value, text=True, check=True)
    print("Saved TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub secrets. All done.")


if __name__ == "__main__":
    main()
