#!/usr/bin/env bash
# Launch the trading bot in LIVE mode (REAL ORDERS, REAL MONEY).
# For paper trading, use scripts/run_paper.sh instead.
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

nohup .venv/bin/python -m bot.main --live > "$log" 2>&1 &
echo $! > bot.pid
echo "live" > bot.mode
disown 2>/dev/null || true
sleep 1

if ps -p "$(cat bot.pid)" > /dev/null 2>&1; then
  echo "LIVE mode bot started pid=$(cat bot.pid)"
  echo "  REAL ORDERS will be placed against your funded deposit wallet"
  echo "  log: $log"
  echo "  tail: tail -f logs/bot_current.log"
  echo "  stop: scripts/stop_live.sh"
else
  echo "FAILED — see $log"
  exit 1
fi
