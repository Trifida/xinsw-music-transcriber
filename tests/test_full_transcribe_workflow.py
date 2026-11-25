# -*- coding: utf-8 -*-
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from musicmaster.workflows import full_transcribe


def test_parse_stages_requires_separation_first():
    assert full_transcribe._parse_stages("1,2,3") == ["1", "2", "3"]
    assert full_transcribe._parse_stages("1") == ["1"]
    with pytest.raises(ValueError):
        full_transcribe._parse_stages("2,3")
    with pytest.raises(ValueError):
        full_transcribe._parse_stages("1,3,2")
    with pytest.raises(ValueError):
        full_transcribe._parse_stages("1,1")


def test_runner_progress_accepts_fraction_and_percent():
    job = full_transcribe._ProgressJob(Path("unused"), None, 0.58, 0.40)
    fractions = []
    job._callback = lambda progress, label: fractions.append(progress)
    job.set_stage("fraction", 0.5)
    job.set_stage("percent", 49)
    assert fractions == pytest.approx([0.78, 0.776])


def test_full_workflow_separates_then_transcribes_and_writes_manifest(tmp_path, monkeypatch):
    source = tmp_path / "song.mp3"
    source.write_bytes(b"test audio")
    output = tmp_path / "job"
    calls = []
    real_import_module = importlib.import_module

    def fake_separate(job, audio_path, stages, denoise):
        calls.append(("separate", audio_path, stages, denoise))
        d = Path(job.job_dir)
        (d / "1_分离").mkdir()
        (d / "1_分离" / "accomp.wav").write_bytes(b"accompaniment")
        (d / "最终_song.wav").write_bytes(b"lead vocal")
        return {
            "ok": True,
            "tracks": [
                {"name": "1_分离/accomp.wav"},
                {"name": "最终_song.wav"},
            ],
        }

    def fake_transcribe(job, audio_path, engine, key, lyrics_text=""):
        calls.append(("transcribe", audio_path, engine, key, lyrics_text))
        d = Path(job.job_dir)
        for name in ("notes.json", "out.mid", "out.musicxml"):
            (d / name).write_bytes(b"artifact")
        job.set_stage("CREPE progress", 49)
        return {"ok": True}

    fake_runners = SimpleNamespace(
        run_separate=fake_separate,
        run_transcribe=fake_transcribe,
    )

    def fake_import(name):
        if name == "musicmaster.web.runners":
            return fake_runners
        return real_import_module(name)

    monkeypatch.setattr(full_transcribe.importlib, "import_module", fake_import)
    progress = []
    result = full_transcribe.run_full_transcription(
        source, output, lyrics_text="春风又绿江南岸",
        progress_callback=lambda p, label: progress.append((p, label))
    )

    assert [call[0] for call in calls] == ["separate", "transcribe"]
    assert calls[0][2:] == ("1,2,3", "dereverb")
    assert calls[1][1] == str(output / "separation" / "最终_song.wav")
    assert calls[1][4] == "春风又绿江南岸"
    assert result["separation"]["accompaniment"] == "separation/1_分离/accomp.wav"
    assert result["transcription"]["files"]["out.mid"] == "transcription/out.mid"
    assert result["transcription"]["lyrics"]["source"] == "user-provided"
    assert json.loads((output / "job_result.json").read_text(encoding="utf-8")) == result
    assert progress[-1][0] == 1.0
    assert all(p <= 1.0 for p, _ in progress)


def test_full_workflow_refuses_to_overwrite_existing_task_outputs(tmp_path):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    output = tmp_path / "job"
    output.mkdir()
    (output / "separation").mkdir()
    with pytest.raises(FileExistsError):
        full_transcribe.run_full_transcription(source, output)
