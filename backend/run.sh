#!/usr/bin/env bash
# Run the IFTR (Evolved) FastAPI backend locally.
#
# Finds a usable virtualenv, then starts uvicorn with reload.
#   HOST=127.0.0.1 PORT=8000 ./run.sh
#
# Also runs the operator commands in the same environment:
#   ./run.sh create-admin you@example.com   # seed/promote an administrator
#   ./run.sh cleanup-uploads                # report only
#   ./run.sh cleanup-uploads --delete       # remove unreferenced uploads
set -euo pipefail

cd "$(dirname "$0")"

# Prefer the repo-root venv (Evolved/backend -> ../../.venv), then a local one.
for candidate in \
  "../../.venv/Scripts/python.exe" \
  "../../.venv/bin/python" \
  ".venv/Scripts/python.exe" \
  ".venv/bin/python"
do
  if [ -x "$candidate" ]; then
    PY="$candidate"
    break
  fi
done

if [ -z "${PY:-}" ]; then
  echo "No virtualenv found. Create one and install dependencies first:" >&2
  echo "  python -m venv .venv" >&2
  echo "  .venv/Scripts/python -m pip install -r requirements.txt   # Windows" >&2
  echo "  .venv/bin/python   -m pip install -r requirements.txt   # POSIX" >&2
  exit 1
fi

# Subcommand: seed the first administrator (registration cannot grant admin).
if [ "${1:-}" = "create-admin" ]; then
  shift
  exec "$PY" create_admin.py "$@"
fi

# Subcommand: reclaim space taken by uploads nothing references any more.
if [ "${1:-}" = "cleanup-uploads" ]; then
  shift
  exec "$PY" cleanup_uploads.py "$@"
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "Starting IFTR API on http://${HOST}:${PORT}"
echo "Interpreter: ${PY}"
echo "Docs:        http://${HOST}:${PORT}/docs"

exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
