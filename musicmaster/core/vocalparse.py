"""VocalParse event adapter.

This module preserves VocalParse's beat-based events without passing them
through the legacy Target -> MusicXML quantizer. The legacy Target contract
and its exporters remain unchanged.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple, Union

PathLike = Union[str, Path]
_TOL = 1e-7


def validate_events(events: Sequence[Mapping[str, Any]], bpm: float) -> List[Dict[str, Any]]:
    """Validate and return a stable, start-time-sorted copy of VocalParse events."""
    bpm = float(bpm)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("bpm must be a finite positive number")
    if not events:
        raise ValueError("events must contain at least one event")

    normalized: List[Dict[str, Any]] = []
    for index, source in enumerate(events):
        try:
            start = float(source["start_beat"])
            duration = float(source["duration_beats"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"event {index} needs numeric start_beat and duration_beats") from exc

        if not math.isfinite(start) or start < 0:
            raise ValueError(f"event {index} has invalid start_beat: {start}")
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"event {index} has invalid duration_beats: {duration}")

        is_rest = bool(source.get("is_rest", False))
        pitch = source.get("pitch_midi")
        if not is_rest:
            if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
                raise ValueError(f"event {index} has invalid pitch_midi: {pitch!r}")

        event = dict(source)
        event["start_beat"] = start
        event["duration_beats"] = duration
        event["end_beat"] = start + duration
        event["is_rest"] = is_rest
        normalized.append(event)

    normalized.sort(key=lambda item: (item["start_beat"], item["is_rest"]))
    previous_end = 0.0
    for index, event in enumerate(normalized):
        if event["start_beat"] < previous_end - _TOL:
            raise ValueError(
                f"overlapping monophonic events at index {index}: "
                f"start={event['start_beat']}, previous_end={previous_end}"
            )
        previous_end = max(previous_end, event["end_beat"])
    return normalized


def vocalparse_events_to_musicxml(
    events: Sequence[Mapping[str, Any]],
    bpm: float,
    out_path: PathLike,
    *,
    key_name: str | None = None,
    time_signature: str = "4/4",
) -> Path:
    """Write VocalParse beat events directly to MusicXML, without legacy quantization.

    The original event list remains the source of truth. MusicXML exporters may
    split an event at notation boundaries; tie marks retain its sounding identity.
    """
    from music21 import key as m21key
    from music21 import meter, note, stream, tempo

    normalized = validate_events(events, bpm)
    try:
        time_sig = meter.TimeSignature(time_signature)
    except Exception as exc:
        raise ValueError(f"invalid time_signature: {time_signature!r}") from exc

    part = stream.Part()
    part.id = "VocalParseLead"
    part.insert(0, tempo.MetronomeMark(number=float(bpm)))
    part.insert(0, time_sig)
    if key_name:
        part.insert(0, m21key.Key(key_name))

    for event in normalized:
        element = note.Rest() if event["is_rest"] else note.Note(int(event["pitch_midi"]))
        element.duration.quarterLength = float(event["duration_beats"])

        lyric = event.get("lyric")
        is_continuation = bool(event.get("is_lyric_continuation", False))
        if not event["is_rest"] and lyric and lyric not in ("SP", "·") and not is_continuation:
            element.addLyric(str(lyric))

        part.insert(float(event["start_beat"]), element)

    score = stream.Score()
    score.insert(0, part)

    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = score.write("musicxml", fp=str(destination))
    return Path(written) if written else destination


def _merge_tied_notes(parsed_notes: Iterable[Any]) -> Tuple[List[Dict[str, float]], List[str]]:
    """Recombine MusicXML tie fragments into their original sounding notes."""
    fragments = sorted(parsed_notes, key=lambda item: float(item.offset))
    merged: List[Dict[str, float]] = []
    errors: List[str] = []
    index = 0

    while index < len(fragments):
        current = fragments[index]
        start = float(current.offset)
        pitch = int(current.pitch.midi)
        duration = float(current.duration.quarterLength)
        tie_type = current.tie.type if current.tie else None

        if tie_type in ("continue", "stop"):
            errors.append(f"orphan tie {tie_type} at beat {start:g}, MIDI {pitch}")
            merged.append({"start": start, "pitch": pitch, "duration": duration})
            index += 1
            continue

        if tie_type != "start":
            merged.append({"start": start, "pitch": pitch, "duration": duration})
            index += 1
            continue

        total = duration
        expected_start = start + duration
        cursor = index + 1
        completed = False
        while cursor < len(fragments):
            following = fragments[cursor]
            following_start = float(following.offset)
            following_pitch = int(following.pitch.midi)
            following_tie = following.tie.type if following.tie else None
            if (
                following_pitch != pitch
                or not math.isclose(following_start, expected_start, abs_tol=_TOL)
                or following_tie not in ("continue", "stop")
            ):
                break

            fragment_duration = float(following.duration.quarterLength)
            total += fragment_duration
            expected_start += fragment_duration
            cursor += 1
            if following_tie == "stop":
                completed = True
                break

        if not completed:
            errors.append(f"unterminated tie at beat {start:g}, MIDI {pitch}")
        merged.append({"start": start, "pitch": pitch, "duration": total})
        index = cursor

    return merged, errors


def _merge_contiguous_rests(parsed_rests: Iterable[Any]) -> List[Dict[str, float]]:
    fragments = sorted(parsed_rests, key=lambda item: float(item.offset))
    merged: List[Dict[str, float]] = []
    for rest in fragments:
        start = float(rest.offset)
        duration = float(rest.duration.quarterLength)
        if merged and math.isclose(
            merged[-1]["start"] + merged[-1]["duration"], start, abs_tol=_TOL
        ):
            merged[-1]["duration"] += duration
        else:
            merged.append({"start": start, "duration": duration})
    return merged


def musicxml_roundtrip_errors(
    events: Sequence[Mapping[str, Any]], musicxml_path: PathLike, bpm: float
) -> List[str]:
    """Return data-integrity differences after reading a generated MusicXML file."""
    from music21 import converter, note

    expected = validate_events(events, bpm)
    parsed = converter.parse(str(musicxml_path))
    if not parsed.parts:
        return ["MusicXML contains no parts"]
    flat = parsed.parts[0].flatten()
    actual_notes, tie_errors = _merge_tied_notes(flat.getElementsByClass(note.Note))
    actual_rests = _merge_contiguous_rests(flat.getElementsByClass(note.Rest))

    expected_notes = [e for e in expected if not e["is_rest"]]
    expected_rests = [e for e in expected if e["is_rest"]]
    errors = list(tie_errors)

    if len(expected_notes) != len(actual_notes):
        errors.append(f"note count: expected {len(expected_notes)}, got {len(actual_notes)}")
    for index, (source, actual) in enumerate(zip(expected_notes, actual_notes), 1):
        checks = (
            ("start", float(source["start_beat"]), actual["start"]),
            ("pitch", int(source["pitch_midi"]), actual["pitch"]),
            ("duration", float(source["duration_beats"]), actual["duration"]),
        )
        for label, left, right in checks:
            equal = left == right if label == "pitch" else math.isclose(left, right, abs_tol=_TOL)
            if not equal:
                errors.append(f"note {index} {label}: expected {left}, got {right}")

    if len(expected_rests) != len(actual_rests):
        errors.append(f"rest count: expected {len(expected_rests)}, got {len(actual_rests)}")
    for index, (source, actual) in enumerate(zip(expected_rests, actual_rests), 1):
        for label, left, right in (
            ("start", float(source["start_beat"]), actual["start"]),
            ("duration", float(source["duration_beats"]), actual["duration"]),
        ):
            if not math.isclose(left, right, abs_tol=_TOL):
                errors.append(f"rest {index} {label}: expected {left}, got {right}")

    return errors
