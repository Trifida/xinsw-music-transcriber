"""Regression tests for the VocalParse -> MusicXML event adapter."""
from __future__ import annotations

import importlib
import importlib.util
import pytest

music21 = pytest.importorskip("music21")

from musicmaster.core.vocalparse import (  # noqa: E402
    musicxml_roundtrip_errors,
    musicxml_lyric_alignment,
    validate_events,
    vocalparse_events_to_musicxml,
    vocalparse_result_to_musicxml,
    vocalparse_tokens_to_events,
    vocalparse_lyric_alignment,
    render_vocalparse_result,
)
from musicmaster.core.render import musicxml_to_lilypond, render_staff_svg


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



def test_real_colab_50_token_sample_is_preserved():
    # Captured from the user's successful 25-second VocalParse inference.
    parsed = {
        "bpm": 100,
        "words": [
            "SP", "如", "果", "世", "·", "界", "变", "·", "换", "太",
            "快", "SP", "当", "青", "·", "春", "SP", "慢", "慢", "走",
            "·", "远", "SP", "当", "容", "·", "颜", "不", "再", "如",
            "初", "·", "·", "见", "SP", "你", "不", "必", "问", "我",
            "SP", "爱", "·", "不", "·", "·", "爱", "SP", "也", "不",
        ],
        "pitches": [
            0, 55, 55, 58, 59, 60, 61, 58, 60, 58,
            54, 0, 55, 58, 60, 60, 0, 58, 58, 54,
            56, 56, 0, 55, 55, 54, 53, 54, 52, 49,
            53, 55, 54, 54, 0, 47, 47, 49, 50, 52,
            0, 52, 54, 56, 58, 56, 56, 0, 56, 55,
        ],
        "notes": [
            "NOTE_2", "NOTE_8", "NOTE_DOT_16", "NOTE_8", "NOTE_DOT_16",
            "NOTE_DOT_4", "NOTE_DOT_16", "NOTE_DOT_16", "NOTE_4", "NOTE_DOT_8",
            "NOTE_DOT_4", "NOTE_2", "NOTE_8", "NOTE_DOT_8", "NOTE_4",
            "NOTE_DOT_4", "NOTE_DOT_4", "NOTE_DOT_8", "NOTE_4", "NOTE_8",
            "NOTE_16", "NOTE_4", "NOTE_DOT_8", "NOTE_8", "NOTE_DOT_16",
            "NOTE_DOT_16", "NOTE_8", "NOTE_8", "NOTE_8", "NOTE_4",
            "NOTE_DOT_8", "NOTE_16", "NOTE_DOT_16", "NOTE_2", "NOTE_4",
            "NOTE_8", "NOTE_8", "NOTE_DOT_8", "NOTE_DOT_16", "NOTE_DOT_4",
            "NOTE_16", "NOTE_8", "NOTE_DOT_8", "NOTE_DOT_8", "NOTE_DOT_16",
            "NOTE_DOT_16", "NOTE_DOT_4", "NOTE_DOT_4", "NOTE_8", "NOTE_8",
        ],
    }

    events = vocalparse_tokens_to_events(parsed)
    assert len(events) == 50
    assert sum(not event["is_rest"] for event in events) == 43
    assert sum(event["is_rest"] for event in events) == 7
    assert sum(event["duration_beats"] for event in events) == 39.5
    assert events[-1]["end_sec"] == pytest.approx(23.7)



def test_lyric_alignment_keeps_one_anchor_and_preserves_continuation_marker(vocalparse_events):
    aligned = vocalparse_lyric_alignment(vocalparse_events, 100)
    displayed = [item for item in aligned if item["display_lyric"]]
    continuations = [item for item in aligned if item["is_continuation_marker"]]

    assert len(aligned) == 10
    assert [item["lyric"] for item in displayed] == ["如", "果", "世", "界", "变", "换", "太", "快", "慢"]
    assert len(continuations) == 1
    assert continuations[0]["raw_word"] == "慢"
    assert continuations[0]["lyric"] is None
    assert continuations[0]["display_lyric"] is False


def test_musicxml_displays_lyrics_once_and_never_on_rests(tmp_path, vocalparse_events):
    destination = tmp_path / "vocalparse-lyrics.musicxml"
    vocalparse_events_to_musicxml(vocalparse_events, 100, destination)

    actual = musicxml_lyric_alignment(destination)
    expected = [
        (event["start_beat"], event["lyric"])
        for event in vocalparse_events
        if not event["is_rest"]
        and event.get("lyric")
        and not event.get("is_lyric_continuation", False)
    ]
    assert [(row["start_beat"], row["lyric"]) for row in actual] == expected



def test_jianpu_source_retains_chinese_lyrics_when_backend_is_installed(tmp_path, vocalparse_events):
    if importlib.util.find_spec("jianpu_ly") is None:
        pytest.skip("jianpu-ly is not installed")
    destination = tmp_path / "jianpu-lyrics.musicxml"
    vocalparse_events_to_musicxml(vocalparse_events, 100, destination)

    lilypond_source = musicxml_to_lilypond(destination)
    # This is an integration contract: the conversion must not silently discard
    # Chinese lyrics while converting MusicXML into jianpu-ly/LilyPond source.
    for lyric in ("如", "果", "世", "界", "变", "换", "太", "快"):
        assert lyric in lilypond_source


def test_staff_svg_retains_chinese_lyrics_when_verovio_is_installed(tmp_path, vocalparse_events):
    if importlib.util.find_spec("verovio") is None:
        pytest.skip("verovio is not installed")
    destination = tmp_path / "staff-lyrics.musicxml"
    svg_path = tmp_path / "staff-lyrics.svg"
    vocalparse_events_to_musicxml(vocalparse_events, 100, destination)

    render_staff_svg(destination, svg_path)
    svg = svg_path.read_text(encoding="utf-8")
    for lyric in ("如", "果", "世", "界", "变", "换", "太", "快"):
        assert lyric in svg



def test_dual_notation_render_uses_one_musicxml_source(tmp_path, monkeypatch):
    render_module = importlib.import_module("musicmaster.core.render")
    captured = {}

    def fake_render(musicxml, out_dir, **kwargs):
        captured["musicxml"] = musicxml
        captured["out_dir"] = out_dir
        captured["kwargs"] = kwargs
        return {"staff": tmp_path / "staff.svg", "jianpu_ly": tmp_path / "jianpu.ly"}

    monkeypatch.setattr(render_module, "render", fake_render)
    parsed = {
        "bpm": 100,
        "words": ["SP", "你", "·", "好"],
        "pitches": [0, 60, 60, 62],
        "notes": ["NOTE_2", "NOTE_4", "NOTE_8", "NOTE_DOT_4"],
    }

    artifacts = render_vocalparse_result(parsed, tmp_path / "score")

    assert artifacts["musicxml"].exists()
    assert captured["musicxml"] == artifacts["musicxml"]
    assert captured["kwargs"]["formats"] == ("staff", "jianpu")
    assert captured["kwargs"]["require_all"] is False
    assert artifacts["staff"].name == "staff.svg"
    assert artifacts["jianpu_ly"].name == "jianpu.ly"


@pytest.mark.parametrize("bad_pitch", [60.5, -1, 128, float("nan"), float("inf"), True, "not-a-pitch"])
def test_vocalparse_rejects_invalid_pitch_without_truncating(bad_pitch):
    parsed = {
        "bpm": 100,
        "words": ["你"],
        "pitches": [bad_pitch],
        "notes": ["NOTE_4"],
    }
    with pytest.raises(ValueError, match="MIDI pitch"):
        vocalparse_tokens_to_events(parsed)


def test_validate_events_rejects_non_boolean_rest_flag():
    event = {
        "start_beat": 0,
        "duration_beats": 1,
        "pitch_midi": 60,
        "is_rest": "false",
    }
    with pytest.raises(ValueError, match="is_rest must be a boolean"):
        validate_events([event], 100)
