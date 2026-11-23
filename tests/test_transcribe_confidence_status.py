import numpy as np

from musicmaster.transcribe import confidence


def _mock_tracks(monkeypatch, *, frames=10, crepe_pitch=60.0, pyin_pitch=60.0,
                 crepe_conf=0.9, pyin_voiced=0.9):
    t = np.arange(frames, dtype=float) * 0.01
    cm = np.full(frames, crepe_pitch, dtype=float)
    pm = np.full(frames, pyin_pitch, dtype=float)
    cc = np.full(frames, crepe_conf, dtype=float)
    pv = np.full(frames, pyin_voiced, dtype=float)
    monkeypatch.setattr(
        confidence,
        "_frame_tracks",
        lambda *args, **kwargs: (t, cm, cc, pm, pv),
    )


def _note(midi=60, start=0.0, end=0.1):
    return {"midi": midi, "start_s": start, "end_s": end}


def test_sufficient_agreement_is_high_confidence(monkeypatch):
    _mock_tracks(monkeypatch)

    result = confidence.assess("unused.wav", [_note()], key="C", gate_tier="好")
    note = result["notes"][0]

    assert note["status"] == "高可信"
    assert note["validation_frames"] == 10
    assert note["validation_coverage"] == 1.0
    assert note["agree"] == 1.0
    assert note["conf"] is not None
    assert result["statuses"]["高可信"] == 1


def test_no_overlap_is_pending_not_full_score(monkeypatch):
    _mock_tracks(monkeypatch, pyin_voiced=0.0)

    result = confidence.assess("unused.wav", [_note()], key="C", gate_tier="好")
    note = result["notes"][0]

    assert note["status"] == "待验证"
    assert note["agree"] is None
    assert note["conf"] is None
    assert "双模型验证证据不足" in note["reasons"]
    assert result["statuses"]["待验证"] == 1
    assert result["scored_notes"] == 0


def test_too_few_common_frames_are_pending(monkeypatch):
    t = np.arange(10, dtype=float) * 0.01
    cm = np.full(10, 60.0)
    pm = np.full(10, 60.0)
    cc = np.full(10, 0.9)
    pv = np.zeros(10)
    pv[:2] = 0.9
    monkeypatch.setattr(
        confidence,
        "_frame_tracks",
        lambda *args, **kwargs: (t, cm, cc, pm, pv),
    )

    result = confidence.assess("unused.wav", [_note()], key="C", gate_tier="好")
    note = result["notes"][0]

    assert note["validation_frames"] == 2
    assert note["agree"] is None
    assert note["status"] == "待验证"


def test_model_disagreement_is_suspect(monkeypatch):
    _mock_tracks(monkeypatch, crepe_pitch=60.0, pyin_pitch=62.0)

    result = confidence.assess("unused.wav", [_note()], key="C", gate_tier="好")
    note = result["notes"][0]

    assert note["agree"] == 0.0
    assert note["status"] == "存疑"
    assert "两算法分歧" in note["reasons"]


def test_three_consecutive_out_of_key_notes_are_suspect(monkeypatch):
    _mock_tracks(monkeypatch, frames=30, crepe_pitch=61.0, pyin_pitch=61.0)
    notes = [
        _note(midi=61, start=0.0, end=0.1),
        _note(midi=61, start=0.1, end=0.2),
        _note(midi=61, start=0.2, end=0.3),
    ]

    result = confidence.assess("unused.wav", notes, key="C", gate_tier="好")

    assert all(note["status"] == "存疑" for note in result["notes"])
    assert result["statuses"]["存疑"] == 3


def test_two_consecutive_out_of_key_notes_are_pending(monkeypatch):
    _mock_tracks(monkeypatch, frames=20, crepe_pitch=61.0, pyin_pitch=61.0)
    notes = [
        _note(midi=61, start=0.0, end=0.1),
        _note(midi=61, start=0.1, end=0.2),
    ]

    result = confidence.assess("unused.wav", notes, key="C", gate_tier="好")

    assert all(note["status"] == "待验证" for note in result["notes"])
    assert result["statuses"]["待验证"] == 2


def test_out_of_key_notes_separated_by_rest_are_not_one_run(monkeypatch):
    _mock_tracks(monkeypatch, frames=120, crepe_pitch=61.0, pyin_pitch=61.0)
    notes = [
        _note(midi=61, start=0.0, end=0.1),
        _note(midi=61, start=1.0, end=1.1),
    ]

    result = confidence.assess("unused.wav", notes, key="C", gate_tier="好")

    assert all(note["status"] == "高可信" for note in result["notes"])
    assert result["passages"] == []


def test_same_status_passages_split_after_long_gap(monkeypatch):
    _mock_tracks(monkeypatch, frames=220, crepe_conf=0.65)
    notes = [
        _note(midi=60, start=0.0, end=0.1),
        _note(midi=60, start=2.0, end=2.1),
    ]

    result = confidence.assess("unused.wav", notes, key="C", gate_tier="好")

    assert all(note["status"] == "待验证" for note in result["notes"])
    assert len(result["passages"]) == 2


def test_single_chromatic_note_is_not_automatically_suspect(monkeypatch):
    _mock_tracks(monkeypatch, crepe_pitch=61.0, pyin_pitch=61.0)

    result = confidence.assess("unused.wav", [_note(midi=61)], key="C", gate_tier="好")
    note = result["notes"][0]

    assert note["in_key"] is False
    assert note["status"] == "高可信"
    assert "单个调外(也可能是真变化音)" in note["reasons"]


def test_low_crepe_confidence_is_pending(monkeypatch):
    _mock_tracks(monkeypatch, crepe_conf=0.65)

    result = confidence.assess("unused.wav", [_note()], key="C", gate_tier="好")
    note = result["notes"][0]

    assert note["status"] == "待验证"
    assert "CREPE自信度偏低" in note["reasons"]
