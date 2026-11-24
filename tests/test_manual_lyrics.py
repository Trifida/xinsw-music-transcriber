import pytest
import xml.etree.ElementTree as ET

from musicmaster.core.vocalparse import align_manual_lyrics, vocalparse_events_to_musicxml, musicxml_lyric_alignment
from musicmaster.transcribe.lyrics import (
    attach_lyrics_to_musicxml, is_editable_melody_musicxml, read_lyric_slots,
)


def _events():
    return [
        {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60},
        {"start_beat": 1, "duration_beats": 1, "pitch_midi": 62},
        {"start_beat": 2, "duration_beats": 1, "is_rest": True},
        {"start_beat": 3, "duration_beats": 1, "pitch_midi": 64},
        {"start_beat": 4, "duration_beats": 1, "pitch_midi": 65},
        {"start_beat": 5, "duration_beats": 1, "pitch_midi": 67},
    ]


def test_manual_chinese_lyrics_skip_rests_and_support_melisma():
    aligned = align_manual_lyrics(_events(), 100, "你—好，世界")
    pitched = [event for event in aligned if not event["is_rest"]]
    assert [event.get("lyric") for event in pitched] == ["你", None, "好，", "世", "界"]
    assert [event.get("is_lyric_continuation", False) for event in pitched] == [False, True, False, False, False]
    assert aligned[2]["is_rest"] is True


def test_manual_lyrics_keep_english_words_together():
    events = [
        {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60},
        {"start_beat": 1, "duration_beats": 1, "pitch_midi": 62},
    ]
    aligned = align_manual_lyrics(events, 100, "Hello world!")
    assert [event["lyric"] for event in aligned] == ["Hello", "world!"]


def test_manual_lyrics_reject_count_mismatch():
    with pytest.raises(ValueError, match="歌词音节数与可分配音符数不一致"):
        align_manual_lyrics(_events(), 100, "只有三字")


def test_manual_lyrics_reject_melisma_without_previous_syllable():
    events = [{"start_beat": 0, "duration_beats": 1, "pitch_midi": 60}]
    with pytest.raises(ValueError, match="前面必须先有一个实际歌词音节"):
        align_manual_lyrics(events, 100, "—")


def test_manual_lyrics_are_written_into_musicxml(tmp_path):
    events = align_manual_lyrics(
        [
            {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60},
            {"start_beat": 1, "duration_beats": 1, "pitch_midi": 62},
            {"start_beat": 2, "duration_beats": 1, "pitch_midi": 64},
        ],
        100,
        "你—好",
    )
    path = vocalparse_events_to_musicxml(events, 100, tmp_path / "with-lyrics.musicxml")
    aligned = musicxml_lyric_alignment(path)
    assert [item["lyric"] for item in aligned] == ["你", "好"]
    root = ET.parse(path).getroot()
    notes = [node for node in root.iter() if node.tag.endswith("note")]
    lyric_nodes = [next((child for child in note if child.tag.endswith("lyric")), None) for note in notes]
    assert next(child for child in lyric_nodes[0] if child.tag.endswith("extend")).attrib["type"] == "start"
    assert next(child for child in lyric_nodes[1] if child.tag.endswith("extend")).attrib["type"] == "stop"



def test_musicxml_lyric_slots_are_editable_one_per_pitched_note(tmp_path):
    events = align_manual_lyrics(
        [
            {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60},
            {"start_beat": 1, "duration_beats": 1, "pitch_midi": 62},
            {"start_beat": 2, "duration_beats": 1, "is_rest": True},
            {"start_beat": 3, "duration_beats": 1, "pitch_midi": 64},
        ],
        100,
        "你—好",
    )
    path = vocalparse_events_to_musicxml(events, 100, tmp_path / "editable.musicxml")
    slots = read_lyric_slots(path)
    assert len(slots) == 3
    assert [slot["lyric"] for slot in slots] == ["你", "—", "好"]
    assert [slot["index"] for slot in slots] == [0, 1, 2]

    attach_lyrics_to_musicxml(path, ["我", "—", "好"])
    updated = read_lyric_slots(path)
    assert [slot["lyric"] for slot in updated] == ["我", "—", "好"]



def test_vocalparse_musicxml_is_eligible_for_lyric_editing(tmp_path):
    path = vocalparse_events_to_musicxml(
        [
            {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60},
            {"start_beat": 1, "duration_beats": 1, "is_rest": True},
            {"start_beat": 2, "duration_beats": 5, "pitch_midi": 62},
        ],
        100,
        tmp_path / "vocalparse.musicxml",
    )
    assert is_editable_melody_musicxml(path)


def test_chord_musicxml_is_not_eligible_for_lyric_editing(tmp_path):
    path = tmp_path / "chord.musicxml"
    path.write_text(
        """<?xml version="1.0"?>
        <score-partwise version="3.1">
          <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
          <part id="P1"><measure number="1">
            <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
            <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
          </measure></part>
        </score-partwise>""",
        encoding="utf-8",
    )
    assert not is_editable_melody_musicxml(path)


def test_multi_part_musicxml_is_not_eligible_for_lyric_editing(tmp_path):
    path = tmp_path / "multi-part.musicxml"
    path.write_text(
        """<?xml version="1.0"?>
        <score-partwise version="3.1">
          <part-list>
            <score-part id="P1"><part-name>Voice</part-name></score-part>
            <score-part id="P2"><part-name>Accompaniment</part-name></score-part>
          </part-list>
          <part id="P1"><measure number="1">
            <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
          </measure></part>
          <part id="P2"><measure number="1">
            <note><pitch><step>C</step><octave>3</octave></pitch><duration>1</duration></note>
          </measure></part>
        </score-partwise>""",
        encoding="utf-8",
    )
    assert not is_editable_melody_musicxml(path)



def test_timewise_monophonic_musicxml_is_eligible_for_lyric_editing(tmp_path):
    path = tmp_path / "timewise.musicxml"
    path.write_text(
        """<?xml version="1.0"?>
        <score-timewise version="3.1">
          <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
          <measure number="1">
            <part id="P1">
              <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
            </part>
          </measure>
          <measure number="2">
            <part id="P1">
              <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
            </part>
          </measure>
        </score-timewise>""",
        encoding="utf-8",
    )
    assert is_editable_melody_musicxml(path)
