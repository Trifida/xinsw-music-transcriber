#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 GPU 完整歌曲验证入口。

在项目主环境(.venv)中运行；MUSICMASTER_SEP_PYTHON 指向独立 CUDA 分离环境。
示例：
  MUSICMASTER_SEP_PYTHON=/workspace/xinsw-music-transcriber/vendor/.venv-sep/bin/python \
  .venv/bin/python scripts/gpu_full_song_smoke.py /path/to/song.mp3

该脚本会先验证 CUDA，再执行 BS-RoFormer 人声分离，最后复用正式 CREPE 扒谱流程。
不会修改正式 Render 服务，也不会自动关机或删除实例数据。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class SmokeJob:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = str(job_dir)

    def set_stage(self, stage: str, progress: float | None = None) -> None:
        suffix = f" ({progress:.0%})" if progress is not None else ""
        print(f"[任务]{suffix} {stage}", flush=True)

    def set_progress(self, progress: float) -> None:
        print(f"[进度] {progress:.0%}", flush=True)


def probe_separator_python(python: str) -> dict:
    code = (
        "import importlib.util,json,torch; "
        "ok=bool(torch.cuda.is_available()); "
        "d={'torch':torch.__version__,'cuda_available':ok,"
        "'cuda_version':torch.version.cuda,"
        "'audio_separator_installed':importlib.util.find_spec('audio_separator') is not None,"
        "'gpu_name':torch.cuda.get_device_name(0) if ok else None,"
        "'gpu_memory_gb':round(torch.cuda.get_device_properties(0).total_memory/1024**3,2) if ok else None}; "
        "print(json.dumps(d,ensure_ascii=False)); "
        "raise SystemExit(0 if ok and d['audio_separator_installed'] else 3)"
    )
    result = subprocess.run(
        [python, "-c", code], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=45,
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        raise RuntimeError(
            "分离环境未通过 CUDA/audio-separator 检查。"
            + (f"\n输出: {output}" if output else "")
            + (f"\n错误: {result.stderr[-2000:]}" if result.stderr else "")
        )
    return json.loads(output.splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description="完整歌曲真实 GPU 端到端冒烟测试")
    parser.add_argument("audio", help="完整歌曲音频文件路径")
    parser.add_argument("--out", default="gpu-smoke-output", help="测试产物目录")
    parser.add_argument("--sep-python", default=os.environ.get("MUSICMASTER_SEP_PYTHON"))
    parser.add_argument("--engine", default="crepe", choices=("crepe",))
    parser.add_argument("--key", default="")
    args = parser.parse_args()

    audio = Path(args.audio).expanduser().resolve()
    if not audio.is_file():
        parser.error(f"找不到音频文件: {audio}")
    if not args.sep_python or not Path(args.sep_python).is_file():
        parser.error("请通过 --sep-python 或 MUSICMASTER_SEP_PYTHON 指定 GPU 分离环境的 Python。")

    os.environ["MUSICMASTER_SEP_PYTHON"] = str(Path(args.sep_python).resolve())
    os.environ.setdefault(
        "MUSICMASTER_SEP_MODELS",
        str(Path.home() / ".cache" / "audio-separator-models"),
    )

    try:
        gpu = probe_separator_python(os.environ["MUSICMASTER_SEP_PYTHON"])
    except Exception as exc:
        print(f"[失败] GPU 环境检查: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print("[GPU]", json.dumps(gpu, ensure_ascii=False), flush=True)
    print(f"[模型缓存] {os.environ['MUSICMASTER_SEP_MODELS']}", flush=True)
    print("[开始] 完整歌曲 → BS-RoFormer → CREPE → MusicXML/谱面", flush=True)

    from musicmaster.web.runners import run_full_song_transcribe

    result = run_full_song_transcribe(
        SmokeJob(out_dir),
        str(audio),
        engine=args.engine,
        key=args.key,
        lyrics_text="",
        auto_lyrics=False,
    )
    files = [
        {"path": p.relative_to(out_dir).as_posix(), "size_bytes": p.stat().st_size}
        for p in sorted(out_dir.rglob("*")) if p.is_file()
    ]
    vocal = out_dir / "1_分离" / "vocal.wav"
    summary = {
        "ok": bool(result.get("ok")),
        "message": result.get("message"),
        "gpu": gpu,
        "separation": result.get("separation"),
        "vocal_exists": vocal.is_file(),
        "vocal_size_bytes": vocal.stat().st_size if vocal.is_file() else None,
        "files": files,
    }
    print("\n[结果]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] and summary["vocal_exists"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
