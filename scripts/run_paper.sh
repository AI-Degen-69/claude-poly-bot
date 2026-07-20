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
touch "$log"
# Symlinks are unavailable under Git Bash on Windows; fall back to a copy-free
# pointer file rather than aborting the launch.
ln -sfn "bot_${ts}.log" logs/bot_current.log 2>/dev/null || echo "$log" > logs/bot_current.path

# No --live flag = dry-run / paper mode
nohup .venv/bin/python -m bot.main > "$log" 2>&1 &
echo $! > bot.pid
echo "paper" > bot.mode
# Git Bash reports an MSYS pid, which native-Windows Python cannot check with
# os.kill(). Record the real Windows pid too so the dashboard can see the bot.
ps -p "$(cat bot.pid)" 2>/dev/null | awk 'NR==2 {print $4}' > bot.win.pid || true
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
