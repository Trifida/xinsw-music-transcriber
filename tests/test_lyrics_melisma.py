from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from musicmaster.transcribe.lyrics import attach_lyrics_to_musicxml, tokenize_lyrics


def test_tokenize_explicit_melisma_and_lyricless_slots():
    assert tokenize_lyrics("你——好·啊") == ["你", "—", "—", "好", "·", "啊"]


def test_attach_lyrics_writes_musicxml_melisma_extensions(tmp_path: Path):
    source = tmp_path / "melisma.musicxml"
    note_xml = "".join(
        '<note><pitch><step>' + step + '</step><octave>4</octave></pitch><duration>1</duration></note>'
        for step in ("C", "D", "E", "F")
    )
    source.write_text(
        '<score-partwise><part><measure>' + note_xml + '</measure></part></score-partwise>',
        encoding="utf-8",
    )
    result = attach_lyrics_to_musicxml(source, ["你", "—", "—", "好"])
    root = ET.parse(source).getroot()
    notes = [node for node in root.iter() if node.tag.endswith("note")]
    lyrics = [next((child for child in note if child.tag.endswith("lyric")), None) for note in notes]
    assert result["assignedCount"] == 4
    assert lyrics[0].find("extend").attrib["type"] == "start"
    assert lyrics[1].find("extend").attrib["type"] == "continue"
    assert lyrics[2].find("extend").attrib["type"] == "stop"
    assert lyrics[3].find("text").text == "好"


def test_attach_lyrics_rejects_melisma_without_anchor(tmp_path: Path):
    source = tmp_path / "invalid-melisma.musicxml"
    source.write_text(
        '<score-partwise><part><measure><note><pitch><step>C</step><octave>4</octave></pitch></note></measure></part></score-partwise>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="延续符前面必须先有"):
        attach_lyrics_to_musicxml(source, ["—"])