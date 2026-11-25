#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""建独立分离环境：audio-separator + CPU 或 CUDA torch。

    python scripts/setup_sep.py --device cpu [--venv /content/xinsw-sep-venv]
    python scripts/setup_sep.py --device cuda [--cuda cu124]

模型权重由 audio-separator 自动下载，可用 MUSICMASTER_SEP_MODELS 指定缓存目录。
"""
from __future__ import annotations
import argparse, os, subprocess, sys, venv
from pathlib import Path

# 系统 Python + GBK 控制台:输出/重定向遇非 GBK 字符会 UnicodeEncodeError,统一切 UTF-8(防御式)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]


def venv_python(d: Path) -> Path:
    return d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venv", default=str(ROOT / "vendor" / ".venv-sep"))
    ap.add_argument("--device", choices=("cpu", "cuda"), default="cpu",
                    help="分离环境计算设备；默认 CPU，不会申请或启动 GPU")
    ap.add_argument("--cuda", default="cu124", help="device=cuda 时的 PyTorch CUDA 轮子标签,如 cu124 / cu121")
    a = ap.parse_args()
    vdir = Path(a.venv)
    vdir.parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] 建 {vdir}")
    venv.create(vdir, with_pip=True)
    py = str(venv_python(vdir))

    def run(*pip_args):
        subprocess.check_call([py, "-m", "pip", *pip_args])

    print("[2/4] 升级 pip")
    run("install", "-U", "pip")
    if a.device == "cpu":
        print("[3/5] 装 CPU torch / torchaudio（不安装 CUDA 运行时）")
        run("install", "torch", "torchaudio", "--index-url",
            "https://download.pytorch.org/whl/cpu")
        extra = "cpu"
    else:
        print(f"[3/5] 装 CUDA torch({a.cuda})")
        run("install", "torch", "torchaudio", "--index-url",
            f"https://download.pytorch.org/whl/{a.cuda}")
        extra = "gpu"

    print("[4/5] 安装分离依赖与 audio-separator")
    run("install", "-r", str(ROOT / "requirements" / "requirements-sep.txt"))
    run("install", f"audio-separator[{extra}]")
    print("[5/5] 安装本包(供 -m musicmaster.separate.pipeline)")
    run("install", "-e", str(ROOT), "--no-deps")

    print("\n[OK] 完成。把这个加进你的环境变量(GUI/CLI 用它找分离 venv):")
    print(f"    MUSICMASTER_SEP_PYTHON={py}")
    print("自测:")
    print(f'    "{py}" -m musicmaster.separate.pipeline 混音.wav --stages 1,2,3')


if __name__ == "__main__":
    main()
