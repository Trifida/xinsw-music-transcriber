from pathlib import Path
import xml.etree.ElementTree as ET

from musicmaster.transcribe.lyrics import attach_lyrics_to_musicxml, tokenize_lyrics


def test_tokenize_chinese_latin_words_and_punctuation():
    assert tokenize_lyrics("春 风，又见 Hello world! 你好吗？") == [
        "春", "风，", "又", "见", "Hello", "world!", "你", "好", "吗？"
    ]


def test_tokenize_apostrophes_and_opening_punctuation():
    assert tokenize_lyrics("“don't stop”") == ["“don't", "stop”"]


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
