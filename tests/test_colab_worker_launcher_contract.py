from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "run_colab_cloud_worker.py"
SOURCE = LAUNCHER.read_text(encoding="utf-8")


def test_colab_launcher_imports_the_real_v1_runtime_dependencies():
    spec = importlib.util.spec_from_file_location("colab_worker_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert {
        "numpy", "librosa", "soundfile", "torch", "audio_separator",
        "tensorflow", "crepe", "hmmlearn", "music21",
    }.issubset(set(module.REQUIRED_MODULES))


def test_colab_launcher_checks_project_entrypoints_and_sep_interpreter():
    for module_name in (
        "musicmaster.cloud.worker",
        "musicmaster.workflows.full_transcribe",
        "musicmaster.separate.pipeline",
        "musicmaster.transcribe.autopilot",
    ):
        assert module_name in SOURCE

    assert "from musicmaster.web.runners import _sep_python" in SOURCE
    assert "Path(resolved_sep_python).resolve() != Path(sys.executable).resolve()" in SOURCE
    assert 'os.environ["MUSICMASTER_SEP_PYTHON"] = sys.executable' in SOURCE


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
    assert "subprocess" not in lowered
