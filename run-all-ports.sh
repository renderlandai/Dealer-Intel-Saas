#!/usr/bin/env bash
# Start backend (port 8000) and frontend (port 3000).
# Run from your project root in a terminal where npm and python are in PATH.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Ensure npm is available (nvm, fnm, homebrew)
if ! command -v npm &>/dev/null; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  [[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh"
  if ! command -v npm &>/dev/null && [[ -s "$HOME/.fnm/fnm" ]]; then
    eval "$("$HOME/.fnm/fnm" env)"
  fi
fi
if ! command -v npm &>/dev/null; then
  echo "npm not found. Install Node.js or run from a terminal where npm is in PATH."
  echo "Then start manually: backend on :8000, frontend on :3000."
  exit 1
fi

# Backend: ensure venv and deps, then start
backend_start() {
  cd "$ROOT/backend"
  if [[ ! -d venv ]]; then
    python3 -m venv venv || python -m venv venv
  fi
  source venv/bin/activate
  pip install -q -r requirements.txt
  exec uvicorn app.main:app --reload --port 8000
}

# Frontend: install deps if needed, then start
frontend_start() {
  cd "$ROOT/frontend"
  [[ -d node_modules ]] || npm install
  exec npm run dev
}

# Run both in background when sourced or run
echo "Starting backend on http://localhost:8000 ..."
backend_start &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:3000 ..."
frontend_start &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:8000  (PID $BACKEND_PID)"
echo "Frontend: http://localhost:3000   (PID $FRONTEND_PID)"
echo "Press Ctrl+C to stop both."
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
