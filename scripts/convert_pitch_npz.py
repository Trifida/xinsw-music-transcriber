"""Convert a saved numeric pitch NPZ archive to timestamped pitch-track JSON.

No model inference is performed. Array keys and timing must be selected explicitly;
this tool intentionally does not guess the archive schema.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def _vector(archive: Any, key: str, label: str) -> np.ndarray:
    if key not in archive.files:
        raise ValueError(f"{label} key {key!r} not found; available keys: {archive.files}")
    try:
        values = np.asarray(archive[key])
    except ValueError as exc:
        raise ValueError(f"{label} array {key!r} cannot be safely read") from exc
    values = np.squeeze(values)
    if values.ndim != 1:
        raise ValueError(
            f"{label} array {key!r} must be one-dimensional after squeezing singleton axes; "
            f"got shape {values.shape}"
        )
    if not np.issubdtype(values.dtype, np.number):
        raise ValueError(f"{label} array {key!r} must be numeric")
    return values.astype(np.float64, copy=False)


def convert_npz_to_pitch_json(
    npz_path: str | Path,
    output_json: str | Path,
    *,
    time_key: str | None = None,
    hop_seconds: float | None = None,
    frequency_key: str | None = None,
    pitch_midi_key: str | None = None,
    confidence_key: str | None = None,
    start_time_sec: float = 0.0,
) -> dict[str, Any]:
    if (frequency_key is None) == (pitch_midi_key is None):
        raise ValueError("select exactly one of frequency_key or pitch_midi_key")
    if (time_key is None) == (hop_seconds is None):
        raise ValueError("select exactly one of time_key or hop_seconds")
    if hop_seconds is not None and (
        isinstance(hop_seconds, bool) or not np.isfinite(hop_seconds) or hop_seconds <= 0
    ):
        raise ValueError("hop_seconds must be finite and positive")
    if isinstance(start_time_sec, bool) or not np.isfinite(start_time_sec) or start_time_sec < 0:
        raise ValueError("start_time_sec must be finite and nonnegative")

    source = Path(npz_path)
    if not source.is_file():
        raise FileNotFoundError(f"NPZ file not found: {source}")

    with np.load(source, allow_pickle=False) as archive:
        value_key = frequency_key if frequency_key is not None else pitch_midi_key
        values = _vector(archive, value_key, "pitch")
        if time_key is not None:
            times = _vector(archive, time_key, "time")
        else:
            times = float(start_time_sec) + np.arange(values.size, dtype=np.float64) * float(hop_seconds)
        confidence = (
            _vector(archive, confidence_key, "confidence")
            if confidence_key is not None
            else np.ones(values.size, dtype=np.float64)
        )
        if len(times) != len(values) or len(confidence) != len(values):
            raise ValueError(
                "time, pitch and confidence arrays must have identical lengths; "
                f"got {len(times)}, {len(values)}, {len(confidence)}"
            )
        if not np.isfinite(times).all() or (times < 0).any():
            raise ValueError("time values must be finite and nonnegative")
        if not np.isfinite(confidence).all() or ((confidence < 0) | (confidence > 1)).any():
            raise ValueError("confidence values must be finite and between 0 and 1")
        if not np.isfinite(values).all():
            raise ValueError("pitch/frequency values must all be finite")
        if frequency_key is not None and (values < 0).any():
            raise ValueError("frequency values must be nonnegative; use 0 for unvoiced frames")
        if pitch_midi_key is not None:
            voiced = values != 0
            if ((values[voiced] <= 0) | (values[voiced] > 127)).any():
                raise ValueError("nonzero MIDI pitch values must be in the range (0, 127]")

        frames = []
        for index in range(values.size):
            frame: dict[str, float | None] = {
                "time_sec": float(times[index]),
                "confidence": float(confidence[index]),
            }
            if frequency_key is not None:
                frame["frequency_hz"] = float(values[index])
            else:
                frame["pitch_midi"] = None if values[index] == 0 else float(values[index])
            frames.append(frame)

        report = {
            "source_file": source.name,
            "frame_count": len(frames),
            "timing": {
                "source": "explicit_time_array" if time_key is not None else "explicit_hop_seconds",
                "time_key": time_key,
                "hop_seconds": float(hop_seconds) if hop_seconds is not None else None,
                "start_time_sec": float(start_time_sec) if time_key is None else None,
            },
            "pitch_representation": "frequency_hz" if frequency_key is not None else "pitch_midi",
            "frames": frames,
        }

    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert explicitly selected arrays in a saved NPZ to pitch-track JSON."
    )
    parser.add_argument("npz_file")
    parser.add_argument("output_json")
    timing = parser.add_mutually_exclusive_group(required=True)
    timing.add_argument("--time-key", help="Array containing frame timestamps in seconds.")
    timing.add_argument("--hop-seconds", type=float, help="Frame spacing in seconds; must be confirmed from source metadata.")
    pitch = parser.add_mutually_exclusive_group(required=True)
    pitch.add_argument("--frequency-key", help="Array of frequencies in Hz; 0 means unvoiced.")
    pitch.add_argument("--pitch-midi-key", help="Array of MIDI pitches; 0 means unvoiced.")
    parser.add_argument("--confidence-key", help="Optional confidence array in [0, 1].")
    parser.add_argument("--start-time-sec", type=float, default=0.0,
                        help="First frame time when using --hop-seconds.")
    args = parser.parse_args()
    try:
        report = convert_npz_to_pitch_json(
            args.npz_file,
            args.output_json,
            time_key=args.time_key,
            hop_seconds=args.hop_seconds,
            frequency_key=args.frequency_key,
            pitch_midi_key=args.pitch_midi_key,
            confidence_key=args.confidence_key,
            start_time_sec=args.start_time_sec,
        )
    except Exception as exc:
        parser.exit(2, f"NPZ conversion failed: {exc}\n")
    print(json.dumps({key: value for key, value in report.items() if key != "frames"},
                     ensure_ascii=False, indent=2))
    print(f"Pitch-track JSON saved: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
