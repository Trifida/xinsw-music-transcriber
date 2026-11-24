import importlib
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from musicmaster.web import server
from musicmaster.web import runners

render_module = importlib.import_module("musicmaster.core.render")


MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>
"""


class FakeJob:
    def __init__(self, job_dir: Path):
        self.kind = "transcribe"
        self.status = "done"
        self.result = {"ok": True, "downloads": []}
        self.job_dir = str(job_dir)
        self._lock = threading.Lock()


@pytest.fixture
def lyric_job(tmp_path, monkeypatch):
    job = FakeJob(tmp_path)
    (tmp_path / "out.musicxml").write_text(MUSICXML, encoding="utf-8")
    monkeypatch.setattr(server.JM, "get", lambda job_id: job if job_id == "job-1" else None)
    monkeypatch.setattr(runners, "_read_svg", lambda path: Path(path).read_text(encoding="utf-8"))
    return job


def test_manual_lyrics_api_renders_both_scores_and_updates_job(lyric_job, monkeypatch):
    calls = []

    def fake_render(musicxml, out_dir, *, formats, jianpu_format="svg", require_all=False):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        calls.append((tuple(formats), jianpu_format, require_all))
        result = {}
        if "staff" in formats:
            staff = out / "staff.svg"
            staff.write_text("<svg>staff</svg>", encoding="utf-8")
            result["staff"] = staff
        if "jianpu" in formats:
            ly = out / "jianpu.ly"
            ly.write_text("% jianpu source", encoding="utf-8")
            result["jianpu_ly"] = ly
            ext = "pdf" if jianpu_format == "pdf" else "svg"
            score = out / f"jianpu.{ext}"
            score.write_text(f"<svg>{ext}</svg>" if ext == "svg" else "PDF", encoding="utf-8")
            result["jianpu"] = score
        return result

    monkeypatch.setattr(render_module, "render", fake_render)

    response = server.api_update_job_lyrics("job-1", ["你", "—", "好"])

    assert response["ok"] is True
    assert calls == [
        (("staff", "jianpu"), "svg", True),
        (("jianpu",), "pdf", True),
    ]
    slots = response["result"]["lyric_slots"]
    assert [slot["lyric"] for slot in slots] == ["你", "—", "好"]
    assert response["result"]["staff_svg"] == "<svg>staff</svg>"
    assert response["result"]["jianpu_svg"] == "<svg>svg</svg>"
    assert (Path(lyric_job.job_dir) / "jianpu.pdf").read_text(encoding="utf-8") == "PDF"
    assert lyric_job.result is response["result"]


def test_manual_lyrics_api_does_not_replace_original_if_render_fails(lyric_job, monkeypatch):
    original = (Path(lyric_job.job_dir) / "out.musicxml").read_text(encoding="utf-8")

    def fail_render(*args, **kwargs):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(render_module, "render", fail_render)

    with pytest.raises(HTTPException) as exc:
        server.api_update_job_lyrics("job-1", ["你", "—", "好"])

    assert exc.value.status_code == 503
    assert (Path(lyric_job.job_dir) / "out.musicxml").read_text(encoding="utf-8") == original
    assert lyric_job.result == {"ok": True, "downloads": []}


def test_manual_lyrics_api_rejects_wrong_slot_count(lyric_job):
    with pytest.raises(HTTPException) as exc:
        server.api_update_job_lyrics("job-1", ["只有两个"])

    assert exc.value.status_code == 422
