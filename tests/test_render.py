from pathlib import Path
from types import SimpleNamespace

import pytest

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



def test_best_effort_keeps_jianpu_source_without_lilypond(tmp_path, monkeypatch):
    musicxml = tmp_path / "input.musicxml"
    musicxml.write_text("<score-partwise/>", encoding="utf-8")
    monkeypatch.setattr(render_module, "_verovio_importable", lambda: False)
    monkeypatch.setattr(render_module, "_jianpu_ly_importable", lambda: True)
    monkeypatch.setattr(
        render_module, "musicxml_to_lilypond", lambda _path: "\\version \"2.24.0\"\n\\score { { c'4 } }"
    )
    monkeypatch.setattr(render_module, "lilypond_executable", lambda: None)

    result = render_module.render(
        musicxml, tmp_path / "out", formats=("staff", "jianpu"), require_all=False
    )

    assert set(result) == {"jianpu_ly"}
    assert result["jianpu_ly"].is_file()
    assert result["jianpu_ly"].read_text(encoding="utf-8").startswith("\\version")


def test_best_effort_staff_survives_jianpu_source_failure(tmp_path, monkeypatch):
    musicxml = tmp_path / "input.musicxml"
    musicxml.write_text("<score-partwise/>", encoding="utf-8")
    staff = tmp_path / "out" / "staff.svg"

    def fake_staff(_source, destination, *, page=1):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("<svg>staff</svg>", encoding="utf-8")
        return destination

    monkeypatch.setattr(render_module, "_verovio_importable", lambda: True)
    monkeypatch.setattr(render_module, "render_staff_svgs", lambda _source, _out, stem="staff": [fake_staff(_source, staff, page=1)])
    monkeypatch.setattr(render_module, "_jianpu_ly_importable", lambda: True)
    monkeypatch.setattr(
        render_module,
        "musicxml_to_lilypond",
        lambda _path: (_ for _ in ()).throw(RuntimeError("jianpu conversion failed")),
    )

    result = render_module.render(
        musicxml, tmp_path / "out", formats=("staff", "jianpu"), require_all=False
    )

    assert result == {"staff": staff}
    assert staff.is_file()



def test_render_staff_svgs_writes_every_page_and_legacy_first_page(tmp_path, monkeypatch):
    import sys
    from types import ModuleType

    musicxml = tmp_path / "input.musicxml"
    musicxml.write_text("<score-partwise/>", encoding="utf-8")

    class FakeToolkit:
        def __init__(self, *_args):
            self.pages = []

        def setInputFrom(self, _kind):
            pass

        def loadData(self, _xml):
            return True

        def getPageCount(self):
            return 2

        def renderToSVG(self, page):
            self.pages.append(page)
            return f'<svg><text>page {page}</text></svg>'

    fake_verovio = ModuleType("verovio")
    fake_verovio.toolkit = FakeToolkit
    monkeypatch.setitem(sys.modules, "verovio", fake_verovio)
    monkeypatch.setattr(render_module, "_verovio_importable", lambda: True)
    monkeypatch.setattr(render_module, "_ascii_verovio_resource_dir", lambda: None)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    stale_page = output_dir / "staff-page-003.svg"
    stale_page.write_text("<svg>old page</svg>", encoding="utf-8")
    pages = render_module.render_staff_svgs(musicxml, output_dir)

    assert not stale_page.exists()
    assert [path.name for path in pages] == ["staff-page-001.svg", "staff-page-002.svg"]
    assert "page 1" in pages[0].read_text(encoding="utf-8")
    assert "page 2" in pages[1].read_text(encoding="utf-8")
    legacy = tmp_path / "out" / "staff.svg"
    assert legacy.is_file()
    assert legacy.read_text(encoding="utf-8") == pages[0].read_text(encoding="utf-8")
