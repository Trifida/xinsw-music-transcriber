# -*- coding: utf-8 -*-
"""Unit tests for the lightweight SmartKeyAnalyzer (no audio/model downloads)."""


def _notes(pitches, durations=None):
    durations = durations or [0.5] * len(pitches)
    out = []
    t = 0.0
    for pitch, dur in zip(pitches, durations):
        out.append({"midi": pitch, "start_s": t, "end_s": t + dur})
        t += dur
    return out


def test_smart_key_returns_ranked_candidates_without_transposing():
    from musicmaster.transcribe.smart_key import analyze_key

    source = _notes([60, 62, 64, 65, 67, 69, 71, 60],
                    [0.6, 0.3, 0.6, 0.3, 0.6, 0.3, 0.6, 1.2])
    before = [n["midi"] for n in source]
    result = analyze_key(source, tempo=100)

    assert result["key"]
    assert result["mode"] in ("major", "minor")
    assert result["status"] in ("probable", "ambiguous", "insufficient-data")
    assert 0.0 <= result["confidence"] <= 1.0
    assert len(result["candidates"]) == 5
    assert result["transposed"] is False
    assert [n["midi"] for n in source] == before
    assert result["tempo_used"] == 100


def test_smart_key_reports_insufficient_data_for_empty_input():
    from musicmaster.transcribe.smart_key import analyze_key

    result = analyze_key([])
    assert result["key"] is None
    assert result["status"] == "insufficient-data"
    assert result["candidates"] == []


def test_smart_key_keeps_chromatic_notes_as_evidence_not_errors():
    from musicmaster.transcribe.smart_key import analyze_key

    source = _notes([60, 62, 64, 65, 66, 67, 71, 60])
    result = analyze_key(source)
    assert result["key"] is not None
    assert result["transposed"] is False
    assert any("调性轮廓" in item for item in result["evidence"])
