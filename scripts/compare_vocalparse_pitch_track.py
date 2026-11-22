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
from musicmaster.core.vocalparse_diagnostics import compare_vocalparse_to_pitch_track


def compare_files(
    vocalparse_json: str | Path,
    pitch_track_json: str | Path,
    output_json: str | Path,
    *,
    confidence_threshold: float = 0.5,
    central_fraction: float = 0.6,
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
    args = parser.parse_args()
    try:
        report = compare_files(
            args.vocalparse_json,
            args.pitch_track_json,
            args.output_json,
            confidence_threshold=args.confidence_threshold,
            central_fraction=args.central_fraction,
        )
    except Exception as exc:
        parser.exit(2, f"Pitch comparison failed: {exc}\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Detailed report: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
