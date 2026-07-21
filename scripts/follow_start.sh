#!/usr/bin/env bash
# Start the copy-trade tracker + dashboard. Refuses to double-launch.
#
#   scripts/follow_start.sh            resume the current experiment
#   scripts/follow_start.sh --fresh    archive follow.db and start a new one
#                                      (both sides then begin from the same
#                                       instant with $5,000 and zero trades)
set -e
cd "$(dirname "$0")/.."
mkdir -p logs archive

running=$(powershell -NoProfile -Command "
(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'follow\.(main|dashboard)' } | Measure-Object).Count
" | tr -d '\r')
if [[ "$running" != "0" ]]; then
  echo "$running follow process(es) already running — run scripts/follow_stop.sh first"
  exit 1
fi

if [[ "$1" == "--fresh" ]]; then
  ts=$(date +%Y%m%d_%H%M%S)
  if [[ -f follow.db ]]; then
    mv follow.db "archive/follow_${ts}.db"
    echo "archived -> archive/follow_${ts}.db"
  fi
  rm -f follow.db-shm follow.db-wal
fi

export POLYFOLLOW_DB="${POLYFOLLOW_DB:-follow.db}"
ts=$(date +%m%d_%H%M%S)

nohup .venv/bin/python -m follow.main > "logs/follow_${ts}.log" 2>&1 &
sleep 3
nohup .venv/Scripts/python.exe -m uvicorn follow.dashboard:app \
      --host 127.0.0.1 --port 8799 > "logs/follow_dash_${ts}.log" 2>&1 &
sleep 6

echo "tracker  log: logs/follow_${ts}.log"
echo "dashboard   : http://127.0.0.1:8799"
echo "stop        : scripts/follow_stop.sh"
