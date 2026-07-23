#!/usr/bin/env bash
# fork_bot.sh — scaffold an ISOLATED, runnable fork of THIS bot (the template).
#
# Usage:
#   scripts/fork_bot.sh <fork-name> [--port N] [--dest DIR] [--force]
#
# What it produces (a sibling directory, e.g. ../<fork-name>):
#   - a full copy of the code, with runtime/secret artifacts EXCLUDED
#   - its own database (POLYBOT_DB) and dashboard port (PORT) -> no clash
#     with the running template or any other fork
#   - its own .env, .venv, and pid/mode files (all written under the fork dir)
#   - the built UI bundled in, so the dashboard serves it on one port
#   - a fresh git repo with the research-log pre-commit hook armed
#
# The template (this repo) is NEVER modified. A fork is a clean slate: tune
# strategy/config.py there without ever touching the live bot.
#
# SECURITY: the fork copies this repo's .env (which holds the wallet key) so it
# runs immediately in sim/paper mode. Keep forks on this machine; .env is
# gitignored so it never gets committed. For a public fork, replace .env with
# .env.example placeholders first.
set -euo pipefail

PORT=""
DEST=""
FORCE=0
NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)  PORT="${2:-}"; shift 2;;
    --dest)  DEST="${2:-}"; shift 2;;
    --force) FORCE=1; shift;;
    -*) echo "unknown flag: $1" >&2; exit 2;;
    *) NAME="${NAME:-$1}"; shift;;
  esac
done

if [[ -z "${NAME:-}" ]]; then
  echo "usage: scripts/fork_bot.sh <fork-name> [--port N] [--dest DIR] [--force]" >&2
  exit 2
fi

PARENT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "$DEST" ]]; then
  FORK="$DEST"
else
  FORK="$(dirname "$PARENT")/$NAME"
fi

if [[ -e "$FORK" && $FORCE -eq 0 ]]; then
  echo "ERROR: $FORK already exists. Remove it or pass --force." >&2
  exit 1
fi

if [[ -z "$PORT" ]]; then PORT=8790; fi
VITE_PORT=$((PORT + 100))

echo "==> forking template : $PARENT"
echo "==> fork dir        : $FORK"
echo "==> dashboard PORT  : $PORT   (vite dev: $VITE_PORT)"

# --- 1) copy source tree, excluding runtime/secret artifacts ----------------
if [[ -e "$FORK" ]]; then rm -rf "$FORK"; fi
mkdir -p "$FORK"
# Write to a real tarball first, then extract — a piped tar|tar can still be
# extracting when the next step runs, and the patch below would race a missing
# run_dashboard.sh. Materializing the archive makes extraction synchronous.
_TARBALL="$(mktemp -t fork_XXXXXX.tar)"
tar -C "$PARENT" -cf "$_TARBALL" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='ui/node_modules' \
  --exclude='ui/dist' \
  --exclude='.env' \
  --exclude='logs' \
  --exclude='archive' \
  --exclude='*.db' \
  --exclude='*.pid' \
  --exclude='bot.mode' \
  --exclude='research/bonereader_raw' \
  --exclude='research/*.json' \
  --exclude='research/*.log' \
  --exclude='.railway' \
  --exclude='.railway-config-pull-*' \
  .
tar -C "$FORK" -xf "$_TARBALL"
rm -f "$_TARBALL"
test -f "$FORK/scripts/run_dashboard.sh" || { echo "ERROR: copy failed (run_dashboard.sh missing)"; exit 1; }

# --- 2) bundle the built UI (built mode = single port, no vite needed) ------
if [[ -d "$PARENT/ui/dist" ]]; then
  cp -R "$PARENT/ui/dist" "$FORK/ui/dist"
  echo "==> UI: copied built dist from template"
elif (cd "$PARENT/ui" && npm ci --no-audit --no-fund && npm run build); then
  cp -R "$PARENT/ui/dist" "$FORK/ui/dist"
  echo "==> UI: built from template and copied"
else
  echo "WARNING: UI build skipped (need node/npm). Dashboard will serve API only;"
  echo "         run 'npm --prefix ui install && npm --prefix ui run build' in the fork later."
fi

# --- 3) isolate in .env (copy template .env so it runs immediately) ----------
if [[ -f "$PARENT/.env" ]]; then
  cp "$PARENT/.env" "$FORK/.env"
  echo "==> .env copied from template (holds wallet creds -- keep this fork local)."
else
  cp "$PARENT/.env.example" "$FORK/.env"
  echo "==> .env created from .env.example (placeholder creds; sim-only safe)."
fi
cat >> "$FORK/.env" <<ENV

# --- fork isolation (added by fork_bot.sh) ---
PORT=$PORT
VITE_PORT=$VITE_PORT
POLYBOT_DB=$(cygpath -w "$FORK/trades.db" 2>/dev/null || echo "$FORK/trades.db")
COLLECTOR_DB=$(cygpath -w "$FORK/collector.db" 2>/dev/null || echo "$FORK/collector.db")
ENV

# --- 4) make run_dashboard.sh port-aware (read PORT/VITE_PORT from .env) -----
# Prefer the real MSYS python over the Windows Store `python3` stub, which
# cannot open MSYS-style paths like /tmp/.... Pass a Windows-native path.
PYBIN="$(command -v python || command -v python3 || command -v python3.exe)"
FORK_WIN="$(cygpath -w "$FORK" 2>/dev/null || echo "$FORK")"
"$PYBIN" - "$FORK_WIN/scripts/run_dashboard.sh" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
# Insert safe .env parsing (grep only PORT/VITE_PORT; never source secrets).
s = s.replace(
    "set -e\n",
    "set -e\n"
    "DIR=\"$(cd \"$(dirname \"$0\")/..\" && pwd)\"\n"
    "PORT=\"$(grep -E '^PORT=' \"$DIR/.env\" 2>/dev/null | tail -1 | cut -d= -f2-)\"\n"
    "VITE_PORT=\"$(grep -E '^VITE_PORT=' \"$DIR/.env\" 2>/dev/null | tail -1 | cut -d= -f2-)\"\n"
    "PORT=\"${PORT:-8787}\"\n"
    "VITE_PORT=\"${VITE_PORT:-5173}\"\n",
    1,
)
# If the built UI is bundled (forks copy it from the template), the dashboard
# serves it on $PORT directly -- don't also start Vite (it would proxy /api to
# the template's 8787 and has no node_modules in the fork). Apply THIS before the
# generic port replacements below, which would otherwise mutate the vite line
# and stop this target from matching.
s = s.replace(
    "nohup npm --prefix ui run dev -- --host 127.0.0.1 --port 5173 > \"$ui_log\" 2>&1 &\n"
    "echo $! > ui.pid\n"
    "disown 2>/dev/null || true",
    "if [[ ! -d ui/dist ]]; then\n"
    "  nohup npm --prefix ui run dev -- --host 127.0.0.1 --port \"$VITE_PORT\" > \"$ui_log\" 2>&1 &\n"
    "  echo $! > ui.pid\n"
    "  disown 2>/dev/null || true\n"
    "else\n"
    "  echo \"built UI present (ui/dist) -- dashboard serves it on $PORT; skipping Vite\" > \"$ui_log\"\n"
    "fi",
)
s = s.replace("--port 8787", "--port \"$PORT\"")
# Point the user at $PORT (the dashboard serves the built UI in a fork).
s = s.replace("echo \"open: http://127.0.0.1:5173\"",
              "echo \"open: http://127.0.0.1:$PORT   (built UI served by dashboard)\"")
open(p, "w", encoding="utf-8").write(s)
PY

# --- 5) fork marker + fresh git repo + arm the research-log hook ------------
cd "$FORK"
TEMPLATE_SHA="$(cd "$PARENT" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"

cat > FORKED_FROM.md <<MD
# Forked from: polymarket-taker (template)

- Template path : $PARENT
- Template commit: $TEMPLATE_SHA
- Fork created  : $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Dashboard port: $PORT   (vite dev: $VITE_PORT)
- Database      : $FORK/trades.db

This is an ISOLATED copy. Tune \`strategy/config.py\` here freely -- the
template bot is untouched. Run with:

    bash scripts/run_paper.sh           # paper / sim bot
    bash scripts/run_dashboard.sh       # dashboard on port $PORT
    # open http://127.0.0.1:$PORT
MD

git init -q
git config user.email "fork@local"
git config user.name "fork-bot"
git add -A
git add -f ui/dist 2>/dev/null || true   # bundled UI: keep the fork self-contained
git commit -q -m "fork: initial snapshot from template ($(basename "$PARENT") @ $TEMPLATE_SHA)"
bash scripts/setup-hooks.sh >/dev/null 2>&1 || true

# --- 6) provision the python venv in the BACKGROUND -------------------------
# web3/clob wheels are slow to build on Windows (often >5 min), so provision
# asynchronously: the fork is fully structured now; the venv finishes while you
# read this. Tail the log to know when it's ready to run.
mkdir -p "$FORK/logs"
VENV_LOG="$FORK/logs/venv_provision.log"
{
  if command -v uv >/dev/null 2>&1; then
    uv venv >/dev/null 2>&1 && uv pip install -r "$FORK/requirements.txt" && \
      echo "VENV READY" || echo "VENV FAILED"
  else
    echo "WARNING: uv not found; create a venv manually:" >&2
    echo "  cd $FORK && python -m venv .venv && pip install -r requirements.txt" >&2
  fi
} > "$VENV_LOG" 2>&1 &

echo
echo "DONE. Fork ready at: $FORK"
echo "  (venv provisioning in background — tail: tail -f logs/venv_provision.log)"
echo "  cd \"$FORK\""
echo "  bash scripts/run_paper.sh       # start the (sim) bot"
echo "  bash scripts/run_dashboard.sh   # dashboard -> http://127.0.0.1:$PORT"
echo "  then edit strategy/config.py to test new parameters."
