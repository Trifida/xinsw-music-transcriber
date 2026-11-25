from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "run_colab_cloud_worker.py"
SOURCE = LAUNCHER.read_text(encoding="utf-8")


def load_launcher():
    spec = importlib.util.spec_from_file_location("colab_worker_launcher_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_colab_launcher_imports_the_real_v1_runtime_dependencies():
    module = load_launcher()

    assert {
        "numpy", "librosa", "soundfile", "tensorflow", "crepe", "hmmlearn", "music21",
    }.issubset(set(module.REQUIRED_MODULES))
    assert "torch" not in module.REQUIRED_MODULES
    assert "torchaudio" not in module.REQUIRED_MODULES
    assert "audio_separator.separator" not in module.REQUIRED_MODULES


def test_colab_launcher_checks_project_entrypoints_and_sep_interpreter():
    for module_name in (
        "musicmaster.cloud.worker",
        "musicmaster.workflows.full_transcribe",
        "musicmaster.separate.pipeline",
        "musicmaster.transcribe.autopilot",
    ):
        assert module_name in SOURCE

    assert "from musicmaster.web.runners import _sep_python" in SOURCE
    assert "audio_separator.separator" in SOURCE
    assert "MUSICMASTER_SEP_PYTHON" in SOURCE
    assert "分离环境检查失败" in SOURCE
    assert "与当前 CUDA Python 不一致" not in SOURCE


def test_colab_launcher_requires_api_root_and_existing_bs_roformer_weights():
    assert 'parsed.path not in ("", "/")' in SOURCE
    assert "parsed.query or parsed.fragment" in SOURCE
    assert 'if not (model_dir / filename).is_file()' in SOURCE
    assert "MUSICMASTER_WORKER_TOKEN" in SOURCE


def test_colab_launcher_does_not_install_dependencies_or_provision_gpu():
    lowered = SOURCE.lower()
    assert "pip install" not in lowered
    assert "autodl" not in lowered
    assert "create_autodl_worker" not in SOURCE
    assert "subprocess.run" in SOURCE
    assert "subprocess.Popen" not in SOURCE


def test_cpu_runtime_is_accepted_as_a_compute_fallback():
    module = load_launcher()
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: False,
            device_count=lambda: 0,
        ),
        version=SimpleNamespace(cuda=None),
    )

    # A connected CPU runtime is a valid worker runtime; CUDA is optional.
    assert fake_torch.cuda.is_available() is False
    assert fake_torch.cuda.device_count() == 0
    assert "当前 Colab 运行时没有分配可用 CUDA GPU" not in SOURCE
    assert "当前使用 CPU Runtime" in SOURCE
