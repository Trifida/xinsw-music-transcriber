from pathlib import Path
from types import SimpleNamespace

import pytest

from musicmaster.core import render as render_function
import importlib


render_module = importlib.import_module("musicmaster.core.render")


def _inputs(tmp_path: Path):
    ly_path = tmp_path / "jianpu.ly"
    ly_path.write_text("\\score { { c'4 } }", encoding="utf-8")
    out_base = tmp_path / "jianpu"
    return ly_path, out_base


def test_lilypond_nonzero_exit_is_failure_even_if_partial_file_exists(tmp_path, monkeypatch):
    ly_path, out_base = _inputs(tmp_path)
    stale = out_base.with_suffix(".svg")
    stale.write_text("<svg>old result</svg>", encoding="utf-8")
    monkeypatch.setattr(render_module, "lilypond_executable", lambda: "/fake/lilypond")

    def fake_run(*args, **kwargs):
        # Simulate LilyPond leaving a partial SVG before reporting failure.
        stale.write_text("<svg>partial result</svg>", encoding="utf-8")
        return SimpleNamespace(returncode=1, stderr=b"engraving failed", stdout=b"")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="returncode=1") as exc:
        render_module._run_lilypond(ly_path, out_base, "svg", 5)

    assert "engraving failed" in str(exc.value)


def test_lilypond_success_requires_fresh_output(tmp_path, monkeypatch):
    ly_path, out_base = _inputs(tmp_path)
    stale = out_base.with_suffix(".svg")
    stale.write_text("<svg>old result</svg>", encoding="utf-8")
    monkeypatch.setattr(render_module, "lilypond_executable", lambda: "/fake/lilypond")

    def fake_run(*args, **kwargs):
        assert not stale.exists(), "old output must be removed before rendering"
        stale.write_text("<svg>fresh result</svg>", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)

    result = render_module._run_lilypond(ly_path, out_base, "svg", 5)

    assert result == stale
    assert "fresh result" in result.read_text(encoding="utf-8")


def test_lilypond_zero_exit_without_output_is_failure(tmp_path, monkeypatch):
    ly_path, out_base = _inputs(tmp_path)
    monkeypatch.setattr(render_module, "lilypond_executable", lambda: "/fake/lilypond")
    monkeypatch.setattr(
        render_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=b"", stdout=b""),
    )

    with pytest.raises(RuntimeError, match="未产出预期"):
        render_module._run_lilypond(ly_path, out_base, "svg", 5)
