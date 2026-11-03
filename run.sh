#!/usr/bin/env bash
# Fetch, build, render. OwnerRez has to succeed with fresh data.
# Tasks, Turno and Enso fail on their own panels and do not stop the build.
set -uo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

python3 fetch/check_window.py
status=$?
if [ "$status" -eq 2 ]; then
  exit 0
elif [ "$status" -ne 0 ]; then
  exit "$status"
fi

python3 fetch/ownerrez.py || { echo "ownerrez fetch failed; not building from cached raw/" >&2; exit 1; }
python3 fetch/maintenance.py || echo "maintenance fetch failed, using last dump" >&2
python3 fetch/tasks.py || echo "tasks panel will show an error" >&2
python3 fetch/turno.py || echo "turno panel will show an error" >&2
python3 fetch/enso.py || echo "enso panel will show an error" >&2

python3 build.py  || { echo "build failed" >&2; exit 1; }
python3 render.py || { echo "render failed" >&2; exit 1; }
