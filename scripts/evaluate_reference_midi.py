#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compare a MusicMaster MIDI result with a manually checked reference MIDI.

Example:
  python scripts/evaluate_reference_midi.py benchmark_result/out.mid reference.mid \
      --onset-tolerance 0.12 --out evaluation.json

Matching is one-to-one and onset-tolerance based (appropriate for a monophonic
lead-vocal melody). Pitch is scored separately so octave errors are visible
rather than being silently treated as unrelated/missing notes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pretty_midi


def read_notes(path: Path, instrument_index: int | None = None):
    midi = pretty_midi.PrettyMIDI(str(path))
    instruments = midi.instruments
    if instrument_index is not None:
        if instrument_index < 0 or instrument_index >= len(instruments):
            raise ValueError(
                f"instrument index {instrument_index} outside 0..{len(instruments)-1}"
            )
        instruments = [instruments[instrument_index]]
    notes = []
    for instrument in instruments:
        for note in instrument.notes:
            if note.end > note.start:
                notes.append({
                    "pitch": int(note.pitch),
                    "start": float(note.start),
                    "end": float(note.end),
                })
    return sorted(notes, key=lambda n: (n["start"], n["pitch"]))


def match_notes(predicted, reference, tolerance):
    """Order-preserving optimal one-to-one matching for monophonic melodies.

    First maximize the number of onset matches, then minimize total onset
    error, then minimize pitch distance as a deterministic tie-breaker.
    This avoids a nearest-pair greedy choice consuming a reference note that
    would otherwise allow two valid sequential matches.
    """
    n, m = len(predicted), len(reference)
    # Score: (number of matches, negative onset error, negative pitch distance).
    dp = [[(0, 0.0, 0) for _ in range(m + 1)] for _ in range(n + 1)]
    action = [[None for _ in range(m + 1)] for _ in range(n + 1)]

    for i in range(1, n + 1):
        action[i][0] = "skip_predicted"
    for j in range(1, m + 1):
        action[0][j] = "skip_reference"

    for i in range(1, n + 1):
        p = predicted[i - 1]
        for j in range(1, m + 1):
            r = reference[j - 1]
            best = dp[i - 1][j]
            best_action = "skip_predicted"

            candidate = dp[i][j - 1]
            if candidate > best:
                best, best_action = candidate, "skip_reference"

            onset_delta = abs(p["start"] - r["start"])
            if onset_delta <= tolerance:
                previous = dp[i - 1][j - 1]
                matched = (
                    previous[0] + 1,
                    previous[1] - onset_delta,
                    previous[2] - abs(p["pitch"] - r["pitch"]),
                )
                if matched > best:
                    best, best_action = matched, "match"

            dp[i][j] = best
            action[i][j] = best_action

    used_p, used_r, matches = set(), set(), []
    i, j = n, m
    while i > 0 or j > 0:
        step = action[i][j]
        if step == "match":
            pi, ri = i - 1, j - 1
            p, r = predicted[pi], reference[ri]
            used_p.add(pi)
            used_r.add(ri)
            matches.append({
                "predicted_index": pi,
                "reference_index": ri,
                "onset_error_seconds": round(p["start"] - r["start"], 4),
                "pitch_error_semitones": p["pitch"] - r["pitch"],
                "duration_error_seconds": round((p["end"] - p["start"]) - (r["end"] - r["start"]), 4),
                "exact_pitch": p["pitch"] == r["pitch"],
                "octave_error": abs(p["pitch"] - r["pitch"]) in (12, 24, 36),
            })
            i -= 1
            j -= 1
        elif step == "skip_predicted":
            i -= 1
        elif step == "skip_reference":
            j -= 1
        else:
            break

    matches.sort(key=lambda item: item["reference_index"])
    return matches, used_p, used_r

def evaluate(predicted, reference, tolerance):
    matches, used_p, used_r = match_notes(predicted, reference, tolerance)
    matched = len(matches)
    exact = sum(m["exact_pitch"] for m in matches)
    octave = sum(m["octave_error"] for m in matches)
    onset_mae = (
        sum(abs(m["onset_error_seconds"]) for m in matches) / matched
        if matched else None
    )
    duration_mae = (
        sum(abs(m["duration_error_seconds"]) for m in matches) / matched
        if matched else None
    )
    pitch_mae = (
        sum(abs(m["pitch_error_semitones"]) for m in matches) / matched
        if matched else None
    )
    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted_note_count": len(predicted),
        "reference_note_count": len(reference),
        "onset_matched_count": matched,
        "unmatched_predicted_count": len(predicted) - len(used_p),
        "missed_reference_count": len(reference) - len(used_r),
        "onset_precision": round(precision, 4),
        "onset_recall": round(recall, 4),
        "onset_f1": round(f1, 4),
        "exact_pitch_count": exact,
        "pitch_accuracy_on_onset_matches": round(exact / matched, 4) if matched else 0.0,
        "octave_error_count": octave,
        "mean_absolute_pitch_error_semitones": round(pitch_mae, 4) if pitch_mae is not None else None,
        "mean_absolute_onset_error_seconds": round(onset_mae, 4) if onset_mae is not None else None,
        "mean_absolute_duration_error_seconds": round(duration_mae, 4) if duration_mae is not None else None,
        "onset_tolerance_seconds": tolerance,
        "matches": matches,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate MusicMaster MIDI against a checked reference MIDI")
    parser.add_argument("predicted_midi")
    parser.add_argument("reference_midi")
    parser.add_argument("--onset-tolerance", type=float, default=0.12)
    parser.add_argument("--predicted-instrument", type=int, default=None)
    parser.add_argument("--reference-instrument", type=int, default=None)
    parser.add_argument("--out", default="midi_evaluation.json")
    args = parser.parse_args(argv)

    if args.onset_tolerance < 0:
        parser.error("--onset-tolerance must be >= 0")
    predicted_path = Path(args.predicted_midi).expanduser().resolve()
    reference_path = Path(args.reference_midi).expanduser().resolve()
    if not predicted_path.is_file() or not reference_path.is_file():
        parser.error("Both predicted and reference MIDI files must exist")

    predicted = read_notes(predicted_path, args.predicted_instrument)
    reference = read_notes(reference_path, args.reference_instrument)
    result = {
        "engine": "MusicMaster CREPE standalone",
        "predicted_file": predicted_path.name,
        "reference_file": reference_path.name,
        **evaluate(predicted, reference, args.onset_tolerance),
    }
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
