#!/bin/bash
# Send Telegram notification. Always exits 0 — never blocks agent loop.
# Usage: ./notify.sh "<html message>"
# Supports \n in message text (converted to actual newlines for Telegram).
# Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (skip silently if missing)
[ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ] && exit 0
MSG=$(echo -e "$1")
curl -s --connect-timeout 5 --max-time 10 \
  -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "text=$MSG" \
  -d chat_id="$TELEGRAM_CHAT_ID" \
  -d parse_mode="HTML" > /dev/null 2>&1 || true
exit 0
