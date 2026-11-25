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
