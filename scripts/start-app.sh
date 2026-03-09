#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Stopping backend (PID $BACKEND_PID)..."
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is not installed or not on PATH."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is not installed or not on PATH."
  exit 1
fi

cd "$REPO_ROOT"
unset VIRTUAL_ENV
export PYTHONPATH="$REPO_ROOT/src"

echo "Starting backend on http://127.0.0.1:8000 ..."
uv run uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

if [[ ! -d "src/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd src/frontend && npm install)
fi

echo "Starting frontend on http://localhost:5173 ..."
cd src/frontend
npm run dev
