#!/usr/bin/env bash
# Stop the copy-trade tracker and its dashboard — reliably.
#
# `pkill -f` does NOT work for these under Git Bash on Windows: the python
# processes are Windows processes that MSYS pkill cannot see, so repeated
# "restarts" silently stacked FOUR tracker instances all writing to the same
# follow.db. Match on the real Windows command line instead.
set -e
cd "$(dirname "$0")/.."

powershell -NoProfile -Command "
Get-CimInstance Win32_Process |
  Where-Object { \$_.CommandLine -match 'follow\.(main|dashboard)' } |
  ForEach-Object {
    Write-Output ('stopped pid ' + \$_.ProcessId)
    Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue
  }
"
sleep 2

left=$(powershell -NoProfile -Command "
(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'follow\.(main|dashboard)' } | Measure-Object).Count
" | tr -d '\r')

rm -f follow.pid
if [[ "$left" == "0" ]]; then
  echo "all follow processes stopped"
else
  echo "WARNING: $left process(es) still alive"
  exit 1
fi
