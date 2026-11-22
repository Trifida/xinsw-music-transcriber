"""Offline cross-checks between VocalParse notes and an independent F0 track.

This module does not declare either model output to be ground truth. It provides
a timestamp-based diagnostic so an existing CREPE/torchcrepe pitch contour can
be compared with VocalParse without rerunning either model.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Mapping, Sequence


def compare_vocalparse_to_pitch_track(
    events: Sequence[Mapping[str, Any]],
    bpm: float,
    pitch_frames: Sequence[Mapping[str, Any]],
    *,
    confidence_threshold: float = 0.5,
    central_fraction: float = 0.6,
) -> Dict[str, Any]:
    """Compare note events with timestamped reference F0 frames.

    Each pitch frame must contain time_sec and pitch_midi; confidence is
    optional and defaults to 1.0. A null pitch denotes an unvoiced frame.
    Only the central central_fraction of each event is sampled to reduce
    boundary contamination. Rests are checked for voiced-frame contamination.

    The reference contour is a second estimator, not human-verified ground
    truth. Metrics therefore describe model-to-model agreement only.
    """
    try:
        tempo = float(bpm)
    except (TypeError, ValueError) as exc:
        raise ValueError("bpm must be a finite positive number") from exc
    if not math.isfinite(tempo) or tempo <= 0:
        raise ValueError("bpm must be a finite positive number")
    if isinstance(confidence_threshold, bool) or not isinstance(confidence_threshold, (int, float)):
        raise ValueError("confidence_threshold must be between 0 and 1")
    if not math.isfinite(float(confidence_threshold)) or not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if isinstance(central_fraction, bool) or not isinstance(central_fraction, (int, float)):
        raise ValueError("central_fraction must be greater than 0 and at most 1")
    if not math.isfinite(float(central_fraction)) or not 0 < central_fraction <= 1:
        raise ValueError("central_fraction must be greater than 0 and at most 1")

    frames = []
    for index, frame in enumerate(pitch_frames):
        try:
            timestamp = float(frame["time_sec"])
            if "pitch_midi" in frame:
                raw_pitch = frame.get("pitch_midi")
                pitch = None if raw_pitch is None else float(raw_pitch)
            elif "frequency_hz" in frame:
                frequency = float(frame["frequency_hz"])
                if not math.isfinite(frequency) or frequency < 0:
                    raise ValueError("frequency_hz must be finite and nonnegative")
                pitch = None if frequency == 0 else 69.0 + 12.0 * math.log2(frequency / 440.0)
            else:
                raise ValueError("pitch frame needs pitch_midi or frequency_hz")
            confidence = float(frame.get("confidence", 1.0))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"invalid pitch frame at index {index}: {exc}") from exc
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError(f"invalid time_sec at pitch frame {index}")
        if pitch is not None and (not math.isfinite(pitch) or not 0 < pitch <= 127):
            raise ValueError(f"invalid pitch value at pitch frame {index}")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f"invalid confidence at pitch frame {index}")
        frames.append((timestamp, pitch, confidence))
    frames.sort(key=lambda item: item[0])

    trim = (1.0 - float(central_fraction)) / 2.0
    seconds_per_beat = 60.0 / tempo
    rows = []
    note_errors = []
    rest_voiced_ratios = []

    for index, event in enumerate(events):
        try:
            start_beat = float(event["start_beat"])
            duration_beats = float(event["duration_beats"])
            is_rest = event["is_rest"]
            expected_pitch = event.get("pitch_midi")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid VocalParse event at index {index}") from exc
        if not math.isfinite(start_beat) or start_beat < 0:
            raise ValueError(f"invalid start_beat at event {index}")
        if not math.isfinite(duration_beats) or duration_beats <= 0:
            raise ValueError(f"invalid duration_beats at event {index}")
        if not isinstance(is_rest, bool):
            raise ValueError(f"is_rest must be boolean at event {index}")
        if not is_rest and (
            isinstance(expected_pitch, bool)
            or not isinstance(expected_pitch, int)
            or not 0 <= expected_pitch <= 127
        ):
            raise ValueError(f"invalid pitch_midi at event {index}")

        start_sec = start_beat * seconds_per_beat
        end_sec = (start_beat + duration_beats) * seconds_per_beat
        sample_start = start_sec + (end_sec - start_sec) * trim
        sample_end = end_sec - (end_sec - start_sec) * trim
        selected = [
            (pitch, confidence)
            for timestamp, pitch, confidence in frames
            if sample_start <= timestamp <= sample_end
        ]
        voiced = [
            (pitch, confidence)
            for pitch, confidence in selected
            if pitch is not None and confidence >= confidence_threshold
        ]
        row: Dict[str, Any] = {
            "event_index": index,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "is_rest": is_rest,
            "frame_count": len(selected),
            "voiced_frame_count": len(voiced),
        }

        if is_rest:
            ratio = len(voiced) / len(selected) if selected else None
            row["reference_voiced_ratio"] = ratio
            if ratio is not None:
                rest_voiced_ratios.append(ratio)
        else:
            row["vocalparse_pitch_midi"] = expected_pitch
            if voiced:
                reference_pitch = float(statistics.median(pitch for pitch, _ in voiced))
                error = float(expected_pitch) - reference_pitch
                row["reference_median_pitch_midi"] = reference_pitch
                row["pitch_error_semitones"] = error
                row["reference_confidence_mean"] = statistics.mean(conf for _, conf in voiced)
                row["is_octave_mismatch"] = abs(abs(error) - 12.0) <= 1.0
                note_errors.append((error, row["is_octave_mismatch"]))
            else:
                row["reference_median_pitch_midi"] = None
                row["pitch_error_semitones"] = None
                row["is_octave_mismatch"] = None
        rows.append(row)

    absolute_errors = [abs(error) for error, _ in note_errors]
    note_count = sum(not event["is_rest"] for event in events)
    summary = {
        "note_count": note_count,
        "compared_note_count": len(note_errors),
        "uncompared_note_count": note_count - len(note_errors),
        "median_absolute_error_semitones": (
            float(statistics.median(absolute_errors)) if absolute_errors else None
        ),
        "within_one_semitone_rate": (
            sum(error <= 1.0 for error in absolute_errors) / len(absolute_errors)
            if absolute_errors else None
        ),
        "octave_mismatch_count": sum(is_octave for _, is_octave in note_errors),
        "rest_count": sum(bool(event["is_rest"]) for event in events),
        "compared_rest_count": len(rest_voiced_ratios),
        "mean_rest_voiced_ratio": (
            float(statistics.mean(rest_voiced_ratios)) if rest_voiced_ratios else None
        ),
        "confidence_threshold": float(confidence_threshold),
        "central_fraction": float(central_fraction),
        "comparison_type": "model_to_model_not_ground_truth",
    }
    return {"summary": summary, "events": rows}
