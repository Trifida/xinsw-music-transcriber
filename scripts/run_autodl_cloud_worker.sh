#!/usr/bin/env bash
set -euo pipefail

# AutoDL GPU worker bootstrap. Secrets and API URL must be injected as environment variables.
# This script intentionally never creates or powers on a paid GPU instance.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SYSTEM_PYTHON="${MUSICMASTER_SYSTEM_PYTHON:-python3}"
CORE_VENV="${MUSICMASTER_CORE_VENV:-$ROOT/.venv}"
SEP_VENV="${MUSICMASTER_SEP_VENV:-$ROOT/vendor/.venv-sep}"
CORE_PY="$CORE_VENV/bin/python"
SEP_PY="$SEP_VENV/bin/python"

: "${MUSICMASTER_API_URL:?Set MUSICMASTER_API_URL to the HTTPS production API URL}"
if [[ -z "${MUSICMASTER_WORKER_TOKEN:-}" && -z "${MUSICMASTER_BOOTSTRAP_TOKEN:-}" ]]; then
  echo "Set MUSICMASTER_WORKER_TOKEN or MUSICMASTER_BOOTSTRAP_TOKEN in the worker environment." >&2
  exit 1
fi

"$SYSTEM_PYTHON" -c 'import sys; raise SystemExit("Python 3.10+ is required") if sys.version_info < (3, 10) else None'

# This launcher fetches the exact private-repository commit before running application code.
if [[ "${MUSICMASTER_SKIP_BUNDLE_BOOTSTRAP:-0}" != "1" ]]; then
  BOOTSTRAP_JSON="$("$SYSTEM_PYTHON" "$ROOT/scripts/bootstrap_worker_bundle.py")"
  BUNDLE_ROOT="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["bundle_root"])' <<<"$BOOTSTRAP_JSON")"
  export MUSICMASTER_WORKER_TOKEN="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["worker_token"])' <<<"$BOOTSTRAP_JSON")"
  export MUSICMASTER_WORKER_ID="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("worker_id") or "")' <<<"$BOOTSTRAP_JSON")"
  INSTANCE_UUID="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("instance_uuid") or "")' <<<"$BOOTSTRAP_JSON")"
  if [[ -n "$INSTANCE_UUID" ]]; then export MUSICMASTER_INSTANCE_UUID="$INSTANCE_UUID"; fi
  unset BOOTSTRAP_JSON MUSICMASTER_BOOTSTRAP_TOKEN
  exec env MUSICMASTER_SKIP_BUNDLE_BOOTSTRAP=1 bash "$BUNDLE_ROOT/scripts/run_autodl_cloud_worker.sh"
fi

# Exchange the one-time bootstrap token before lengthy environment/model setup.
if [[ -z "${MUSICMASTER_WORKER_TOKEN:-}" ]]; then
  BOOTSTRAP_JSON="$("$SYSTEM_PYTHON" - "${MUSICMASTER_API_URL}" "${MUSICMASTER_BOOTSTRAP_TOKEN}" <<'PY'
import json
import sys
import urllib.request

base, token = sys.argv[1].rstrip("/"), sys.argv[2]
request = urllib.request.Request(
    base + "/api/internal/bootstrap",
    data=json.dumps({"bootstrap_token": token}).encode("utf-8"),
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode("utf-8"))
PY
)"
  export MUSICMASTER_WORKER_TOKEN="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["worker_token"])' <<<"$BOOTSTRAP_JSON")"
  export MUSICMASTER_WORKER_ID="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["worker_id"])' <<<"$BOOTSTRAP_JSON")"
  INSTANCE_UUID="$("$SYSTEM_PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("instance_uuid") or "")' <<<"$BOOTSTRAP_JSON")"
  if [[ -n "$INSTANCE_UUID" ]]; then export MUSICMASTER_INSTANCE_UUID="$INSTANCE_UUID"; fi
  unset BOOTSTRAP_JSON
  unset MUSICMASTER_BOOTSTRAP_TOKEN
fi

if [[ ! -x "$CORE_PY" ]]; then
  "$SYSTEM_PYTHON" scripts/setup_core.py --venv "$CORE_VENV"
fi

if [[ ! -x "$SEP_PY" ]]; then
  "$SYSTEM_PYTHON" scripts/setup_sep.py --venv "$SEP_VENV" --cuda "${MUSICMASTER_TORCH_CUDA:-cu124}"
fi

export MUSICMASTER_SEP_PYTHON="$SEP_PY"
export MUSICMASTER_SEP_MODELS="${MUSICMASTER_SEP_MODELS:-$ROOT/.cache/audio-separator-models}"
export MUSICMASTER_WORKER_DATA="${MUSICMASTER_WORKER_DATA:-$ROOT/.cache/jobs}"
mkdir -p "$MUSICMASTER_SEP_MODELS" "$MUSICMASTER_WORKER_DATA"

exec "$CORE_PY" -m musicmaster.cloud.worker
