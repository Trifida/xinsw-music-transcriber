# -*- coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "setup_sep.py"


def _load_setup_sep():
    spec = importlib.util.spec_from_file_location("musicmaster_setup_sep_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_sep_uses_existing_requirements_manifest():
    setup_sep = _load_setup_sep()
    assert setup_sep.SEP_REQUIREMENTS == REPO / "requirements" / "requirements-sep.txt"
    assert setup_sep.SEP_REQUIREMENTS.is_file()


def test_setup_sep_passes_correct_requirements_file_to_pip(tmp_path, monkeypatch):
    setup_sep = _load_setup_sep()
    calls = []
    monkeypatch.setattr(setup_sep.venv, "create", lambda *args, **kwargs: None)
    monkeypatch.setattr(setup_sep.subprocess, "check_call", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT), "--venv", str(tmp_path / "venv"), "--cuda", "cu124"
    ])

    setup_sep.main()

    requirements_calls = [cmd for cmd in calls if "-r" in cmd]
    assert len(requirements_calls) == 1
    assert requirements_calls[0][requirements_calls[0].index("-r") + 1] == str(setup_sep.SEP_REQUIREMENTS)
