#!/usr/bin/env bash
# Start the IHP dev servers (backend :8001, frontend :3000) from Git Bash.
# Port 8000 is occupied by another local service on this machine.
ROOT="$(cd "$(dirname "$0")" && pwd)"
(cd "$ROOT/backend" && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8001) &
(cd "$ROOT/frontend" && npm run dev)
