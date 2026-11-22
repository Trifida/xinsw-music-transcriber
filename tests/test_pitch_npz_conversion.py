"""Tests for converting saved numeric pitch archives without model inference."""
from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.convert_pitch_npz import convert_npz_to_pitch_json


def test_convert_frequency_npz_with_explicit_time_and_confidence(tmp_path):
    source = tmp_path / "saved.npz"
    destination = tmp_path / "track.json"
    np.savez(
        source,
        timestamps=np.array([30.0, 30.01, 30.02]),
        f0_hz=np.array([261.6256, 0.0, 293.6648]),
        periodicity=np.array([0.95, 0.1, 0.9]),
    )

    result = convert_npz_to_pitch_json(
        source,
        destination,
        time_key="timestamps",
        frequency_key="f0_hz",
        confidence_key="periodicity",
    )
    saved = json.loads(destination.read_text(encoding="utf-8"))

    assert result["frame_count"] == 3
    assert saved["frames"][0]["time_sec"] == 30.0
    assert saved["frames"][0]["frequency_hz"] == pytest.approx(261.6256)
    assert saved["frames"][1]["frequency_hz"] == 0.0
    assert saved["frames"][1]["confidence"] == pytest.approx(0.1)


def test_convert_midi_npz_with_confirmed_hop_and_start_time(tmp_path):
    source = tmp_path / "midi.npz"
    destination = tmp_path / "track.json"
    np.savez(source, midi=np.array([60.0, 61.0, 0.0]))

    result = convert_npz_to_pitch_json(
        source,
        destination,
        hop_seconds=0.01,
        pitch_midi_key="midi",
        start_time_sec=30.0,
    )

    assert [frame["time_sec"] for frame in result["frames"]] == pytest.approx(
        [30.0, 30.01, 30.02]
    )
    assert result["frames"][0]["pitch_midi"] == 60.0
    assert result["frames"][2]["pitch_midi"] is None


def test_converter_requires_explicit_pitch_and_timing_keys(tmp_path):
    source = tmp_path / "saved.npz"
    np.savez(source, f0=np.array([220.0]))

    with pytest.raises(ValueError, match="exactly one of frequency_key"):
        convert_npz_to_pitch_json(
            source, tmp_path / "out.json",
            hop_seconds=0.01,
        )

    with pytest.raises(ValueError, match="exactly one of time_key"):
        convert_npz_to_pitch_json(
            source, tmp_path / "out.json",
            frequency_key="f0",
        )


def test_converter_rejects_mismatched_array_lengths(tmp_path):
    source = tmp_path / "saved.npz"
    np.savez(
        source,
        times=np.array([0.0, 0.01]),
        f0=np.array([220.0, 221.0]),
        confidence=np.array([0.9]),
    )

    with pytest.raises(ValueError, match="identical lengths"):
        convert_npz_to_pitch_json(
            source, tmp_path / "out.json",
            time_key="times",
            frequency_key="f0",
            confidence_key="confidence",
        )


def test_converter_rejects_non_numeric_or_invalid_values(tmp_path):
    source = tmp_path / "saved.npz"
    np.savez(
        source,
        times=np.array([0.0, 0.01]),
        f0=np.array([220.0, -1.0]),
    )

    with pytest.raises(ValueError, match="nonnegative"):
        convert_npz_to_pitch_json(
            source, tmp_path / "out.json",
            time_key="times",
            frequency_key="f0",
        )


def test_converter_refuses_unknown_keys_and_object_arrays(tmp_path):
    source = tmp_path / "saved.npz"
    np.savez(
        source,
        f0=np.array([220.0]),
        unsafe=np.array([{"secret": "value"}], dtype=object),
    )

    with pytest.raises(ValueError, match="not found"):
        convert_npz_to_pitch_json(
            source, tmp_path / "out.json",
            time_key="time",
            frequency_key="f0",
        )

    with pytest.raises(ValueError, match="cannot be safely read"):
        convert_npz_to_pitch_json(
            source, tmp_path / "out.json",
            time_key="f0",
            frequency_key="unsafe",
        )
