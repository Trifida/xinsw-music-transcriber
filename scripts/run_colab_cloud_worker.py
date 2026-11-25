#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the durable cloud worker inside an already-allocated Google Colab GPU runtime.

This launcher never provisions, powers on, shuts down, or releases a GPU. It
refuses to register a worker unless the current Python process has CUDA, the
separation/transcription dependencies are importable, and the Drive model
directory is present. It performs no pip installs and downloads no weights.
"""
from __future__ import annotations

import importlib.util
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


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _fail(message: str, code: int = 2) -> int:
    print(f"[Colab Worker] 未启动：{message}", file=sys.stderr, flush=True)
    return code


def validate_runtime() -> tuple[str, str] | int:
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

    required_modules = ("audio_separator", "tensorflow", "crepe", "hmmlearn", "music21")
    missing = [name for name in required_modules if not _module_available(name)]
    if missing:
        return _fail(
            "当前环境缺少必要模块：" + "、".join(missing)
            + "。请先按已核验的 Colab 依赖方案准备环境；本脚本不会自动安装。"
        )

    if not Path("/content/drive/MyDrive").is_dir():
        return _fail("Google Drive 尚未挂载，找不到 /content/drive/MyDrive。")

    model_dir = Path(os.environ.get("MUSICMASTER_SEP_MODELS", str(DEFAULT_MODEL_DIR))).expanduser()
    for filename in (CHECKPOINT, CONFIG):
        if not (model_dir / filename).is_file():
            return _fail(f"模型文件缺失：{model_dir / filename}")

    api_url = os.environ.get("MUSICMASTER_API_URL", "").strip().rstrip("/")
    token = os.environ.get("MUSICMASTER_WORKER_TOKEN", "").strip()
    parsed = urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return _fail("请先设置 HTTPS 格式的 MUSICMASTER_API_URL。")
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

    # The worker and its separation subprocess must import this exact checkout.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    print("[Colab Worker] 依赖与模型目录检查通过。", flush=True)
    print(f"[Colab Worker] 模型目录：{model_dir.resolve()}", flush=True)
    print(f"[Colab Worker] Worker ID：{os.environ['MUSICMASTER_WORKER_ID']}", flush=True)
    print(f"[Colab Worker] API 主机：{parsed.netloc}", flush=True)
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
