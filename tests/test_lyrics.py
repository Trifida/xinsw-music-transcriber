from pathlib import Path
import xml.etree.ElementTree as ET

from musicmaster.transcribe.lyrics import attach_lyrics_to_musicxml, tokenize_lyrics


def test_tokenize_chinese_latin_words_and_punctuation():
    assert tokenize_lyrics("春 风，又见 Hello world! 你好吗？") == [
        "春", "风，", "又", "见", "Hello", "world!", "你", "好", "吗？"
    ]


def test_tokenize_apostrophes_and_opening_punctuation():
    assert tokenize_lyrics("“don't stop”") == ["“don't", "stop”"]


def test_tokenize_em_dash_as_explicit_melisma_slot():
    assert tokenize_lyrics("春——风") == ["春", "—", "—", "风"]


def test_attach_lyrics_skips_rests_and_tied_continuations(tmp_path: Path):
    source = tmp_path / "score.musicxml"
    source.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise xmlns="http://www.musicxml.org/ns/musicxml">
  <part id="P1"><measure number="1">
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
    <note><rest/><duration>1</duration></note>
    <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><tie type="start"/></note>
    <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><tie type="stop"/></note>
    <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
  </measure></part>
</score-partwise>""", encoding="utf-8")
    result = attach_lyrics_to_musicxml(source, ["春", "风", "又"])
    root = ET.parse(source).getroot()
    notes = [node for node in root.iter() if node.tag.endswith("note")]
    lyric_texts = [
        next((child.text for child in note.iter() if child.tag.endswith("text")), None)
        for note in notes
    ]
    assert result == {
        "lyricSlots": 3, "tokenCount": 3, "assignedCount": 3, "unassignedCount": 0
    }
    assert lyric_texts == ["春", None, "风", None, "又"]


def test_unassigned_lyrics_are_reported(tmp_path: Path):
    source = tmp_path / "score.musicxml"
    source.write_text(
        '<score-partwise><part><measure><note><pitch><step>C</step><octave>4</octave></pitch></note></measure></part></score-partwise>',
        encoding="utf-8",
    )
    result = attach_lyrics_to_musicxml(source, ["一", "二"])
    assert result["assignedCount"] == 1
    assert result["unassignedCount"] == 1


def test_extract_lyric_slots_skips_rests_and_tied_continuations(tmp_path: Path):
    from musicmaster.transcribe.lyrics import extract_lyric_slots

    source = tmp_path / "slots.musicxml"
    source.write_text("""<score-partwise>
      <part><measure>
        <note><pitch><step>C</step><octave>4</octave></pitch><lyric><text>春</text></lyric></note>
        <note><rest/></note>
        <note><pitch><step>D</step><octave>4</octave></pitch><tie type="start"/></note>
        <note><pitch><step>D</step><octave>4</octave></pitch><tie type="stop"/></note>
        <note><pitch><step>E</step><octave>4</octave></pitch></note>
      </measure></part>
    </score-partwise>""", encoding="utf-8")
    assert extract_lyric_slots(source) == [
        {"index": 0, "pitch": "C4", "lyric": "春"},
        {"index": 2, "pitch": "D4", "lyric": ""},
        {"index": 4, "pitch": "E4", "lyric": ""},
    ]


def test_extract_lyric_slots_formats_decimal_accidentals(tmp_path: Path):
    from musicmaster.transcribe.lyrics import extract_lyric_slots

    source = tmp_path / "accidentals.musicxml"
    source.write_text("""<score-partwise><part><measure>
      <note><pitch><step>C</step><alter>1.0</alter><octave>4</octave></pitch></note>
      <note><pitch><step>D</step><alter>-1.0</alter><octave>4</octave></pitch></note>
      <note><pitch><step>E</step><alter>0.5</alter><octave>4</octave></pitch></note>
    </measure></part></score-partwise>""", encoding="utf-8")
    assert [slot["pitch"] for slot in extract_lyric_slots(source)] == ["C#4", "Db4", "E(+0.5)4"]


def test_apply_lyric_assignments_preserves_empty_and_melisma_slots(tmp_path: Path):
    from musicmaster.transcribe.lyrics import apply_lyric_assignments, extract_lyric_slots

    source = tmp_path / "edit.musicxml"
    source.write_text("""<score-partwise>
      <part><measure>
        <note><pitch><step>C</step><octave>4</octave></pitch></note>
        <note><rest/></note>
        <note><pitch><step>D</step><octave>4</octave></pitch></note>
        <note><pitch><step>E</step><octave>4</octave></pitch></note>
      </measure></part>
    </score-partwise>""", encoding="utf-8")
    result = apply_lyric_assignments(source, ["春", "", "—"])
    assert result["lyricSlots"] == 3
    assert result["assignedCount"] == 2
    assert result["emptyCount"] == 1
    assert [slot["lyric"] for slot in extract_lyric_slots(source)] == ["春", "", "—"]


def test_apply_lyric_assignments_rejects_wrong_slot_count(tmp_path: Path):
    from musicmaster.transcribe.lyrics import apply_lyric_assignments

    source = tmp_path / "count.musicxml"
    source.write_text(
        '<score-partwise><part><measure><note><pitch><step>C</step><octave>4</octave></pitch></note></measure></part></score-partwise>',
        encoding="utf-8",
    )
    import pytest
    with pytest.raises(ValueError, match="槽位数量不匹配"):
        apply_lyric_assignments(source, [])


def test_join_lyric_slots_keeps_latin_word_spacing_without_chinese_spaces():
    from musicmaster.transcribe.lyrics import join_lyric_slots

    assert join_lyric_slots(["春", "风，", "Hello", "world!", "Again", "你", "好"]) == "春风，Hello world! Again你好"
    assert join_lyric_slots(["", "Hello", "", "world"]) == "Hello world"


def test_notation_level_tie_stop_is_not_a_new_lyric_slot(tmp_path: Path):
    from musicmaster.transcribe.lyrics import extract_lyric_slots, apply_lyric_assignments

    source = tmp_path / "notation-tie.musicxml"
    source.write_text("""<score-partwise>
      <part><measure>
        <note><pitch><step>C</step><octave>4</octave></pitch></note>
        <note><pitch><step>C</step><octave>4</octave></pitch>
          <notations><tied type="stop"/></notations>
        </note>
        <note><pitch><step>D</step><octave>4</octave></pitch><play/></note>
      </measure></part>
    </score-partwise>""", encoding="utf-8")

    assert len(extract_lyric_slots(source)) == 2
    apply_lyric_assignments(source, ["长", "音"])
    root = ET.parse(source).getroot()
    notes = [node for node in root.iter() if node.tag.endswith("note")]
    assert [next((n.text for n in note.iter() if n.tag.endswith("text")), None)
            for note in notes] == ["长", None, "音"]
    last_children = [child.tag.rsplit("}", 1)[-1] for child in notes[-1]]
    assert last_children.index("lyric") < last_children.index("play")


def test_jianpu_ly_import_keeps_musicxml_lyrics(tmp_path: Path):
    from music21 import note, stream
    from musicmaster.core.render import musicxml_to_lilypond

    part = stream.Part()
    first = note.Note("C4", quarterLength=1)
    first.lyric = "春"
    second = note.Note("D4", quarterLength=1)
    second.lyric = "风"
    part.append(first)
    part.append(second)
    score = stream.Score()
    score.append(part)
    source = tmp_path / "lyrics.musicxml"
    score.write("musicxml", fp=str(source))

    lilypond_source = musicxml_to_lilypond(source)
    assert "春" in lilypond_source
    assert "风" in lilypond_source

def test_save_lyrics_api_updates_musicxml_and_result_manifest(tmp_path, monkeypatch):
    import importlib
    from musicmaster.web import server
    from musicmaster.web.jobs import Job

    source = tmp_path / "out.musicxml"
    source.write_text("""<score-partwise>
      <part><measure>
        <note><pitch><step>C</step><octave>4</octave></pitch></note>
        <note><pitch><step>D</step><octave>4</octave></pitch></note>
      </measure></part>
    </score-partwise>""", encoding="utf-8")
    job = Job(
        id="lyric-edit-test",
        kind="transcribe",
        job_dir=str(tmp_path),
        status="done",
        result={"ok": True, "lyrics_slots": [
            {"index": 0, "pitch": "C4", "lyric": "旧"},
            {"index": 1, "pitch": "D4", "lyric": "词"},
        ], "downloads": [], "report_md": ""},
    )

    class Manager:
        def get(self, job_id):
            return job if job_id == job.id else None

        def file_path(self, job_id, name):
            target = tmp_path / name
            return target if job_id == job.id and target.is_file() else None

    monkeypatch.setattr(server, "JM", Manager())
    for stale_name in ("staff.svg", "jianpu.svg", "jianpu.pdf"):
        (tmp_path / stale_name).write_text("<svg>old preview</svg>", encoding="utf-8")
    render_module = importlib.import_module("musicmaster.core.render")
    monkeypatch.setattr(render_module, "render", lambda *args, **kwargs: {})

    # One lyric slot per pitched note in the MusicXML.
    job.result["lyrics_slots"] = [
        {"index": 0, "pitch": "C4", "lyric": "旧"},
        {"index": 1, "pitch": "D4", "lyric": "词"},
    ]
    response = server.api_save_lyrics(
        job.id, server.LyricEditsRequest(assignments=["春", "—"])
    )
    assert response["ok"] is True
    assert [slot["lyric"] for slot in response["lyrics_slots"]] == ["春", "—"]
    assert job.result["lyrics_info"]["alignmentStatus"] == "manually-edited"
    assert "out.musicxml" in [item["name"] for item in job.result["downloads"]]
    assert (tmp_path / "lyrics_alignment.json").is_file()
    assert "逐音歌词人工校正" in job.result["report_md"]
    assert not (tmp_path / "staff.svg").exists()
    assert not (tmp_path / "jianpu.svg").exists()
    assert not (tmp_path / "jianpu.pdf").exists()
    assert response["render_warnings"]
