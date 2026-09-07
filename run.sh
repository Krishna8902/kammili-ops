#!/usr/bin/env bash
# Fetch, build, render. Any single fetch may fail; the build still runs on
# the last good dump and the page shows the data age in red.
set -uo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

python3 fetch/check_window.py || exit 0

python3 fetch/ownerrez.py || echo "ownerrez fetch failed, using last dump" >&2
python3 fetch/maintenance.py || echo "maintenance fetch failed, using last dump" >&2

python3 build.py  || { echo "build failed" >&2; exit 1; }
python3 render.py || { echo "render failed" >&2; exit 1; }
