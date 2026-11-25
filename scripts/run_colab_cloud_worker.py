#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the durable cloud worker inside an already-allocated Google Colab GPU runtime.

This launcher never provisions, powers on, shuts down, or releases a GPU. It
performs real import checks for the complete V1 processing stack and confirms
that the separation subprocess will use this same CUDA-enabled interpreter.
It performs no pip installs and downloads no weights.
"""
from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DRIVE_ROOT = Path("/content/drive/MyDrive")
DEFAULT_MODEL_DIR = DRIVE_ROOT / "XinsW_Models" / "BS-RoFormer"
CHECKPOINT = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
CONFIG = "model_bs_roformer_ep_317_sdr_12.9755.yaml"

# Import the concrete modules used by the actual full-song processing path.
# Importing only the audio_separator package root is insufficient: the
# Separator class and torchaudio can still fail later when the first job starts.
REQUIRED_MODULES = (
    "numpy",
    "librosa",
    "soundfile",
    "torch",
    "torchaudio",
    "audio_separator.separator",
    "tensorflow",
    "crepe",
    "hmmlearn",
    "music21",
)
PROJECT_MODULES = (
    "musicmaster.cloud.worker",
    "musicmaster.workflows.full_transcribe",
    "musicmaster.separate.pipeline",
    "musicmaster.transcribe.autopilot",
)


def _fail(message: str, code: int = 2) -> int:
    print(f"[Colab Worker] 未启动：{message}", file=sys.stderr, flush=True)
    return code


def _import_runtime_modules() -> tuple[dict[str, object], list[str]]:
    loaded: dict[str, object] = {}
    errors: list[str] = []
    for name in REQUIRED_MODULES:
        try:
            loaded[name] = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — report the actual broken dependency
            errors.append(f"{name} ({type(exc).__name__}: {str(exc)[:160]})")
    return loaded, errors


def validate_runtime() -> tuple[str, str] | int:
    if sys.version_info < (3, 10):
        return _fail("项目要求 Python 3.10 或更高版本。")

    # Check GPU first. A CPU runtime must never register as an available GPU worker.
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        return _fail(f"无法导入 PyTorch：{type(exc).__name__}: {exc}")

    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        return _fail(
            "当前 Colab 运行时没有分配可用 CUDA GPU。请在 Colab 选择 GPU 运行时后再启动；"
            "本脚本不会创建或启动 GPU。"
        )
    if not getattr(torch.version, "cuda", None):
        return _fail("当前 PyTorch 是 CPU 版本，不包含 CUDA 支持。")

    device_name = torch.cuda.get_device_name(0)
    device_props = torch.cuda.get_device_properties(0)
    memory_gib = round(device_props.total_memory / (1024 ** 3), 2)
    print(f"[Colab Worker] GPU：{device_name}，显存 {memory_gib} GiB", flush=True)

    modules, import_errors = _import_runtime_modules()
    if import_errors:
        return _fail(
            "完整乐曲流程依赖导入失败：" + "；".join(import_errors)
            + "。请按已核验的 Colab 环境方案修复；本脚本不会自动安装或升级依赖。"
        )
    if not hasattr(modules["audio_separator.separator"], "Separator"):
        return _fail("audio_separator.separator 已导入，但找不到 Separator 类。")

    if not DRIVE_ROOT.is_dir():
        return _fail("Google Drive 尚未挂载，找不到 /content/drive/MyDrive。")

    model_dir = Path(os.environ.get("MUSICMASTER_SEP_MODELS", str(DEFAULT_MODEL_DIR))).expanduser()
    missing_required = [
        str(model_dir / filename) for filename in (CHECKPOINT, CONFIG)
        if not (model_dir / filename).is_file()
    ]
    if missing_required:
        return _fail("BS-RoFormer 必需文件缺失：" + "、".join(missing_required))

    api_url = os.environ.get("MUSICMASTER_API_URL", "").strip().rstrip("/")
    token = os.environ.get("MUSICMASTER_WORKER_TOKEN", "").strip()
    parsed = urlsplit(api_url)
    if (parsed.scheme != "https" or not parsed.netloc
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        return _fail("MUSICMASTER_API_URL 必须是 API 根地址，例如 https://你的服务.onrender.com（不要附加 /api 路径）。")
    if not token:
        return _fail(
            "未设置 MUSICMASTER_WORKER_TOKEN。请通过 Colab Secrets 安全提供已有 Worker 凭据；"
            "不要把凭据写进 Notebook 单元或提交到 GitHub。"
        )

    sep_python = os.environ.get("MUSICMASTER_SEP_PYTHON", "").strip()
    if sep_python and Path(sep_python).resolve() != Path(sys.executable).resolve():
        return _fail(
            "MUSICMASTER_SEP_PYTHON 指向了另一个 Python 环境；"
            "Colab Worker 必须使用当前已验证 CUDA 的解释器。"
        )

    os.environ["MUSICMASTER_SEP_PYTHON"] = sys.executable
    os.environ["MUSICMASTER_SEP_MODELS"] = str(model_dir.resolve())
    os.environ.setdefault("MUSICMASTER_WORKER_ID", "colab-" + socket.gethostname()[:100])
    os.environ.setdefault("MUSICMASTER_WORKER_DATA", "/content/xinsw-worker-tmp")
    os.environ.setdefault("MUSICMASTER_WORKER_POLL_SECONDS", "5")

    # Import the real project entrypoints only after environment paths are set.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        for module_name in PROJECT_MODULES:
            importlib.import_module(module_name)
        from musicmaster.web.runners import _sep_python
        resolved_sep_python = _sep_python()
    except Exception as exc:  # noqa: BLE001
        return _fail(f"项目工作流导入失败：{type(exc).__name__}: {str(exc)[:200]}")

    if not resolved_sep_python:
        return _fail("分离子进程没有找到 Python 解释器，MUSICMASTER_SEP_PYTHON 未生效。")
    if Path(resolved_sep_python).resolve() != Path(sys.executable).resolve():
        return _fail(
            "分离子进程解析到的 Python 与当前 CUDA Python 不一致："
            f"{resolved_sep_python}"
        )

    # Stage 2/3 weights may be fetched by audio-separator on first use. Warn,
    # rather than blocking registration: stage 1's BS-RoFormer is the required
    # persistent model already checked above.
    try:
        from musicmaster.separate import pipeline
        optional_models = (
            *pipeline.DEHARMONY_MODELS.values(),
            *pipeline.DENOISE_MODELS.values(),
        )
        missing_optional = [name for name in optional_models if not (model_dir / name).is_file()]
    except Exception:
        missing_optional = []

    print("[Colab Worker] 完整乐曲工作流依赖导入通过。", flush=True)
    print(f"[Colab Worker] Python：{sys.executable}", flush=True)
    print(f"[Colab Worker] PyTorch：{modules['torch'].__version__}；"
          f"torchaudio：{modules['torchaudio'].__version__}；"
          f"TensorFlow：{modules['tensorflow'].__version__}", flush=True)
    print(f"[Colab Worker] 模型目录：{model_dir.resolve()}", flush=True)
    if missing_optional:
        print(
            "[Colab Worker] 提醒：以下去和声/降噪模型尚未缓存，首次运行相应阶段时 "
            "audio-separator 可能需要联网下载：" + "、".join(missing_optional),
            flush=True,
        )
    print(f"[Colab Worker] Worker ID：{os.environ['MUSICMASTER_WORKER_ID']}", flush=True)
    print(f"[Colab Worker] API 主机：{parsed.netloc}", flush=True)
    print("[Colab Worker] 分离子进程已确认使用当前 CUDA Python。", flush=True)
    print("[Colab Worker] 不会创建 GPU；按 Ctrl+C 可停止本次 Worker。", flush=True)
    return api_url, device_name


def main() -> int:
    result = validate_runtime()
    if isinstance(result, int):
        return result
    from musicmaster.cloud.worker import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
