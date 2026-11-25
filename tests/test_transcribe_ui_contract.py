from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_transcription_is_the_default_home_panel():
    html = (ROOT / "musicmaster/web/static/index.html").read_text(encoding="utf-8")

    assert html.index('id="tab-transcribe"') < html.index('id="tab-convert"')
    assert 'id="tab-transcribe" role="tab" aria-selected="true"' in html
    assert '<div class="panel active" id="p-transcribe"' in html
    assert '<div class="panel active" id="p-convert"' not in html


def test_full_song_is_the_fourth_sound_type_not_a_separate_mode_tab():
    html = (ROOT / "musicmaster/web/static/index.html").read_text(encoding="utf-8")
    upload_js = (ROOT / "musicmaster/web/static/js/full-song-upload.js").read_text(encoding="utf-8")

    assert 'name="tr" value="crepe"' in html
    assert 'name="tr" value="basic-pitch"' in html
    assert 'name="tr" value="bytedance"' in html
    assert 'name="tr" value="full-song"' in html
    assert 'data-source-mode=' not in html
    assert 'input[name="tr"]' in upload_js
    assert 'id="single-audio-input"' in html
    assert 'id="single-source-fields"' in html
    assert 'id="full-song-fields" hidden' in html
    assert 'id="full-song-file"' in html
    assert 'id="full-song-lyrics"' in html
