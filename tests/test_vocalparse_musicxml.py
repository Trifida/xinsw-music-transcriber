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



def test_pitch_npz_inspector_reports_numeric_arrays_without_unpickling(tmp_path):
    import json
    import numpy as np
    import runpy
    from pathlib import Path

    archive = tmp_path / "pitch.npz"
    np.savez(
        archive,
        time=np.array([0.0, 0.01, 0.02]),
        frequency=np.array([220.0, 221.0, 0.0]),
        confidence=np.array([0.9, 0.8, 0.1]),
    )
    script = Path(__file__).parents[1] / "scripts" / "inspect_pitch_npz.py"
    report = runpy.run_path(str(script))["inspect_npz"](archive)

    assert report["format"] == "numpy_npz"
    assert report["arrays"]["frequency"]["shape"] == [3]
    assert report["arrays"]["frequency"]["min"] == 0.0
    assert report["arrays"]["frequency"]["max"] == 221.0
    assert report["arrays"]["confidence"]["sample"] == [0.9, 0.8, 0.1]


def test_pitch_npz_inspector_refuses_object_arrays(tmp_path):
    import numpy as np
    import runpy
    from pathlib import Path

    archive = tmp_path / "object.npz"
    np.savez(archive, unsafe=np.array([{"x": 1}], dtype=object))
    script = Path(__file__).parents[1] / "scripts" / "inspect_pitch_npz.py"
    report = runpy.run_path(str(script))["inspect_npz"](archive)

    assert report["arrays"]["unsafe"]["readable"] is False


def test_pitch_track_comparison_cli_writes_machine_readable_report(tmp_path):
    import json
    import runpy
    from pathlib import Path

    vocalparse_json = tmp_path / "vocalparse.json"
    track_json = tmp_path / "pitch-track.json"
    output_json = tmp_path / "comparison.json"
    vocalparse_json.write_text(
        json.dumps({"bpm": 100, "words": ["你"], "pitches": [60], "notes": ["NOTE_4"]}),
        encoding="utf-8",
    )
    track_json.write_text(
        json.dumps({"frames": [
            {"time_sec": 0.12, "pitch_midi": 60.1, "confidence": 0.9},
            {"time_sec": 0.24, "pitch_midi": 60.0, "confidence": 0.9},
            {"time_sec": 0.36, "pitch_midi": 60.2, "confidence": 0.9},
        ]}),
        encoding="utf-8",
    )
    script = Path(__file__).parents[1] / "scripts" / "compare_vocalparse_pitch_track.py"
    namespace = runpy.run_path(str(script))
    report = namespace["compare_files"](vocalparse_json, track_json, output_json)

    assert report["summary"]["compared_note_count"] == 1
    saved = json.loads(output_json.read_text(encoding="utf-8"))
    assert saved["summary"]["comparison_type"] == "model_to_model_not_ground_truth"


def test_pitch_track_diagnostic_reports_semitone_and_octave_mismatches():
    from musicmaster.core.vocalparse_diagnostics import compare_vocalparse_to_pitch_track

    events = [
        {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60, "is_rest": False},
        {"start_beat": 1, "duration_beats": 1, "pitch_midi": None, "is_rest": True},
        {"start_beat": 2, "duration_beats": 1, "pitch_midi": 72, "is_rest": False},
    ]
    frames = []
    for time_sec in (0.12, 0.18, 0.24, 0.30, 0.36, 0.42, 0.48, 0.54):
        frames.append({"time_sec": time_sec, "pitch_midi": 60.1, "confidence": 0.95})
    for time_sec in (0.72, 0.90, 1.08):
        frames.append({"time_sec": time_sec, "pitch_midi": None, "confidence": 0.1})
    for time_sec in (1.32, 1.50, 1.68, 1.86):
        frames.append({"time_sec": time_sec, "pitch_midi": 60.0, "confidence": 0.9})

    result = compare_vocalparse_to_pitch_track(events, 100, frames)
    summary = result["summary"]
    assert summary["compared_note_count"] == 2
    assert summary["median_absolute_error_semitones"] == pytest.approx(6.05)
    assert summary["octave_mismatch_count"] == 1
    assert summary["compared_rest_count"] == 1
    assert summary["mean_rest_voiced_ratio"] == 0.0
    assert summary["comparison_type"] == "model_to_model_not_ground_truth"


def test_pitch_track_diagnostic_accepts_frequency_hz_frames():
    from musicmaster.core.vocalparse_diagnostics import compare_vocalparse_to_pitch_track

    result = compare_vocalparse_to_pitch_track(
        [{"start_beat": 0, "duration_beats": 1, "pitch_midi": 60, "is_rest": False}],
        100,
        [
            {"time_sec": 0.12, "frequency_hz": 261.6256, "confidence": 0.95},
            {"time_sec": 0.24, "frequency_hz": 261.6256, "confidence": 0.95},
            {"time_sec": 0.36, "frequency_hz": 0, "confidence": 0.1},
        ],
    )
    assert result["summary"]["compared_note_count"] == 1
    assert result["events"][0]["reference_median_pitch_midi"] == pytest.approx(60, abs=0.001)


def test_pitch_track_diagnostic_rejects_invalid_reference_frames():
    from musicmaster.core.vocalparse_diagnostics import compare_vocalparse_to_pitch_track

    with pytest.raises(ValueError, match="invalid pitch_midi"):
        compare_vocalparse_to_pitch_track(
            [{"start_beat": 0, "duration_beats": 1, "pitch_midi": 60, "is_rest": False}],
            100,
            [{"time_sec": 0.1, "pitch_midi": 200, "confidence": 1}],
        )


def test_real_colab_50_token_sample_is_preserved():
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "vocalparse_25s_sample.json"
    parsed = json.loads(fixture.read_text(encoding="utf-8"))

    events = vocalparse_tokens_to_events(parsed)
    assert len(events) == 50
    assert sum(not event["is_rest"] for event in events) == 43
    assert sum(event["is_rest"] for event in events) == 7
    assert sum(event["duration_beats"] for event in events) == 39.5
    assert events[-1]["end_sec"] == pytest.approx(23.7)



def test_captured_colab_sample_roundtrips_notes_rests_and_lyrics(tmp_path):
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "vocalparse_25s_sample.json"
    parsed = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(parsed["words"]) == len(parsed["pitches"]) == len(parsed["notes"]) == 50

    events = vocalparse_tokens_to_events(parsed)
    musicxml_path = tmp_path / "captured-vocalparse-sample.musicxml"
    vocalparse_events_to_musicxml(events, parsed["bpm"], musicxml_path)

    assert musicxml_roundtrip_errors(events, musicxml_path, parsed["bpm"]) == []
    expected_lyrics = [
        (item["start_beat"], item["lyric"])
        for item in vocalparse_lyric_alignment(events, parsed["bpm"])
        if item["display_lyric"]
    ]
    actual_lyrics = musicxml_lyric_alignment(musicxml_path)
    assert [(item["start_beat"], item["lyric"]) for item in actual_lyrics] == expected_lyrics
    assert len(actual_lyrics) == 33
    assert all(lyric not in ("SP", "·") for _, lyric in expected_lyrics)


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
    expected_lyrics = ("如", "果", "世", "界", "变", "换", "太", "快")
    for lyric in expected_lyrics:
        assert lyric in lilypond_source
    # jianpu-ly should emit an actual Lyrics context, not merely leave the
    # characters in metadata or comments; the syllables must remain ordered.
    assert r"\lyricsto" in lilypond_source
    lyric_positions = [lilypond_source.index(lyric) for lyric in expected_lyrics]
    assert lyric_positions == sorted(lyric_positions)


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


def test_vocalparse_musicxml_renders_real_jianpu_svg_and_pdf_when_lilypond_installed(
    tmp_path, vocalparse_events
):
    import shutil

    if not shutil.which("lilypond"):
        pytest.skip("LilyPond CLI is not installed")
    from musicmaster.core.render import render

    musicxml = tmp_path / "vocalparse-real-render.musicxml"
    vocalparse_events_to_musicxml(vocalparse_events, 100, musicxml)

    svg_result = render(
        musicxml, tmp_path, formats=("jianpu",), jianpu_format="svg"
    )
    pdf_result = render(
        musicxml, tmp_path, formats=("jianpu",), jianpu_format="pdf"
    )
    svg = svg_result["jianpu"]
    pdf = pdf_result["jianpu"]
    assert svg.is_file() and svg.stat().st_size > 500
    assert "<svg" in svg.read_text(encoding="utf-8")[:500]
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")


def test_vocalparse_musicxml_renders_real_staff_svg_with_lyrics_when_verovio_installed(
    tmp_path, vocalparse_events
):
    if importlib.util.find_spec("verovio") is None:
        pytest.skip("Verovio is not installed")
    from musicmaster.core.render import render

    musicxml = tmp_path / "vocalparse-staff.musicxml"
    vocalparse_events_to_musicxml(vocalparse_events, 100, musicxml)
    artifacts = render(musicxml, tmp_path / "staff", formats=("staff",))
    staff = artifacts["staff"]

    assert staff.is_file() and staff.stat().st_size > 500
    svg = staff.read_text(encoding="utf-8")
    assert "<svg" in svg[:500]
    # Verovio should carry the MusicXML lyric syllables into visible SVG text.
    for syllable in ("如", "果", "世", "界", "变", "换", "太", "快"):
        assert syllable in svg


def test_dual_notation_render_can_require_both_outputs(tmp_path, monkeypatch):
    render_module = importlib.import_module("musicmaster.core.render")
    captured = {}

    def fake_render(musicxml, out_dir, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "staff": tmp_path / "staff.svg",
            "jianpu": tmp_path / "jianpu.svg",
        }

    monkeypatch.setattr(render_module, "render", fake_render)
    parsed = {
        "bpm": 100,
        "words": ["你"],
        "pitches": [60],
        "notes": ["NOTE_4"],
    }

    artifacts = render_vocalparse_result(
        parsed, tmp_path / "strict-score", require_all=True
    )

    assert captured["kwargs"]["formats"] == ("staff", "jianpu")
    assert captured["kwargs"]["require_all"] is True
    assert set(artifacts) == {"musicxml", "staff", "jianpu"}


def test_saved_vocalparse_json_cli_renders_without_model_inference(tmp_path, monkeypatch):
    import json
    import runpy

    input_json = tmp_path / "saved-vocalparse.json"
    input_json.write_text(
        json.dumps({
            "bpm": 100,
            "words": ["你"],
            "pitches": [60],
            "notes": ["NOTE_4"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    captured = {}
    expected = {
        "musicxml": tmp_path / "out" / "vocalparse.musicxml",
        "staff": tmp_path / "out" / "staff.svg",
        "jianpu": tmp_path / "out" / "jianpu.svg",
    }

    import musicmaster.core.vocalparse as vocalparse_module

    def fake_render(parsed, output_dir, **kwargs):
        captured["parsed"] = parsed
        captured["output_dir"] = output_dir
        captured["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(vocalparse_module, "render_vocalparse_result", fake_render)
    namespace = runpy.run_path(
        str(__import__("pathlib").Path(__file__).parents[1] / "scripts" / "render_vocalparse_json.py")
    )
    artifacts = namespace["render_file"](input_json, tmp_path / "out")

    assert artifacts == expected
    assert captured["parsed"]["words"] == ["你"]
    assert captured["kwargs"]["require_all"] is True


def test_saved_vocalparse_json_cli_allows_partial_render_when_requested(tmp_path, monkeypatch):
    import json
    import runpy
    from pathlib import Path

    input_json = tmp_path / "saved-vocalparse.json"
    input_json.write_text(
        json.dumps({"bpm": 100, "words": ["你"], "pitches": [60], "notes": ["NOTE_4"]}),
        encoding="utf-8",
    )
    captured = {}
    import musicmaster.core.vocalparse as vocalparse_module

    def fake_render(parsed, output_dir, **kwargs):
        captured.update(kwargs)
        return {"musicxml": Path(output_dir) / "vocalparse.musicxml"}

    monkeypatch.setattr(vocalparse_module, "render_vocalparse_result", fake_render)
    script = Path(__file__).parents[1] / "scripts" / "render_vocalparse_json.py"
    namespace = runpy.run_path(str(script))
    namespace["render_file"](input_json, tmp_path / "out", require_all=False)

    assert captured["require_all"] is False


def test_saved_vocalparse_json_cli_reports_invalid_json(tmp_path):
    import runpy
    from pathlib import Path

    input_json = tmp_path / "broken.json"
    input_json.write_text("{not valid JSON", encoding="utf-8")
    namespace = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "render_vocalparse_json.py")
    )

    with pytest.raises(ValueError, match="Invalid JSON"):
        namespace["render_file"](input_json, tmp_path / "out")


def test_saved_vocalparse_json_cli_rejects_missing_model_fields(tmp_path):
    import json
    import runpy
    from pathlib import Path

    input_json = tmp_path / "incomplete.json"
    input_json.write_text(json.dumps({"bpm": 100}), encoding="utf-8")
    namespace = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "render_vocalparse_json.py")
    )

    with pytest.raises(ValueError, match="missing required keys"):
        namespace["render_file"](input_json, tmp_path / "out")
