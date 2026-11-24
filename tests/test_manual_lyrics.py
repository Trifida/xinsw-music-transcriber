import pytest

from musicmaster.core.vocalparse import align_manual_lyrics, vocalparse_events_to_musicxml, musicxml_lyric_alignment


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
        align_manual_lyrics(_events(), 100, "只有三个字")


def test_manual_lyrics_reject_melisma_without_previous_syllable():
    events = [{"start_beat": 0, "duration_beats": 1, "pitch_midi": 60}]
    with pytest.raises(ValueError, match="前面必须先有一个实际歌词音节"):
        align_manual_lyrics(events, 100, "—")


def test_manual_lyrics_are_written_into_musicxml(tmp_path):
    events = [
        {"start_beat": 0, "duration_beats": 1, "pitch_midi": 60, "lyric": "你"},
        {"start_beat": 1, "duration_beats": 1, "pitch_midi": 62, "lyric": None, "is_lyric_continuation": True},
        {"start_beat": 2, "duration_beats": 1, "pitch_midi": 64, "lyric": "好"},
    ]
    path = vocalparse_events_to_musicxml(events, 100, tmp_path / "with-lyrics.musicxml")
    aligned = musicxml_lyric_alignment(path)
    assert [item["lyric"] for item in aligned] == ["你", "好"]