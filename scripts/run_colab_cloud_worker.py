#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the durable worker with separate core and audio-separation environments.

This launcher never provisions, powers on, shuts down, or releases a GPU. Core
transcription dependencies stay isolated from the NumPy 2 / PyTorch separator
stack. It performs import checks but no pip installs and downloads no weights.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DRIVE_ROOT = Path("/content/drive/MyDrive")
DEFAULT_MODEL_DIR = DRIVE_ROOT / "XinsW_Models" / "BS-RoFormer"
CHECKPOINT = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
CONFIG = "model_bs_roformer_ep_317_sdr_12.9755.yaml"
BUNDLE_CACHE_ROOT = Path(
    os.environ.get("MUSICMASTER_WORKER_BUNDLE_CACHE", "/content/xinsw-worker-bundles")
)

# Modules imported directly by the core transcription / worker process.
# PyTorch and audio-separator are checked in the dedicated separator venv below.
REQUIRED_MODULES = (
    "numpy",
    "librosa",
    "soundfile",
    "tensorflow",
    "crepe",
    "hmmlearn",
    "music21",
    "verovio",
    "jianpu_ly",
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

    # Core transcription runs in the Python 3.11 core environment.
    # Audio separation intentionally runs in its own environment because its
    # current dependency stack requires NumPy 2 while core TensorFlow 2.15
    # requires NumPy <2. Never mix these incompatible stacks.
    modules, import_errors = _import_runtime_modules()
    if import_errors:
        return _fail(
            "完整乐曲流程依赖导入失败：" + "；".join(import_errors)
            + "。请按已核验的 Colab 环境方案修复；本脚本不会自动安装或升级依赖。"
        )
    if not shutil.which("lilypond"):
        return _fail(
            "未找到 LilyPond。完整歌曲必须生成简谱 PDF；请先在 Colab 单元执行 "
            "`!apt-get update -qq && apt-get install -y lilypond`，再重新启动 Worker。"
        )
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
    bootstrap_token = os.environ.get("MUSICMASTER_BOOTSTRAP_TOKEN", "").strip()
    parsed = urlsplit(api_url)
    if (parsed.scheme != "https" or not parsed.netloc
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        return _fail("MUSICMASTER_API_URL 必须是 API 根地址，例如 https://你的服务.onrender.com（不要附加 /api 路径）。")
    if not token and not bootstrap_token:
        return _fail(
            "未设置 Worker 凭据。请通过 Colab Secrets 提供 MUSICMASTER_WORKER_TOKEN，"
            "或提供短时一次性的 MUSICMASTER_BOOTSTRAP_TOKEN；"
            "不要把凭据写进 Notebook 单元或提交到 GitHub。"
        )

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

    if not resolved_sep_python or not Path(resolved_sep_python).is_file():
        return _fail(
            "没有找到独立的人声分离 Python 环境。请设置 MUSICMASTER_SEP_PYTHON，"
            "指向 /content/xinsw-sep-venv/bin/python。"
        )

    # Probe the dedicated separator environment separately. Its NumPy/PyTorch
    # stack must not be imported into the TensorFlow 2.15 core environment.
    probe_code = (
        "import torch, torchaudio; "
        "from audio_separator.separator import Separator; "
        "print('TORCH=' + torch.__version__); "
        "print('TORCHAUDIO=' + torchaudio.__version__); "
        "print('DEVICE=' + (torch.cuda.get_device_name(0) if "
        "torch.cuda.is_available() and torch.cuda.device_count() else 'CPU'))"
    )
    try:
        probe = subprocess.run(
            [resolved_sep_python, "-c", probe_code],
            capture_output=True, text=True, timeout=90, check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"分离环境检查失败：{type(exc).__name__}: {str(exc)[:200]}")
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "无详细错误").strip()[-500:]
        return _fail(f"分离环境无法导入 PyTorch / torchaudio / audio-separator：{detail}")

    sep_lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    sep_info = {line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in sep_lines if "=" in line}
    if not all(key in sep_info for key in ("TORCH", "TORCHAUDIO", "DEVICE")):
        return _fail("分离环境检查没有返回完整版本信息。")
    device_name = sep_info["DEVICE"]
    os.environ["MUSICMASTER_SEP_PYTHON"] = str(Path(resolved_sep_python).resolve())

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
    print(f"[Colab Worker] 核心 TensorFlow：{modules['tensorflow'].__version__}", flush=True)
    print(f"[Colab Worker] 分离环境 PyTorch：{sep_info['TORCH']}；"
          f"torchaudio：{sep_info['TORCHAUDIO']}；设备：{device_name}", flush=True)
    print(f"[Colab Worker] 模型目录：{model_dir.resolve()}", flush=True)
    if missing_optional:
        print(
            "[Colab Worker] 提醒：以下去和声/降噪模型尚未缓存，首次运行相应阶段时 "
            "audio-separator 可能需要联网下载：" + "、".join(missing_optional),
            flush=True,
        )
    print(f"[Colab Worker] Worker ID：{os.environ['MUSICMASTER_WORKER_ID']}", flush=True)
    print(f"[Colab Worker] API 主机：{parsed.netloc}", flush=True)
    print("[Colab Worker] 分离子进程已确认使用独立分离 Python 环境。", flush=True)
    print("[Colab Worker] 不会创建 GPU；按 Ctrl+C 可停止本次 Worker。", flush=True)
    return api_url, device_name


def _activate_published_source_bundle() -> None:
    """Fetch, verify and re-exec from the API-pinned immutable source bundle."""
    if os.environ.get("MUSICMASTER_SOURCE_BUNDLE_ACTIVE", "").strip():
        return

    api_url = os.environ.get("MUSICMASTER_API_URL", "").strip().rstrip("/")
    if not api_url:
        raise RuntimeError("MUSICMASTER_API_URL is required before source bundle activation.")

    # _config exchanges a short-lived bootstrap token when no long-lived token
    # is present. The credential remains in process memory/environment only.
    from musicmaster.cloud.worker import _config
    base, token, _, _ = _config()

    request = urllib.request.Request(
        base + "/api/internal/worker/bundle",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            manifest = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Could not obtain published Worker source bundle: {type(exc).__name__}"
        ) from None

    commit = str(manifest.get("repository_commit") or "").lower()
    digest = str(manifest.get("sha256") or "").lower()
    url = str(manifest.get("url") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Published Worker source bundle has an invalid commit SHA.")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Published Worker source bundle has an invalid SHA-256.")
    if not url.startswith("https://"):
        raise RuntimeError("Published Worker source bundle URL must use HTTPS.")

    cache_root = BUNDLE_CACHE_ROOT
    target = cache_root / commit
    marker = target / ".xinsw-bundle-sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == digest:
        bundle_root = target
    else:
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xinsw-bundle-") as temp:
            archive_path = Path(temp) / "worker.tar.gz"
            download = urllib.request.Request(url, headers={"User-Agent": "XinsW-Music-Worker/1"})
            try:
                with urllib.request.urlopen(download, timeout=600) as response, archive_path.open("wb") as out:
                    shutil.copyfileobj(response, out, length=1024 * 1024)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Worker source bundle download failed: {type(exc).__name__}"
                ) from None

            hasher = hashlib.sha256()
            with archive_path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != digest:
                raise RuntimeError("Worker source bundle SHA-256 mismatch.")

            staging = Path(temp) / "extracted"
            staging.mkdir()
            expanded_bytes = 0
            try:
                with tarfile.open(archive_path, "r:gz") as archive:
                    members = archive.getmembers()
                    roots = {PurePosixPath(item.name).parts[0] for item in members if PurePosixPath(item.name).parts}
                    if len(roots) != 1:
                        raise RuntimeError("Worker source archive has an unexpected root layout.")
                    root_prefix = next(iter(roots))
                    for item in members:
                        member_path = PurePosixPath(item.name)
                        if member_path.is_absolute() or ".." in member_path.parts:
                            raise RuntimeError("Worker source archive contains an unsafe path.")
                        parts = member_path.parts[1:]
                        if not parts:
                            continue
                        destination = staging.joinpath(*parts)
                        if item.isdir():
                            destination.mkdir(parents=True, exist_ok=True)
                        elif item.isfile():
                            expanded_bytes += int(item.size)
                            if expanded_bytes > 1024 * 1024 * 1024:
                                raise RuntimeError("Worker source archive expands beyond 1 GiB.")
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            source_file = archive.extractfile(item)
                            if source_file is None:
                                raise RuntimeError("Worker source archive contains an unreadable file.")
                            with source_file, destination.open("wb") as out:
                                shutil.copyfileobj(source_file, out, length=1024 * 1024)
                            destination.chmod(item.mode & 0o755)
                        else:
                            raise RuntimeError("Worker source archive contains an unsupported link or special file.")
            except (tarfile.TarError, OSError) as exc:
                raise RuntimeError(
                    f"Worker source archive extraction failed: {type(exc).__name__}"
                ) from None

            if not (staging / "musicmaster/cloud/worker.py").is_file():
                raise RuntimeError("Published Worker source bundle is missing its worker entrypoint.")
            if not (staging / "scripts/run_colab_cloud_worker.py").is_file():
                raise RuntimeError("Published Worker source bundle is missing its Colab launcher.")
            (staging / ".xinsw-bundle-sha256").write_text(digest, encoding="ascii")
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
            bundle_root = target

    launcher = bundle_root / "scripts/run_colab_cloud_worker.py"
    if not launcher.is_file():
        raise RuntimeError("Verified Worker source bundle does not contain its launcher.")
    env = os.environ.copy()
    env["MUSICMASTER_SOURCE_BUNDLE_ACTIVE"] = commit
    env["PYTHONPATH"] = str(bundle_root) + os.pathsep + env.get("PYTHONPATH", "")
    print(
        f"[Colab Worker] 已验证并切换到固定源码版本 {commit[:12]}（SHA-256 校验通过）。",
        flush=True,
    )
    os.execve(sys.executable, [sys.executable, str(launcher)], env)


def main() -> int:
    _activate_published_source_bundle()
    result = validate_runtime()
    if isinstance(result, int):
        return result
    from musicmaster.cloud.worker import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
