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

        is_rest_value = source.get("is_rest", False)
        if not isinstance(is_rest_value, bool):
            raise ValueError(f"event {index} is_rest must be a boolean")
        is_rest = is_rest_value
        pitch = source.get("pitch_midi")
        if not is_rest:
            if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
                raise ValueError(f"event {index} has invalid pitch_midi: {pitch!r}")

        event = dict(source)
        event["start_beat"] = start
        event["duration_beats"] = duration
        calculated_end = start + duration
        if "end_beat" in source and not math.isclose(float(source["end_beat"]), calculated_end, abs_tol=_TOL):
            raise ValueError(f"event {index} end_beat does not match start_beat + duration_beats")
        event["end_beat"] = calculated_end
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


# VocalParse symbol durations are expressed in quarter-note beats.
_DURATION_BEATS = {
    "NOTE_1": 4.0,
    "NOTE_DOT_1": 6.0,
    "NOTE_2": 2.0,
    "NOTE_DOT_2": 3.0,
    "NOTE_4": 1.0,
    "NOTE_DOT_4": 1.5,
    "NOTE_8": 0.5,
    "NOTE_DOT_8": 0.75,
    "NOTE_16": 0.25,
    "NOTE_DOT_16": 0.375,
    "NOTE_32": 0.125,
    "NOTE_DOT_32": 0.1875,
}


def vocalparse_tokens_to_events(parsed: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Convert VocalParse's parsed words/pitches/duration tokens into beat events.

    SP and MIDI pitch 0 are rests. The middle-dot marker is preserved as a
    lyric-continuation event, not promoted to a new lyric syllable.
    """
    try:
        bpm = float(parsed["bpm"])
        words = list(parsed["words"])
        pitches = list(parsed["pitches"])
        durations = list(parsed["notes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("parsed result must contain bpm, words, pitches, and notes arrays") from exc

    if not (len(words) == len(pitches) == len(durations)):
        raise ValueError(
            "VocalParse words, pitches, and notes arrays must have equal lengths"
        )
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("parsed bpm must be a finite positive number")

    events: List[Dict[str, Any]] = []
    cursor = 0.0
    seconds_per_beat = 60.0 / bpm

    for index, (word, pitch_value, token) in enumerate(zip(words, pitches, durations)):
        token = str(token)
        if token not in _DURATION_BEATS:
            raise ValueError(f"unsupported VocalParse duration token at index {index}: {token}")
        duration = _DURATION_BEATS[token]
        word = str(word)
        if isinstance(pitch_value, bool):
            raise ValueError(f"invalid MIDI pitch at index {index}: {pitch_value!r}")
        try:
            numeric_pitch = float(pitch_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid MIDI pitch at index {index}: {pitch_value!r}") from exc
        if (
            not math.isfinite(numeric_pitch)
            or not numeric_pitch.is_integer()
            or not 0 <= numeric_pitch <= 127
        ):
            raise ValueError(f"invalid MIDI pitch at index {index}: {pitch_value!r}")
        pitch = int(numeric_pitch)
        is_rest = word == "SP" or pitch == 0
        is_continuation = word == "·"

        event = {
            "event_id": f"vp-{index + 1:05d}",
            "raw_word": word,
            "lyric": None if is_rest or is_continuation else word,
            "pitch_midi": None if is_rest else pitch,
            "duration_token": token,
            "duration_beats": duration,
            "start_beat": cursor,
            "end_beat": cursor + duration,
            "start_sec": cursor * seconds_per_beat,
            "end_sec": (cursor + duration) * seconds_per_beat,
            "is_rest": is_rest,
            "is_lyric_continuation": is_continuation,
        }
        events.append(event)
        cursor += duration

    return validate_events(events, bpm)



def _tokenize_manual_lyrics(lyrics: str) -> List[str]:
    """Split pasted lyrics into note-level syllables.

    Chinese characters are individual syllables; contiguous Latin words and
    numbers stay together. Punctuation is attached to the preceding syllable.
    An em dash (—) or tilde (~) is a melisma continuation slot; a middle dot
    (·) is an intentionally lyricless note slot.
    """
    import re
    if not isinstance(lyrics, str):
        raise TypeError("lyrics must be a string")
    raw_tokens = re.findall(
        r"[A-Za-z]+(?:['’][A-Za-z]+)*|[0-9]+|[\u3400-\u9fff]|[—~·]|[^\s]",
        lyrics,
    )
    tokens: List[str] = []
    punctuation = set("，。！？；：、,.!?;:)]}）】》」』”’")
    for token in raw_tokens:
        if token in punctuation and tokens and tokens[-1] not in ("—", "~", "·"):
            tokens[-1] += token
        else:
            tokens.append(token)
    return tokens


def align_manual_lyrics(
    events: Sequence[Mapping[str, Any]],
    bpm: float,
    lyrics: str,
    *,
    strict: bool = True,
) -> List[Dict[str, Any]]:
    """Attach user-supplied lyrics to monophonic note events.

    Default mapping is one Chinese character or one Latin word per pitched
    note. Rests do not consume lyric slots. Use '—' (or '~') for a melisma
    continuation note and '·' for a deliberately lyricless pitched note.
    Strict mode requires an exact slot count to prevent silent lyric loss.
    """
    normalized = validate_events(events, bpm)
    tokens = _tokenize_manual_lyrics(lyrics)
    note_events = [
        event for event in normalized
        if not event["is_rest"]
        and not bool(event.get("is_lyric_continuation", False))
        and str(event.get("raw_word") or "") != "·"
    ]
    if strict and len(tokens) != len(note_events):
        raise ValueError(
            f"歌词音节数与可分配音符数不一致：歌词 {len(tokens)} 个，"
            f"可分配音符 {len(note_events)} 个。中文按字、英文按单词；"
            "拖腔请用“—”占一个后续音符，纯音乐音符请用“·”占位。"
        )
    if len(tokens) > len(note_events):
        raise ValueError(f"歌词有 {len(tokens)} 个音节，但只有 {len(note_events)} 个可分配音符。")
    aligned = [dict(event) for event in normalized]
    token_index = 0
    previous_has_lyric = False
    for event in aligned:
        if event["is_rest"]:
            event["lyric"] = None
            previous_has_lyric = False
            continue
        if bool(event.get("is_lyric_continuation", False)) or str(event.get("raw_word") or "") == "·":
            event["lyric"] = None
            event["is_lyric_continuation"] = True
            continue
        if token_index >= len(tokens):
            if strict:
                raise ValueError("歌词音节不足，无法完成逐音符对齐。")
            event["lyric"] = None
            event["is_lyric_continuation"] = False
            continue
        token = tokens[token_index]
        token_index += 1
        if token in ("—", "~"):
            if not previous_has_lyric:
                raise ValueError("歌词延续符“—”前面必须先有一个实际歌词音节。")
            event["lyric"] = None
            event["is_lyric_continuation"] = True
        elif token == "·":
            event["lyric"] = None
            event["is_lyric_continuation"] = False
            previous_has_lyric = False
        else:
            event["lyric"] = token
            event["is_lyric_continuation"] = False
            event["lyric_source"] = "manual"
            previous_has_lyric = True
    if strict and token_index != len(tokens):
        raise ValueError("存在未能分配到音符的歌词音节。")
    return aligned

def vocalparse_result_to_musicxml(
    parsed: Mapping[str, Any],
    out_path: PathLike,
    *,
    key_name: str | None = None,
    time_signature: str = "4/4",
    lyrics: str | None = None,
) -> Path:
    """Convert a VocalParse result to MusicXML, optionally using user-supplied lyrics."""
    bpm = float(parsed["bpm"])
    events = vocalparse_tokens_to_events(parsed)
    if lyrics is not None:
        events = align_manual_lyrics(events, bpm, lyrics)
    return vocalparse_events_to_musicxml(
        events, bpm, out_path, key_name=key_name, time_signature=time_signature
    )



def vocalparse_lyric_alignment(
    events: Sequence[Mapping[str, Any]], bpm: float
) -> List[Dict[str, Any]]:
    """Build a notation-ready, per-note lyric alignment without guessing marker semantics.

    A normal lyric is anchored to its own note. A VocalParse middle-dot marker
    remains an explicit continuation marker with no displayed lyric. It is not
    silently merged into the preceding word because that interpretation needs
    model-level confirmation.
    """
    normalized = validate_events(events, bpm)
    aligned: List[Dict[str, Any]] = []
    note_index = 0
    for event in normalized:
        if event["is_rest"]:
            continue
        note_index += 1
        raw_word = str(event.get("raw_word") or "")
        is_continuation = bool(event.get("is_lyric_continuation", False)) or raw_word == "·"
        lyric = event.get("lyric")
        if is_continuation or lyric in (None, "", "SP", "·"):
            lyric = None
        aligned.append({
            "event_id": event.get("event_id"),
            "note_index": note_index,
            "start_beat": float(event["start_beat"]),
            "end_beat": float(event["end_beat"]),
            "raw_word": raw_word,
            "lyric": str(lyric) if lyric is not None else None,
            "display_lyric": lyric is not None,
            "is_continuation_marker": is_continuation,
        })
    return aligned


def musicxml_lyric_alignment(musicxml_path: PathLike) -> List[Dict[str, Any]]:
    """Read displayed lyric anchors from MusicXML for layout regression checks."""
    from music21 import converter, note

    parsed = converter.parse(str(musicxml_path))
    if not parsed.parts:
        return []
    flat = parsed.parts[0].flatten()
    aligned: List[Dict[str, Any]] = []
    for element in flat.getElementsByClass(note.Note):
        for lyric in element.lyrics:
            aligned.append({
                "start_beat": float(element.offset),
                "lyric": str(lyric.text or ""),
            })
    return aligned


def render_vocalparse_result(
    parsed: Mapping[str, Any],
    out_dir: PathLike,
    *,
    key_name: str | None = None,
    time_signature: str = "4/4",
    lyrics: str | None = None,
    page: int = 1,
    jianpu_format: str = "svg",
    lilypond_timeout: float = 120.0,
    require_all: bool = False,
) -> Dict[str, Path]:
    """Create one MusicXML source and render VocalParse output as staff and jianpu.

    Both notation renderers receive the exact same MusicXML file. By default,
    missing optional render backends follow the existing best-effort behavior;
    set require_all=True to fail unless both requested score formats render.
    The MusicXML source is always included in the returned artifact map.
    """
    from .render import render

    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    musicxml_path = vocalparse_result_to_musicxml(
        parsed,
        destination / "vocalparse.musicxml",
        key_name=key_name,
        time_signature=time_signature,
        lyrics=lyrics,
    )
    artifacts = render(
        musicxml_path,
        destination,
        formats=("staff", "jianpu"),
        page=page,
        jianpu_format=jianpu_format,
        lilypond_timeout=lilypond_timeout,
        require_all=require_all,
    )
    return {"musicxml": musicxml_path, **artifacts}
