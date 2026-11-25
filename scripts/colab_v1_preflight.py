#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only preflight for the XinsW Music Transcriber V1 Google Colab runtime.

This script deliberately does not install packages, download models, start/stop
GPU runtimes, modify Drive files, or launch inference. It only inspects the
current runtime and prints a JSON report suitable for a handoff.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from datetime import datetime, timezone
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DRIVE_ROOT = Path("/content/drive/MyDrive")
MODEL_ROOT = DRIVE_ROOT / "XinsW_Models" / "BS-RoFormer"
BS_ROFORMER_FILES = (
    MODEL_ROOT / "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    MODEL_ROOT / "model_bs_roformer_ep_317_sdr_12.9755.yaml",
    MODEL_ROOT / "download_checks.json",
)
IMPORTANT_DRIVE_DIRS = (
    DRIVE_ROOT / "XinsW_Models",
    DRIVE_ROOT / "XinsW_Lead_Transcription",
    DRIVE_ROOT / "XinsW_GPU_Results",
    DRIVE_ROOT / "Colab Notebooks",
)
EPHEMERAL_MODEL_DIRS = (
    Path("/content/VocalParse_Test/models/VocalParse"),
    Path("/content/VocalParse_Test/models/Qwen3-ASR-1.7B"),
)
MODULES = (
    "torch",
    "torchaudio",
    "tensorflow",
    "audio_separator",
    "crepe",
    "torchcrepe",
    "basic_pitch",
    "librosa",
    "soundfile",
    "music21",
    "verovio",
    "jianpu",
    "fastapi",
)


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception as exc:  # metadata corruption should not abort the report
        return f"ERROR: {type(exc).__name__}: {exc}"


def _module_status(name: str) -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec(name)
        return {
            "available": spec is not None,
            "origin": getattr(spec, "origin", None) if spec else None,
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _path_status(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
    }
    if path.is_file():
        try:
            result["size_bytes"] = path.stat().st_size
        except OSError as exc:
            result["stat_error"] = str(exc)
    if path.is_dir():
        try:
            result["children"] = [
                {"name": child.name, "is_dir": child.is_dir()}
                for child in sorted(path.iterdir(), key=lambda item: item.name)[:30]
            ]
            result["children_truncated"] = sum(1 for _ in path.iterdir()) > 30
        except OSError as exc:
            result["list_error"] = str(exc)
    return result


def _command_version(command: str, args: list[str]) -> dict[str, Any]:
    executable = shutil.which(command)
    if not executable:
        return {"available": False}
    try:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = (completed.stdout or completed.stderr).strip()
        return {
            "available": True,
            "executable": executable,
            "return_code": completed.returncode,
            "output": output[:2000],
        }
    except Exception as exc:
        return {"available": True, "executable": executable, "error": f"{type(exc).__name__}: {exc}"}


def _git_status(repo: Path) -> dict[str, Any]:
    if not (repo / ".git").exists():
        return {"repository_found": False, "path": str(repo)}
    result: dict[str, Any] = {"repository_found": True, "path": str(repo)}
    for key, args in (
        ("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
        ("commit", ["rev-parse", "HEAD"]),
        ("working_tree", ["status", "--short"]),
        ("remote", ["remote", "get-url", "origin"]),
    ):
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            result[key] = (completed.stdout or completed.stderr).strip()[:2000]
        except Exception as exc:
            result[key] = f"ERROR: {type(exc).__name__}: {exc}"
    return result


def inspect_torch() -> dict[str, Any]:
    try:
        import torch

        info: dict[str, Any] = {
            "version": getattr(torch, "__version__", None),
            "cuda_build": getattr(getattr(torch, "version", None), "cuda", None),
            "cuda_available": bool(torch.cuda.is_available()),
            "device_count": int(torch.cuda.device_count()),
        }
        if info["cuda_available"]:
            devices = []
            for index in range(info["device_count"]):
                props = torch.cuda.get_device_properties(index)
                devices.append(
                    {
                        "index": index,
                        "name": props.name,
                        "total_memory_bytes": int(props.total_memory),
                        "total_memory_gib": round(props.total_memory / (1024**3), 2),
                        "compute_capability": f"{props.major}.{props.minor}",
                    }
                )
            info["devices"] = devices
        return info
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def inspect_tensorflow() -> dict[str, Any]:
    try:
        import tensorflow as tf

        return {
            "version": tf.__version__,
            "built_with_cuda": bool(tf.test.is_built_with_cuda()),
            "physical_gpus": [
                {"name": device.name, "device_type": device.device_type}
                for device in tf.config.list_physical_devices("GPU")
            ],
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def build_report() -> dict[str, Any]:
    repo_path = Path("/content/xinsw-music-transcriber")
    packages = {
        name: _version(name)
        for name in (
            "numpy",
            "scipy",
            "librosa",
            "soundfile",
            "torch",
            "torchaudio",
            "tensorflow",
            "audio-separator",
            "crepe",
            "torchcrepe",
            "basic-pitch",
            "music21",
            "verovio",
            "jianpu-ly",
            "fastapi",
        )
    }

    report: dict[str, Any] = {
        "report_type": "xinsw_colab_v1_preflight",
        "read_only": True,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "python": sys.version,
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "working_directory": os.getcwd(),
            "colab_environment": bool(os.environ.get("COLAB_RELEASE_TAG")),
            "nvidia_smi": _command_version("nvidia-smi", ["-q"]),
            "git": _command_version("git", ["--version"]),
        },
        "gpu": {
            "torch": inspect_torch(),
            "tensorflow": inspect_tensorflow(),
        },
        "packages": packages,
        "modules": {name: _module_status(name) for name in MODULES},
        "drive": {
            "mounted": (DRIVE_ROOT / ".").exists(),
            "important_directories": [
                _path_status(path) for path in IMPORTANT_DRIVE_DIRS
            ],
            "bs_roformer_files": [
                _path_status(path) for path in BS_ROFORMER_FILES
            ],
            "ephemeral_model_directories": [
                _path_status(path) for path in EPHEMERAL_MODEL_DIRS
            ],
        },
        "project": _git_status(repo_path),
        "notes": [
            "This report does not install or upgrade any package.",
            "This report does not download, move, delete, or overwrite model/audio files.",
            "This report does not start, stop, or provision any GPU runtime.",
            "ASR/Qwen model presence is recorded for inventory only; ASR is outside V1.",
            "A package being installed does not prove that its model inference works.",
        ],
    }

    python_version = tuple(sys.version_info[:2])
    tf_version = packages.get("tensorflow")
    if python_version >= (3, 12):
        report["compatibility_warnings"] = [
            "This runtime uses Python 3.12+. The repository's legacy transcription dependency set pins TensorFlow 2.15.0, which is not a compatible target for Python 3.12+. Do not install that pinned set into this interpreter; first select a tested environment strategy."
        ]
    else:
        report["compatibility_warnings"] = []

    return report


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
