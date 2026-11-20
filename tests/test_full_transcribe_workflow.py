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


def test_full_workflow_separates_then_transcribes_and_writes_manifest(tmp_path, monkeypatch):
    source = tmp_path / "song.mp3"
    source.write_bytes(b"test audio")
    output = tmp_path / "job"
    calls = []

    def fake_separate_main(argv):
        calls.append(("separate", argv))
        args = dict(zip(argv[::2], argv[1::2]))
        sep_root = Path(args["--out-dir"])
        (sep_root / "1_分离").mkdir(parents=True)
        (sep_root / "1_分离" / "accomp.wav").write_bytes(b"accompaniment")
        (sep_root / "最终_song.wav").write_bytes(b"lead vocal")
        return 0

    def fake_autopilot_main(argv, progress_callback=None):
        calls.append(("transcribe", argv))
        args = dict(zip(argv[1::2], argv[2::2]))
        out = Path(args["--out"])
        for name in ("notes.json", "out.mid", "out.musicxml"):
            (out / name).write_bytes(b"artifact")
        if progress_callback:
            progress_callback(49, "识别完成")
        return 0

    fake_separator = SimpleNamespace(main=fake_separate_main)
    fake_autopilot = SimpleNamespace(
        ENGINES={"crepe": "CREPE"},
        main=fake_autopilot_main,
    )

    def fake_import(name):
        if name == "musicmaster.separate.pipeline":
            return fake_separator
        if name == "musicmaster.transcribe.autopilot":
            return fake_autopilot
        return importlib.import_module(name)

    monkeypatch.setattr(full_transcribe.importlib, "import_module", fake_import)
    progress = []
    result = full_transcribe.run_full_transcription(
        source, output, progress_callback=lambda p, label: progress.append((p, label))
    )

    assert [call[0] for call in calls] == ["separate", "transcribe"]
    assert calls[1][1][0] == str(output / "separation" / "最终_song.wav")
    assert result["separation"]["accompaniment"] == "separation/1_分离/accomp.wav"
    assert result["transcription"]["files"]["out.mid"] == "transcription/out.mid"
    assert json.loads((output / "job_result.json").read_text(encoding="utf-8")) == result
    assert progress[-1][0] == 1.0


def test_full_workflow_refuses_to_overwrite_existing_task_outputs(tmp_path):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio")
    output = tmp_path / "job"
    (output / "separation").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        full_transcribe.run_full_transcription(source, output)
