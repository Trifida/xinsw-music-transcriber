"""Compare saved VocalParse notes with an independently saved pitch contour.

Input pitch-track JSON:
{"frames": [{"time_sec": 0.01, "frequency_hz": 261.63, "confidence": 0.95}]}
Use frequency_hz: 0 or pitch_midi: null for unvoiced frames. No inference is performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from musicmaster.core.vocalparse import vocalparse_tokens_to_events
from musicmaster.core.vocalparse_diagnostics import (
    calibrate_vocalparse_time_mapping,
    compare_vocalparse_to_pitch_track,
)


def compare_files(
    vocalparse_json: str | Path,
    pitch_track_json: str | Path,
    output_json: str | Path,
    *,
    confidence_threshold: float = 0.5,
    central_fraction: float = 0.6,
    reference_time_offset_sec: float = 0.0,
    reference_time_scale: float = 1.0,
) -> dict[str, Any]:
    parsed = json.loads(Path(vocalparse_json).read_text(encoding="utf-8"))
    reference = json.loads(Path(pitch_track_json).read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("VocalParse JSON root must be an object")
    if isinstance(reference, dict):
        frames = reference.get("frames")
    else:
        frames = reference
    if not isinstance(frames, list):
        raise ValueError("pitch-track JSON must be an array or an object with a frames array")

    events = vocalparse_tokens_to_events(parsed)
    report = compare_vocalparse_to_pitch_track(
        events,
        parsed["bpm"],
        frames,
        confidence_threshold=confidence_threshold,
        central_fraction=central_fraction,
        reference_time_offset_sec=reference_time_offset_sec,
        reference_time_scale=reference_time_scale,
    )
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare saved VocalParse notes against a timestamped pitch contour."
    )
    parser.add_argument("vocalparse_json")
    parser.add_argument("pitch_track_json")
    parser.add_argument("output_json")
    parser.add_argument("--confidence-threshold", type=float, default=0.5)
    parser.add_argument("--central-fraction", type=float, default=0.6)
    parser.add_argument("--reference-time-offset", type=float, default=0.0,
                        help="Offset in seconds from the VocalParse clip start to the reference track timeline.")
    parser.add_argument("--reference-time-scale", type=float, default=1.0,
                        help="Scale applied to clip-relative times before adding the reference offset; 1.06 means the reference timeline runs 6%% longer.")
    parser.add_argument("--calibrate-time-mapping", action="store_true",
                        help="Also grid-search the clip-to-reference offset and time scale.")
    parser.add_argument("--calibrate-offset-range", type=float, nargs=3, metavar=("START", "STOP", "STEP"),
                        default=(29.5, 31.0, 0.1))
    parser.add_argument("--calibrate-scale-range", type=float, nargs=3, metavar=("START", "STOP", "STEP"),
                        default=(0.96, 1.10, 0.01))
    parser.add_argument("--minimum-coverage", type=float, default=0.8)
    args = parser.parse_args()
    try:
        report = compare_files(
            args.vocalparse_json,
            args.pitch_track_json,
            args.output_json,
            confidence_threshold=args.confidence_threshold,
            central_fraction=args.central_fraction,
            reference_time_offset_sec=args.reference_time_offset,
            reference_time_scale=args.reference_time_scale,
        )
        if args.calibrate_time_mapping:
            def make_grid(spec):
                start, stop, step = spec
                if step <= 0 or stop < start:
                    raise ValueError('calibration ranges require positive step and stop >= start')
                count = int(round((stop - start) / step))
                return [round(start + index * step, 8) for index in range(count + 1)]
            parsed = json.loads(Path(args.vocalparse_json).read_text(encoding='utf-8'))
            reference = json.loads(Path(args.pitch_track_json).read_text(encoding='utf-8'))
            frames = reference.get('frames') if isinstance(reference, dict) else reference
            events = vocalparse_tokens_to_events(parsed)
            report['time_mapping_calibration'] = calibrate_vocalparse_time_mapping(
                events, parsed['bpm'], frames,
                offset_values=make_grid(args.calibrate_offset_range),
                scale_values=make_grid(args.calibrate_scale_range),
                confidence_threshold=args.confidence_threshold,
                central_fraction=args.central_fraction,
                minimum_coverage=args.minimum_coverage,
            )
            destination = Path(args.output_json)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        parser.exit(2, f"Pitch comparison failed: {exc}\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Detailed report: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
