from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.worker"
WORKFLOW = ROOT / ".github" / "workflows" / "build-worker-image.yml"


def test_worker_image_uses_two_isolated_cpu_python_environments():
    source = DOCKERFILE.read_text(encoding="utf-8")
    assert "python:3.11-slim-bookworm" in source
    assert "/opt/xinsw-core-venv" in source
    assert "/opt/xinsw-sep-venv" in source
    assert "requirements/locks/core-cpu.txt" in source
    assert "requirements/locks/separator-cpu.txt" in source
    assert "download.pytorch.org/whl/cpu" in source
    assert "MUSICMASTER_SEP_PYTHON=/opt/xinsw-sep-venv/bin/python" in source


def test_worker_image_prepares_crepe_and_separator_model_cache_at_runtime():
    source = DOCKERFILE.read_text(encoding="utf-8")
    assert "scripts/prepare_crepe_model.py" in source
    assert "MUSICMASTER_SEP_MODELS=/models/audio-separator" in source
    assert "mkdir -p /models/audio-separator" in source
    assert "audio_separator.separator" in source


def test_worker_image_runs_the_cloud_worker_without_baking_secrets():
    source = DOCKERFILE.read_text(encoding="utf-8")
    assert 'CMD ["/opt/xinsw-core-venv/bin/python", "-m", "musicmaster.cloud.worker"]' in source
    assert "MUSICMASTER_API_URL" in source
    assert "MUSICMASTER_WORKER_TOKEN" in source
    assert "ENV MUSICMASTER_WORKER_TOKEN" not in source


def test_worker_image_workflow_builds_prs_without_publishing():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in source
    assert "push: ${{ github.event_name != 'pull_request' }}" in source
    assert "ghcr.io/trifida/xinsw-music-transcriber-worker" in source
