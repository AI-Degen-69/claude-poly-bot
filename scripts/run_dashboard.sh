#!/usr/bin/env bash
# Launch the dashboard backend (FastAPI on :8787) and the Vite UI (on :5173).
set -e
cd "$(dirname "$0")/.."

mkdir -p logs

ts=$(date +%Y%m%d_%H%M%S)
server_log="logs/server_${ts}.log"
ui_log="logs/ui_${ts}.log"
touch "$server_log" "$ui_log"
# Symlinks are unavailable under Git Bash on Windows; don't abort the launch.
ln -sfn "server_${ts}.log" logs/server_current.log 2>/dev/null || echo "$server_log" > logs/server_current.path
ln -sfn "ui_${ts}.log" logs/ui_current.log 2>/dev/null || echo "$ui_log" > logs/ui_current.path

# stop any prior instance
if [[ -f server.pid ]] && ps -p "$(cat server.pid)" > /dev/null 2>&1; then
  kill "$(cat server.pid)" || true
  sleep 1
fi
if [[ -f ui.pid ]] && ps -p "$(cat ui.pid)" > /dev/null 2>&1; then
  kill "$(cat ui.pid)" || true
  sleep 1
fi

nohup .venv/bin/uvicorn server.dashboard:app --host 127.0.0.1 --port 8787 > "$server_log" 2>&1 &
echo $! > server.pid
disown 2>/dev/null || true

nohup npm --prefix ui run dev -- --host 127.0.0.1 --port 5173 > "$ui_log" 2>&1 &
echo $! > ui.pid
disown 2>/dev/null || true

sleep 2

s_alive=$(ps -p "$(cat server.pid)" > /dev/null 2>&1 && echo yes || echo no)
u_alive=$(ps -p "$(cat ui.pid)" > /dev/null 2>&1 && echo yes || echo no)
echo "server pid=$(cat server.pid)  alive=$s_alive  log=$server_log"
echo "ui     pid=$(cat ui.pid)      alive=$u_alive  log=$ui_log"
echo
echo "open: http://127.0.0.1:5173"
echo "stop: scripts/stop_dashboard.sh"
