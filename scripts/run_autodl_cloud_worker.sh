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
: "${MUSICMASTER_WORKER_TOKEN:?Set MUSICMASTER_WORKER_TOKEN in the worker environment}"

"$SYSTEM_PYTHON" -c 'import sys; raise SystemExit("Python 3.10+ is required") if sys.version_info < (3, 10) else None'

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
