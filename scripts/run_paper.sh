#!/usr/bin/env bash
# Launch the bot in PAPER mode — logs decisions only, never places real orders.
# Safe to run while you're learning or tuning the strategy.
set -e
cd "$(dirname "$0")/.."

if [[ -f bot.pid ]] && ps -p "$(cat bot.pid)" > /dev/null 2>&1; then
  echo "bot already running pid=$(cat bot.pid)"
  echo "stop it first:  scripts/stop_live.sh"
  exit 1
fi

mkdir -p logs
ts=$(date +%Y%m%d_%H%M%S)
log="logs/bot_${ts}.log"
ln -sfn "bot_${ts}.log" logs/bot_current.log

# No --live flag = dry-run / paper mode
nohup .venv/bin/python -m bot.main > "$log" 2>&1 &
echo $! > bot.pid
echo "paper" > bot.mode
disown 2>/dev/null || true
sleep 1

if ps -p "$(cat bot.pid)" > /dev/null 2>&1; then
  echo "PAPER mode bot started pid=$(cat bot.pid)"
  echo "  no real orders will be placed"
  echo "  log: $log"
  echo "  tail: tail -f logs/bot_current.log"
  echo "  stop: scripts/stop_live.sh"
else
  echo "FAILED — see $log"
  exit 1
fi
