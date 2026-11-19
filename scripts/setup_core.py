#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""建主环境(CPU):GUI + 扒谱 + 互转 + 渲染。

    python scripts/setup_core.py [--venv .venv]

安装流程:建 venv → TensorFlow → CREPE full 单一模型 → 本地 CREPE 精简包
→ MusicMaster 核心依赖 → MusicMaster 本体。不会下载 CREPE 其他四种规格。
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]


def venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", default=str(ROOT / ".venv"))
    args = parser.parse_args()
    vdir = Path(args.venv)

    print(f"[1/7] 创建虚拟环境: {vdir}")
    venv.create(vdir, with_pip=True)
    py = str(venv_python(vdir))

    def pip(*arguments):
        subprocess.check_call([py, "-m", "pip", *arguments])

    print("[2/7] 更新 pip 和构建工具")
    pip("install", "--upgrade", "pip")
    pip("install", "setuptools<81", "wheel")

    print("[3/7] 安装 TensorFlow 2.15.0")
    pip("install", "tensorflow==2.15.0")

    print("[4/7] 下载并解压 CREPE full 模型（只下载这一种规格）")
    subprocess.check_call([py, str(ROOT / "scripts" / "prepare_crepe_model.py")])

    print("[5/7] 安装本地 CREPE 精简包")
    pip("install", "--no-build-isolation", "--no-deps", str(ROOT / "vendor" / "crepe"))

    print("[6/7] 安装 MusicMaster 核心依赖")
    pip("install", "-r", str(ROOT / "requirements" / "requirements-core.txt"))

    print("[7/7] 安装 MusicMaster 本体")
    pip("install", "-e", str(ROOT))

    print("\n[完成] 启动界面: 双击 启动.bat")
    print(f"       或运行: {py} -m musicmaster.web.server")
    print("简谱 PDF/SVG 出图还需独立安装 LilyPond CLI（见 README）。")


if __name__ == "__main__":
    main()
