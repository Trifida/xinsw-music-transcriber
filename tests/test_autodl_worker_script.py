# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_autodl_full_transcribe.sh"


def test_autodl_worker_bootstrap_is_valid_bash():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_autodl_worker_uses_two_existing_virtual_environments():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "scripts/setup_core.py" in source
    assert "scripts/setup_sep.py" in source
    assert 'export MUSICMASTER_SEP_PYTHON="$SEP_PY"' in source
    assert "MUSICMASTER_SEP_MODELS" in source
    assert 'exec "$CORE_PY" -m musicmaster.workflows.full_transcribe "$@"' in source
