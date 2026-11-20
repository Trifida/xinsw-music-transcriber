#!/usr/bin/env bash
set -euo pipefail

# AutoDL Pro Linux worker bootstrap + one-song execution.
# Run from a checked-out XinsW Music Transcriber repository:
#   bash scripts/run_autodl_full_transcribe.sh /path/to/song.mp3 --out /path/to/job
#
# The core venv runs CREPE/score generation (CPU); the separate venv runs
# audio-separator with CUDA. No AutoDL API token is needed inside this worker.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SYSTEM_PYTHON="${MUSICMASTER_SYSTEM_PYTHON:-python3}"
CORE_VENV="${MUSICMASTER_CORE_VENV:-$ROOT/.venv}"
SEP_VENV="${MUSICMASTER_SEP_VENV:-$ROOT/vendor/.venv-sep}"
CORE_PY="$CORE_VENV/bin/python"
SEP_PY="$SEP_VENV/bin/python"

"$SYSTEM_PYTHON" -c 'import sys; raise SystemExit("Python 3.10+ is required") if sys.version_info < (3, 10) else None'

if [[ ! -x "$CORE_PY" ]]; then
  "$SYSTEM_PYTHON" scripts/setup_core.py --venv "$CORE_VENV"
fi

if [[ ! -x "$SEP_PY" ]]; then
  "$SYSTEM_PYTHON" scripts/setup_sep.py --venv "$SEP_VENV" --cuda "${MUSICMASTER_TORCH_CUDA:-cu124}"
fi

export MUSICMASTER_SEP_PYTHON="$SEP_PY"
export MUSICMASTER_SEP_MODELS="${MUSICMASTER_SEP_MODELS:-$ROOT/.cache/audio-separator-models}"
mkdir -p "$MUSICMASTER_SEP_MODELS"

exec "$CORE_PY" -m musicmaster.workflows.full_transcribe "$@"
