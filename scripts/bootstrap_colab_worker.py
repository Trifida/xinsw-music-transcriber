#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command Colab GPU Worker bootstrap.

All interpreters, virtual environments, and uv caches live under /content.
Google Drive is used only for persistent model weights.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("/content/xinsw-runtime")
PYTHON_INSTALL = RUNTIME / "python"
UV_CACHE = RUNTIME / "uv-cache"
CORE_VENV = Path("/content/xinsw-core-venv")
SEP_VENV = Path("/content/xinsw-sep-venv")
DRIVE = Path("/content/drive/MyDrive")
MODEL_DIR = DRIVE / "XinsW_Models" / "BS-RoFormer"
CHECKPOINT = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
CONFIG = "model_bs_roformer_ep_317_sdr_12.9755.yaml"
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"


def run(command: list[str], *, env: dict[str, str], cwd: Path = ROOT) -> None:
    print("\n[Colab Bootstrap] $ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def python_in(venv: Path) -> Path:
    return venv / "bin" / "python"


def ensure_drive() -> None:
    if DRIVE.is_dir():
        return
    try:
        from google.colab import drive
    except ImportError as exc:
        raise RuntimeError("Google Drive 尚未挂载；请在 Colab 中先挂载 Drive。") from exc
    drive.mount("/content/drive")
    if not DRIVE.is_dir():
        raise RuntimeError("Drive 挂载后仍找不到 /content/drive/MyDrive。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", action="store_true",
        help="环境检查通过后直接启动 Worker（要求已设置 API URL 和 Worker token）。",
    )
    args = parser.parse_args()

    if sys.platform != "linux":
        raise RuntimeError("此初始化脚本仅用于 Google Colab Linux Runtime。")
    if not ROOT.joinpath("musicmaster/cloud/worker.py").is_file():
        raise RuntimeError("未找到项目源码；请从仓库根目录运行此脚本。")

    RUNTIME.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "UV_PYTHON_INSTALL_DIR": str(PYTHON_INSTALL),
        "UV_CACHE_DIR": str(UV_CACHE),
        "UV_LINK_MODE": "copy",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })

    uv = shutil.which("uv")
    if not uv:
        run([sys.executable, "-m", "pip", "install", "-q", "uv"], env=env)
        uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv 安装失败；请检查 Colab 网络和 pip。")

    # Python and package cache deliberately stay on the ephemeral local disk.
    run([uv, "python", "install", "3.11"], env=env)
    py311 = subprocess.check_output(
        [uv, "python", "find", "3.11"], cwd=ROOT, env=env, text=True
    ).strip()
    if not py311 or not Path(py311).is_file():
        raise RuntimeError("uv 未能定位 Python 3.11。")
    print(f"\n[Colab Bootstrap] Python 3.11: {py311}", flush=True)

    core_py = python_in(CORE_VENV)
    if not core_py.is_file():
        run([uv, "venv", "--python", py311, str(CORE_VENV)], env=env)
    sep_py = python_in(SEP_VENV)
    if not sep_py.is_file():
        run([uv, "venv", "--python", py311, str(SEP_VENV)], env=env)

    # Reconcile the core environment to the repository's validated lock.
    run([uv, "pip", "install", "--python", str(core_py), "setuptools<81", "wheel"], env=env)
    run([
        uv, "pip", "sync", "--python", str(core_py),
        str(ROOT / "requirements/locks/core-cpu.txt"),
    ], env=env)
    run([
        uv, "pip", "install", "--python", str(core_py),
        "--no-build-isolation", "--no-deps", str(ROOT / "vendor/crepe"),
    ], env=env)

    crepe_model = subprocess.check_output(
        [str(core_py), "-c",
         "import crepe.core; from pathlib import Path; "
         "print(Path(crepe.core.__file__).parent / 'model-full.h5')"],
        cwd=ROOT, env=env, text=True,
    ).strip()
    if not Path(crepe_model).is_file() or Path(crepe_model).stat().st_size < 10_000_000:
        run([str(core_py), str(ROOT / "scripts/prepare_crepe_model.py")], env=env)

    # Install LilyPond only when absent; it is required for the final jianpu PDF.
    if not shutil.which("lilypond"):
        run(["apt-get", "update", "-qq"], env=env)
        run(["apt-get", "install", "-y", "lilypond"], env=env)

    # Separate NumPy 2 / PyTorch stack from TensorFlow 2.15 (NumPy <2).
    # The exact PyTorch trio is pinned to the CUDA 13.0 wheel set.
    run([
        uv, "pip", "install", "--python", str(sep_py),
        "--index-url", TORCH_INDEX, "--extra-index-url", "https://pypi.org/simple",
        "torch==2.11.0", "torchvision==0.26.0", "torchaudio==2.11.0",
    ], env=env)
    run([
        uv, "pip", "install", "--python", str(sep_py),
        "-r", str(ROOT / "requirements/requirements-sep.txt"),
    ], env=env)
    run([
        uv, "pip", "install", "--python", str(sep_py), "audio-separator[gpu]",
    ], env=env)

    # Verify both isolated environments before attempting Worker registration.
    run([
        str(core_py), "-c",
        "import numpy, librosa, soundfile, tensorflow, crepe, hmmlearn, "
        "music21, verovio, jianpu_ly; "
        "assert numpy.__version__.startswith('1.'); "
        "import musicmaster.cloud.worker, musicmaster.workflows.full_transcribe; "
        "print('CORE_OK', tensorflow.__version__, numpy.__version__)",
    ], env=env)
    sep_probe = (
        "import torch, torchaudio, torchvision; "
        "from audio_separator.separator import Separator; "
        "assert torch.__version__.startswith('2.11.0'); "
        "assert torchaudio.__version__.startswith('2.11.0'); "
        "assert torchvision.__version__.startswith('0.26.0'); "
        "assert torch.cuda.is_available(), 'CUDA 不可用'; "
        "print('GPU_OK', torch.__version__, torchaudio.__version__, "
        "torch.cuda.get_device_name(0))"
    )
    run([str(sep_py), "-c", sep_probe], env=env)

    ensure_drive()
    missing = [name for name in (CHECKPOINT, CONFIG) if not (MODEL_DIR / name).is_file()]
    if missing:
        raise RuntimeError(
            "BS-RoFormer 模型文件缺失，请放入 " + str(MODEL_DIR) + "："
            + "、".join(missing)
        )

    env["MUSICMASTER_SEP_PYTHON"] = str(sep_py)
    env["MUSICMASTER_SEP_MODELS"] = str(MODEL_DIR)
    env["MUSICMASTER_WORKER_DATA"] = "/content/xinsw-worker-tmp"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    print("\n[Colab Bootstrap] 环境初始化与检查全部通过。", flush=True)
    print(f"[Colab Bootstrap] 核心 Python：{core_py}", flush=True)
    print(f"[Colab Bootstrap] 分离 Python：{sep_py}", flush=True)
    print(f"[Colab Bootstrap] GPU：CUDA 可用；模型目录：{MODEL_DIR}", flush=True)

    if args.start:
        if not env.get("MUSICMASTER_API_URL", "").strip():
            raise RuntimeError("缺少 MUSICMASTER_API_URL 环境变量。")
        if not env.get("MUSICMASTER_WORKER_TOKEN", "").strip():
            raise RuntimeError("缺少 MUSICMASTER_WORKER_TOKEN；请从 Colab Secrets 注入。")
        print("[Colab Bootstrap] 正在启动 Worker；按 Colab 停止按钮可结束。", flush=True)
        os.execve(str(core_py), [str(core_py), str(ROOT / "scripts/run_colab_cloud_worker.py")], env)

    print("\n下一步：设置 MUSICMASTER_API_URL 和 MUSICMASTER_WORKER_TOKEN 后，")
    print("重新运行本脚本并加参数 --start，即可启动 Worker。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\n[Colab Bootstrap] 命令失败（退出码 {exc.returncode}）：{exc.cmd}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[Colab Bootstrap] 初始化失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
