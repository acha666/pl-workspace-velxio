#!/bin/bash
set -euo pipefail

# Retain the official two-process design. Package installation belongs to
# the Docker build; this entrypoint performs no network setup or downloads.
python3 - <<'PY'
import json
import os
import re
from pathlib import Path

base = os.environ.get('WORKSPACE_BASE_URL', '/')
if not re.fullmatch(r'/[A-Za-z0-9/_-]*', base) or base.startswith('//'):
    raise SystemExit('WORKSPACE_BASE_URL must be an absolute URL path.')
base = base.rstrip('/') + '/'
Path('/tmp/velxio-workspace-config.js').write_text(
    'window.__VELXIO_WORKSPACE_BASE__ = ' + json.dumps(base) + ';\n'
    'window.__VELXIO_API_BASE__ = ' + json.dumps(base + 'api') + ';\n',
    encoding='utf-8',
)
PY

uvicorn app.main:app --host 127.0.0.1 --port 8001 &
backend_pid=$!
nginx -c /app/pl-nginx.conf -g 'daemon off;' &
nginx_pid=$!
stop_children() {
    kill "$backend_pid" "$nginx_pid" 2>/dev/null || true
    wait "$backend_pid" "$nginx_pid" 2>/dev/null || true
}
trap stop_children EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
set +e
wait -n "$backend_pid" "$nginx_pid"
status=$?
exit "$status"
