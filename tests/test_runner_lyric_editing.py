import importlib
from pathlib import Path

_render_module = importlib.import_module("musicmaster.core.render")
from musicmaster.transcribe import autopilot
from musicmaster.web import runners


MONOPHONIC_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>
"""


class FakeJob:
    def __init__(self, job_dir):
        self.job_dir = str(job_dir)
        self.stages = []

    def set_stage(self, message, progress):
        self.stages.append((message, progress))


class FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def test_non_crepe_engine_exposes_lyrics_for_monophonic_musicxml(tmp_path, monkeypatch):
    job = FakeJob(tmp_path)

    def fake_autopilot(argv):
        out_dir = Path(argv[argv.index("--out") + 1])
        (out_dir / "out.musicxml").write_text(MONOPHONIC_MUSICXML, encoding="utf-8")
        (out_dir / "报告.md").write_text("test report", encoding="utf-8")
        return 0

    def fake_render(musicxml, out_dir, *, formats, jianpu_format="svg", require_all=False):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        result = {}
        if "staff" in formats:
            staff = out / "staff.svg"
            staff.write_text("<svg>staff</svg>", encoding="utf-8")
            result["staff"] = staff
        if "jianpu" in formats:
            extension = "pdf" if jianpu_format == "pdf" else "svg"
            score = out / f"jianpu.{extension}"
            score.write_text("<svg>jianpu</svg>" if extension == "svg" else "PDF", encoding="utf-8")
            result["jianpu"] = score
        return result

    monkeypatch.setattr(autopilot, "main", fake_autopilot)
    monkeypatch.setattr(runners.threading, "Thread", FakeThread)
    monkeypatch.setattr(_render_module, "render", fake_render)
    monkeypatch.setattr(runners, "_downloads", lambda *args, **kwargs: [])
    monkeypatch.setattr(runners, "_parse_confidence", lambda *_: (None, None))

    result = runners.run_transcribe(
        job, "unused-audio.wav", engine="basic-pitch", lyrics_text="你好"
    )

    assert result["ok"] is True
    assert [slot["lyric"] for slot in result["lyric_slots"]] == ["你", "好"]
    assert result["lyrics_info"]["alignmentStatus"] == "aligned"
    assert result["staff_svg"] == "<svg>staff</svg>"
    assert result["jianpu_svg"] == "<svg>jianpu</svg>"
