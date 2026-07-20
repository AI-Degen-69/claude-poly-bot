#!/usr/bin/env bash
# Cleanly stop the live bot.
set -e
cd "$(dirname "$0")/.."

if [[ ! -f bot.pid ]]; then
  echo "no bot.pid"
  exit 0
fi
pid=$(cat bot.pid)
if ps -p "$pid" > /dev/null 2>&1; then
  kill "$pid"
  for _ in 1 2 3 4 5; do
    if ! ps -p "$pid" > /dev/null 2>&1; then break; fi
    sleep 1
  done
  if ps -p "$pid" > /dev/null 2>&1; then
    echo "graceful stop failed; SIGKILL"
    kill -9 "$pid"
  fi
  echo "stopped pid=$pid"
else
  echo "pid $pid not running"
fi
rm -f bot.pid bot.mode bot.win.pid
