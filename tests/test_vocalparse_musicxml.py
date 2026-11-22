"""Regression tests for the VocalParse -> MusicXML event adapter."""
from __future__ import annotations

import pytest

music21 = pytest.importorskip("music21")

from musicmaster.core.vocalparse import (  # noqa: E402
    musicxml_roundtrip_errors,
    validate_events,
    vocalparse_events_to_musicxml,
    vocalparse_result_to_musicxml,
    vocalparse_tokens_to_events,
)


@pytest.fixture
def vocalparse_events():
    # Includes dotted/irregular subdivisions, a note crossing a 4/4 boundary,
    # explicit rests, and a lyric continuation marker.
    rows = [
        (0.000, 2.000, None, True, None, False),
        (2.000, 0.500, 55, False, "如", False),
        (2.500, 0.375, 58, False, "果", False),
        (2.875, 0.500, 59, False, "世", False),
        (3.375, 0.375, 60, False, "界", False),
        (3.750, 1.500, 61, False, "变", False),
        (5.250, 0.375, 58, False, "换", False),
        (5.625, 0.375, 60, False, "太", False),
        (6.000, 1.000, 58, False, "快", False),
        (7.000, 0.750, 54, False, "慢", False),
        (7.750, 1.500, 56, False, "慢", True),
        (9.250, 2.000, None, True, None, False),
    ]
    events = []
    for index, (start, duration, pitch, is_rest, lyric, continuation) in enumerate(rows):
        events.append({
            "event_id": f"e{index + 1}",
            "start_beat": start,
            "duration_beats": duration,
            "end_beat": start + duration,
            "pitch_midi": pitch,
            "is_rest": is_rest,
            "lyric": lyric,
            "raw_word": lyric if lyric else "SP",
            "is_lyric_continuation": continuation,
        })
    return events


def test_validate_events_preserves_order_and_duration(vocalparse_events):
    normalized = validate_events(vocalparse_events, 100)
    assert len(normalized) == len(vocalparse_events)
    assert normalized[5]["pitch_midi"] == 61
    assert normalized[5]["duration_beats"] == 1.5
    assert normalized[-1]["is_rest"] is True


def test_validate_events_rejects_overlaps(vocalparse_events):
    broken = [dict(event) for event in vocalparse_events]
    broken[2]["start_beat"] = 2.25
    broken[2]["end_beat"] = 2.625
    with pytest.raises(ValueError, match="overlapping"):
        validate_events(broken, 100)


def test_musicxml_roundtrip_restores_split_notes_and_rests(tmp_path, vocalparse_events):
    destination = tmp_path / "vocalparse-roundtrip.musicxml"
    vocalparse_events_to_musicxml(vocalparse_events, 100, destination)

    assert destination.exists()
    assert destination.stat().st_size > 0
    assert musicxml_roundtrip_errors(vocalparse_events, destination, 100) == []



def test_vocalparse_tokens_build_beat_events():
    parsed = {
        "bpm": 100,
        "words": ["SP", "你", "·", "好"],
        "pitches": [0, 60, 60, 62],
        "notes": ["NOTE_2", "NOTE_4", "NOTE_8", "NOTE_DOT_4"],
    }
    events = vocalparse_tokens_to_events(parsed)
    assert len(events) == 4
    assert events[0]["is_rest"] is True
    assert events[1]["lyric"] == "你"
    assert events[2]["is_lyric_continuation"] is True
    assert events[2]["lyric"] is None
    assert events[-1]["end_beat"] == 5.0


def test_vocalparse_result_direct_musicxml_roundtrip(tmp_path):
    parsed = {
        "bpm": 100,
        "words": ["SP", "你", "·", "好"],
        "pitches": [0, 60, 60, 62],
        "notes": ["NOTE_2", "NOTE_4", "NOTE_8", "NOTE_DOT_4"],
    }
    events = vocalparse_tokens_to_events(parsed)
    destination = tmp_path / "vocalparse-direct.musicxml"
    vocalparse_result_to_musicxml(parsed, destination)
    assert musicxml_roundtrip_errors(events, destination, 100) == []
