# -*- coding: utf-8 -*-
"""整首歌曲工作流：混音 → 人声/伴奏分离 → 主旋律扒谱。

此入口供后续云 GPU worker 和本地验收共同调用。它只负责编排现有算法，
不复制或改写 separate.pipeline / transcribe.autopilot 的核心处理逻辑。
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Callable, Optional


ProgressCallback = Optional[Callable[[float, str], None]]


def _notify(callback: ProgressCallback, progress: float, label: str) -> None:
    if callback is None:
        return
    try:
        callback(max(0.0, min(1.0, float(progress))), label)
    except Exception:  # noqa: BLE001 — 进度通知不能中断音频任务
        pass


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _parse_stages(value: str) -> list[str]:
    stages = [part.strip() for part in value.split(",") if part.strip()]
    if (not stages or any(stage not in {"1", "2", "3"} for stage in stages)
            or len(stages) != len(set(stages)) or stages[0] != "1"):
        raise ValueError("stages 必须从第 1 段分离开始，按顺序选择 1、2、3，例如 1 或 1,2,3。")
    if stages != sorted(stages):
        raise ValueError("stages 必须按 1、2、3 的顺序填写。")
    return stages


def run_full_transcription(
    input_audio: str | Path,
    output_dir: str | Path,
    *,
    engine: str = "crepe",
    key: str = "",
    stages: str = "1,2,3",
    denoise: str = "dereverb",
    progress_callback: ProgressCallback = None,
) -> dict:
    """从整首混音开始，完成分离并对最终主唱轨执行主旋律扒谱。

    output_dir 必须是本次任务专属目录；已有 separation/transcription 子目录时拒绝覆盖。
    """
    source = Path(input_audio).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    selected_stages = _parse_stages(stages)

    if not source.is_file():
        raise FileNotFoundError(f"输入音频不存在：{source}")
    if denoise not in {"dereverb", "deecho"}:
        raise ValueError("denoise 仅支持 dereverb / deecho。")

    root.mkdir(parents=True, exist_ok=True)
    separation_dir = root / "separation"
    transcription_dir = root / "transcription"
    if separation_dir.exists() or transcription_dir.exists():
        raise FileExistsError("任务输出目录已包含 separation/transcription，拒绝覆盖已有结果。")

    separation_dir.mkdir()
    _notify(progress_callback, 0.03, "准备分离整首歌曲…")

    separator = importlib.import_module("musicmaster.separate.pipeline")
    separation_rc = separator.main([
        str(source),
        "--stages", ",".join(selected_stages),
        "--denoise", denoise,
        "--out-dir", str(separation_dir),
    ])
    if separation_rc != 0:
        raise RuntimeError(f"人声分离失败，退出码：{separation_rc}")

    # pipeline 的正式输出约定：第一段保留伴奏，顶层“最终_*.wav”为级联处理后的人声。
    vocal = separation_dir / f"最终_{source.stem}.wav"
    accompaniment = separation_dir / "1_分离" / "accomp.wav"
    if not vocal.is_file():
        raise RuntimeError("分离程序未生成最终主唱音轨，不能继续扒谱。")
    if not accompaniment.is_file():
        raise RuntimeError("分离程序未生成伴奏音轨，M1 产物不完整。")

    _notify(progress_callback, 0.58, "人声与伴奏已分离，开始识别主旋律…")
    transcription_dir.mkdir()
    autopilot = importlib.import_module("musicmaster.transcribe.autopilot")
    if engine not in autopilot.ENGINES:
        raise ValueError(f"未知扒谱引擎「{engine}」，可选：{', '.join(autopilot.ENGINES)}。")

    argv = [str(vocal), "--out", str(transcription_dir), "--engine", engine]
    if key and key.strip():
        argv.extend(["--key", key.strip()])

    def _transcribe_progress(value: float, label: str) -> None:
        # autopilot 回传 0–100 的阶段进度；把它映射到整条工作流的后 40%。
        mapped = 0.58 + 0.40 * max(0.0, min(100.0, float(value))) / 100.0
        _notify(progress_callback, mapped, label)

    transcription_rc = autopilot.main(argv, progress_callback=_transcribe_progress)
    if transcription_rc != 0:
        raise RuntimeError(f"主旋律扒谱失败，退出码：{transcription_rc}")

    required = ("notes.json", "out.mid", "out.musicxml")
    missing = [name for name in required if not (transcription_dir / name).is_file()]
    if missing:
        raise RuntimeError("扒谱流程未生成必要产物：" + "、".join(missing))

    optional = ("staff.svg", "jianpu.pdf", "jianpu.ly", "confidence.json", "报告.md")
    transcription_files = {
        name: _relative(transcription_dir / name, root)
        for name in (*required, *optional)
        if (transcription_dir / name).is_file()
    }
    separation_files = sorted(
        _relative(path, root) for path in separation_dir.rglob("*") if path.is_file()
    )

    manifest = {
        "schema_version": 1,
        "status": "completed",
        "source": {"filename": source.name},
        "separation": {
            "status": "completed",
            "stages": selected_stages,
            "final_vocal": _relative(vocal, root),
            "accompaniment": _relative(accompaniment, root),
            "files": separation_files,
        },
        "transcription": {
            "status": "completed",
            "engine": engine,
            "key": key.strip() or None,
            "input_vocal": _relative(vocal, root),
            "files": transcription_files,
        },
    }
    manifest_path = root / "job_result.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _notify(progress_callback, 1.0, "整首歌曲处理完成。")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="整首歌曲自动分离人声并扒取主旋律")
    parser.add_argument("input", help="整首混音音频 MP3/WAV")
    parser.add_argument("--out", required=True, help="本次任务专属输出目录")
    parser.add_argument("--engine", default="crepe", choices=("crepe", "basic-pitch", "bytedance"))
    parser.add_argument("--key", default="")
    parser.add_argument("--stages", default="1,2,3")
    parser.add_argument("--denoise", default="dereverb", choices=("dereverb", "deecho"))
    args = parser.parse_args(argv)
    try:
        result = run_full_transcription(
            args.input, args.out, engine=args.engine, key=args.key,
            stages=args.stages, denoise=args.denoise,
        )
    except Exception as exc:  # noqa: BLE001 — CLI 向调度器返回非零码
        print(f"[full-transcribe] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
