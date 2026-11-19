#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对真实主唱音轨运行 MusicMaster 原生 CREPE 全流程并记录可复核基准。

用法:
  python scripts/benchmark_real_audio.py lead_vocal.wav --out benchmark_result

说明:
  - 只运行独立 CREPE 主唱流程,不调用旧 music-engine。
  - 会生成 MusicMaster 原生 MIDI / MusicXML / SVG / 简谱源 / 可信度报告。
  - benchmark.json 记录整次耗时、峰值内存(平台支持时)、音符数量和产物大小。
  - CREPE 权重由独立安装脚本预先准备;本脚本只测推理/制谱流程,不把模型下载时间混入识别耗时。
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import time
from pathlib import Path


def peak_rss_mb():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes.
        return round(value / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except Exception:
        try:
            import psutil
            return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except Exception:
            return None


def extract_quality_gate(report: str):
    """Extract the human-readable L1 quality gate from MusicMaster's report."""
    match = re.search(r"门控=([^\s）)]+)", report)
    return match.group(1) if match else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="MusicMaster CREPE 主唱真实音频基准")
    parser.add_argument("input", help="主唱音轨 WAV/MP3/FLAC")
    parser.add_argument("--out", required=True, help="结果输出目录")
    parser.add_argument("--fmin", default="C2", help="最低识别音高,默认 C2")
    parser.add_argument("--fmax", default="C6", help="最高识别音高,默认 C6")
    args = parser.parse_args(argv)

    src = Path(args.input).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not src.is_file():
        parser.error("输入音频不存在: " + str(src))
    out.mkdir(parents=True, exist_ok=True)

    from musicmaster.transcribe import autopilot

    started = time.perf_counter()
    rc = autopilot.main([
        str(src), "--out", str(out), "--engine", "crepe",
        "--fmin", args.fmin, "--fmax", args.fmax,
    ])
    elapsed = round(time.perf_counter() - started, 3)

    notes_path = out / "notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}
    confidence_path = out / "confidence.json"
    confidence = json.loads(confidence_path.read_text(encoding="utf-8")) if confidence_path.is_file() else {}
    report_path = out / "报告.md"
    report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    gate = extract_quality_gate(report)
    outputs = {}
    for name in ("notes.json", "out.mid", "out.musicxml", "staff.svg",
                 "jianpu.ly", "jianpu.pdf", "confidence.json", "报告.md"):
        file = out / name
        if file.is_file():
            outputs[name] = {"bytes": file.stat().st_size}

    result = {
        "engine": "MusicMaster CREPE standalone",
        "input_file": src.name,
        "input_bytes": src.stat().st_size,
        "fmin": args.fmin,
        "fmax": args.fmax,
        "return_code": rc,
        "elapsed_seconds": elapsed,
        "peak_rss_mb": peak_rss_mb(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "tempo_bpm": notes.get("tempo"),
        "note_count": len(notes.get("notes", [])),
        "quality_gate": gate.group(1) if gate else None,
        "confidence_overall": confidence.get("overall"),
        "confidence_passages": len(confidence.get("passages", [])),
        "outputs": outputs,
    }
    summary = out / "benchmark.json"
    summary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    required = ("notes.json", "out.mid", "out.musicxml", "staff.svg", "confidence.json")
    if rc != 0 or not all((out / name).is_file() for name in required):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
