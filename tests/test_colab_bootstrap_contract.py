import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "scripts" / "bootstrap_colab_worker.py").read_text(encoding="utf-8")
NOTEBOOK = (ROOT / "notebooks" / "XinsW_Colab_GPU_Worker_V1.ipynb").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "COLAB_CLOUD_WORKER.md").read_text(encoding="utf-8")


def test_colab_bootstrap_keeps_core_and_separator_dependency_stacks_isolated():
    assert "requirements/locks/core-cpu.txt" in BOOTSTRAP
    assert "requirements/requirements-sep.txt" in BOOTSTRAP
    assert "torch==2.11.0" in BOOTSTRAP
    assert "torchvision==0.26.0" in BOOTSTRAP
    assert "torchaudio==2.11.0" in BOOTSTRAP
    assert "numpy.__version__.startswith('1.')" in BOOTSTRAP
    assert "numpy.__version__.split('.')[0] == '2'" in BOOTSTRAP


def test_colab_bootstrap_persists_exact_separator_lock_and_skips_repeated_core_sync():
    assert 'SEP_LOCK_FILE = RUNTIME_DRIVE / "colab-separator-cu130.lock"' in BOOTSTRAP
    assert 'core_stamp = RUNTIME / "core-lock-sha256"' in BOOTSTRAP
    assert 'PYTHON_VERSION_FILE = RUNTIME_DRIVE / "colab-python-version.txt"' in BOOTSTRAP
    assert "actual_python_version" in BOOTSTRAP
    assert 'uv, "pip", "freeze"' in BOOTSTRAP
    assert 'uv, "pip", "sync"' in BOOTSTRAP
    assert "跳过重复安装" in BOOTSTRAP
    assert "已将分离环境精确版本保存到 Drive" in BOOTSTRAP


def test_colab_bootstrap_persists_crepe_model_but_requires_bs_roformer_from_drive():
    assert 'CREPE_MODEL_DRIVE = DRIVE / "XinsW_Models" / "CREPE" / "model-full.h5"' in BOOTSTRAP
    assert "shutil.copy2(crepe_model_path, CREPE_MODEL_DRIVE)" in BOOTSTRAP
    assert 'MODEL_DIR = DRIVE / "XinsW_Models" / "BS-RoFormer"' in BOOTSTRAP
    assert "missing = [name for name in (CHECKPOINT, CONFIG)" in BOOTSTRAP


def test_one_click_colab_notebook_uses_secret_and_verifies_published_bundle():
    assert "MUSICMASTER_WORKER_TOKEN" in NOTEBOOK
    assert "/api/internal/worker/bundle" in NOTEBOOK
    assert "hashlib.sha256" in NOTEBOOK
    assert "tarfile.open" in NOTEBOOK
    assert "bootstrap_colab_worker.py" in NOTEBOOK
    assert '"--start"' in NOTEBOOK
    assert "print(worker_token)" not in NOTEBOOK
    assert "MUSICMASTER_WORKER_ID" in NOTEBOOK


def test_colab_docs_distinguish_persistent_assets_from_ephemeral_venvs():
    assert "不需要重新下载" in DOC
    assert "colab-separator-cu130.lock" in DOC
    assert "不会自动创建或启动 GPU" in DOC
    assert "notebooks/XinsW_Colab_GPU_Worker_V1.ipynb" in DOC


def test_one_click_notebook_is_valid_json_and_its_startup_cell_compiles():
    notebook = json.loads(NOTEBOOK)
    assert notebook["nbformat"] == 4
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(code_cells) == 1
    compile("".join(code_cells[0]["source"]), "XinsW_Colab_GPU_Worker_V1.ipynb", "exec")
