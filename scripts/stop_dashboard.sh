#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

for tag in server ui; do
  if [[ -f "${tag}.pid" ]]; then
    pid=$(cat "${tag}.pid")
    if ps -p "$pid" > /dev/null 2>&1; then
      kill "$pid" || true
      for _ in 1 2 3; do
        if ! ps -p "$pid" > /dev/null 2>&1; then break; fi
        sleep 1
      done
      if ps -p "$pid" > /dev/null 2>&1; then
        kill -9 "$pid" || true
      fi
      echo "stopped $tag pid=$pid"
    fi
    rm -f "${tag}.pid"
  fi
done

# kill any lingering vite/uvicorn just in case
pkill -f "uvicorn server.dashboard" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
echo "done."
