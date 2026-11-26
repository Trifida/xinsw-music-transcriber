#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command Colab GPU Worker bootstrap.

All interpreters, virtual environments, and uv caches live under /content.
Google Drive is used only for persistent model weights.
"""
from __future__ import annotations

import argparse
import hashlib
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
RUNTIME_DRIVE = DRIVE / "XinsW_Runtime"
SEP_LOCK_FILE = RUNTIME_DRIVE / "colab-separator-cu130.lock"
PYTHON_VERSION_FILE = RUNTIME_DRIVE / "colab-python-version.txt"
CREPE_MODEL_DRIVE = DRIVE / "XinsW_Models" / "CREPE" / "model-full.h5"


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

    ensure_drive()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    RUNTIME_DRIVE.mkdir(parents=True, exist_ok=True)
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

    # Pin the exact Python 3.11 patch version after the first successful
    # resolution. The interpreter remains local to this Runtime; only its
    # version string is persisted in Drive.
    if PYTHON_VERSION_FILE.is_file():
        python_version = PYTHON_VERSION_FILE.read_text(encoding="ascii").strip()
        parts = python_version.split(".")
        if len(parts) != 3 or parts[:2] != ["3", "11"] or not parts[2].isdigit():
            raise RuntimeError("Drive 中记录的 Python 版本无效：" + python_version)
    else:
        python_version = "3.11"
    run([uv, "python", "install", python_version], env=env)
    py311 = subprocess.check_output(
        [uv, "python", "find", python_version], cwd=ROOT, env=env, text=True
    ).strip()
    if not py311 or not Path(py311).is_file():
        raise RuntimeError("uv 未能定位 Python 3.11。")
    actual_python_version = subprocess.check_output(
        [py311, "-c", "import platform; print(platform.python_version())"],
        cwd=ROOT, env=env, text=True,
    ).strip()
    if PYTHON_VERSION_FILE.is_file() and actual_python_version != python_version:
        raise RuntimeError("Python 版本与 Drive 中固定的版本不一致。")
    if not PYTHON_VERSION_FILE.is_file():
        PYTHON_VERSION_FILE.write_text(actual_python_version + "\n", encoding="ascii")
    print(f"\n[Colab Bootstrap] Python：{actual_python_version}（版本已记录到 Drive）", flush=True)

    core_py = python_in(CORE_VENV)
    if not core_py.is_file():
        run([uv, "venv", "--python", py311, str(CORE_VENV)], env=env)
    sep_py = python_in(SEP_VENV)
    if not sep_py.is_file():
        run([uv, "venv", "--python", py311, str(SEP_VENV)], env=env)

    # Reconcile the core environment only when its committed lock changes or
    # the installed environment fails its import probe. Reruns are then cheap.
    core_lock = ROOT / "requirements/locks/core-cpu.txt"
    core_lock_sha = hashlib.sha256(core_lock.read_bytes()).hexdigest()
    core_stamp = RUNTIME / "core-lock-sha256"
    core_probe = (
        "import numpy, librosa, soundfile, tensorflow, hmmlearn, music21, "
        "verovio, jianpu_ly; "
        "assert numpy.__version__.startswith('1.'); "
        "assert tensorflow.__version__.startswith('2.15.')"
    )
    core_is_ready = (
        core_py.is_file()
        and core_stamp.is_file()
        and core_stamp.read_text(encoding="ascii").strip() == core_lock_sha
        and subprocess.run(
            [str(core_py), "-c", core_probe], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
    )
    if not core_is_ready:
        print("[Colab Bootstrap] 核心环境首次安装或锁文件已变化，开始同步依赖。", flush=True)
        run([uv, "pip", "install", "--python", str(core_py), "setuptools<81", "wheel"], env=env)
        run([uv, "pip", "sync", "--python", str(core_py), str(core_lock)], env=env)
        # pip sync may remove build tools not listed in the runtime lock.
        run([uv, "pip", "install", "--python", str(core_py), "setuptools<81", "wheel"], env=env)
        run([
            uv, "pip", "install", "--python", str(core_py),
            "--no-build-isolation", "--no-deps", str(ROOT / "vendor/crepe"),
        ], env=env)
        core_stamp.write_text(core_lock_sha, encoding="ascii")
    else:
        print("[Colab Bootstrap] 核心环境锁文件未变化且导入检查通过，跳过重复安装。", flush=True)

    crepe_model = subprocess.check_output(
        [str(core_py), "-c",
         "import crepe.core; from pathlib import Path; "
         "print(Path(crepe.core.__file__).parent / 'model-full.h5')"],
        cwd=ROOT, env=env, text=True,
    ).strip()
    crepe_model_path = Path(crepe_model)
    if CREPE_MODEL_DRIVE.is_file() and CREPE_MODEL_DRIVE.stat().st_size >= 10_000_000:
        if (not crepe_model_path.is_file()
                or crepe_model_path.stat().st_size != CREPE_MODEL_DRIVE.stat().st_size):
            crepe_model_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CREPE_MODEL_DRIVE, crepe_model_path)
        print("[Colab Bootstrap] 已从 Drive 恢复 CREPE 模型缓存。", flush=True)
    else:
        if not crepe_model_path.is_file() or crepe_model_path.stat().st_size < 10_000_000:
            run([str(core_py), str(ROOT / "scripts/prepare_crepe_model.py")], env=env)
        if crepe_model_path.is_file() and crepe_model_path.stat().st_size >= 10_000_000:
            CREPE_MODEL_DRIVE.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(crepe_model_path, CREPE_MODEL_DRIVE)
            print("[Colab Bootstrap] CREPE 模型已备份到 Google Drive。", flush=True)

    # Install LilyPond only when absent; it is required for the final jianpu PDF.
    if not shutil.which("lilypond"):
        run(["apt-get", "update", "-qq"], env=env)
        run(["apt-get", "install", "-y", "lilypond"], env=env)

    # The first successful setup writes an exact dependency lock to Drive.
    # Every later Runtime rebuilds the ephemeral venv from that same lock.
    sep_probe_lock = (
        "import torch, torchaudio, torchvision, numpy; "
        "from audio_separator.separator import Separator; "
        "assert torch.__version__.startswith('2.11.0'); "
        "assert '+cpu' not in torch.__version__; "
        "assert torch.version.cuda is not None; "
        "assert torchaudio.__version__.startswith('2.11.0'); "
        "assert torchvision.__version__.startswith('0.26.0'); "
        "assert numpy.__version__.split('.')[0] == '2'; "
        "assert torch.cuda.is_available()"
    )
    if SEP_LOCK_FILE.is_file():
        print("[Colab Bootstrap] 使用 Drive 中固定的 CUDA 分离环境锁文件。", flush=True)
        run([
            uv, "pip", "sync", "--python", str(sep_py),
            "--index-strategy", "first-index",
            "--index-url", TORCH_INDEX, "--extra-index-url", "https://pypi.org/simple",
            str(SEP_LOCK_FILE),
        ], env=env)
    else:
        print("[Colab Bootstrap] 首次安装 CUDA 分离环境，完成后将精确版本锁定到 Drive。", flush=True)
        run([
            uv, "pip", "install", "--python", str(sep_py),
            "--reinstall", "--index-strategy", "first-index",
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
        freeze = subprocess.check_output(
            [uv, "pip", "freeze", "--python", str(sep_py)],
            cwd=ROOT, env=env, text=True,
        )
        if "torch==2.11.0" not in freeze or "torchaudio==2.11.0" not in freeze:
            raise RuntimeError("分离环境导出的锁文件未包含预期 PyTorch 版本。")
        SEP_LOCK_FILE.write_text(freeze, encoding="utf-8")
        print(f"[Colab Bootstrap] 已将分离环境精确版本保存到 Drive：{SEP_LOCK_FILE}", flush=True)

    sep_lock_check = subprocess.run(
        [str(sep_py), "-c", sep_probe_lock], cwd=ROOT, env=env,
        capture_output=True, text=True, check=False,
    )
    if sep_lock_check.returncode != 0:
        detail = (sep_lock_check.stderr or sep_lock_check.stdout or "无详细错误").strip()[-1200:]
        raise RuntimeError("CUDA 分离环境未通过检查：" + detail)

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
        "print('TORCH_VERSION=', torch.__version__); "
        "print('TORCH_CUDA_BUILD=', torch.version.cuda); "
        "print('TORCHAUDIO_VERSION=', torchaudio.__version__); "
        "print('TORCHVISION_VERSION=', torchvision.__version__); "
        "print('CUDA_AVAILABLE=', torch.cuda.is_available()); "
        "print('CUDA_DEVICE_COUNT=', torch.cuda.device_count()); "
        "assert torch.__version__.startswith('2.11.0'); "
        "assert '+cpu' not in torch.__version__, '安装到了 CPU-only PyTorch'; "
        "assert torch.version.cuda is not None, 'PyTorch 本身不是 CUDA 构建'; "
        "assert torchaudio.__version__.startswith('2.11.0'); "
        "assert torchvision.__version__.startswith('0.26.0'); "
        "assert torch.cuda.is_available(), 'CUDA 构建已安装，但驱动/GPU 不可用'; "
        "print('GPU_OK', torch.cuda.get_device_name(0), "
        "torch.cuda.get_device_capability(0))"
    )
    run([str(sep_py), "-c", sep_probe], env=env)

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
        if not (
            env.get("MUSICMASTER_WORKER_TOKEN", "").strip()
            or env.get("MUSICMASTER_BOOTSTRAP_TOKEN", "").strip()
        ):
            raise RuntimeError(
                "缺少 Worker 凭据；请从 Colab Secrets 注入 MUSICMASTER_WORKER_TOKEN "
                "或短时 MUSICMASTER_BOOTSTRAP_TOKEN。"
            )
        print("[Colab Bootstrap] 正在启动 Worker；按 Colab 停止按钮可结束。", flush=True)
        os.execve(str(core_py), [str(core_py), str(ROOT / "scripts/run_colab_cloud_worker.py")], env)

    print("\n下一步：设置 MUSICMASTER_API_URL，以及以下任一凭据：")
    print("MUSICMASTER_WORKER_TOKEN（长期 Worker 凭据）或 MUSICMASTER_BOOTSTRAP_TOKEN（一次性短时凭据）。")
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
