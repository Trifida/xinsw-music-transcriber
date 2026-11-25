from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "musicmaster" / "web" / "static" / "index.html"
SCRIPT = ROOT / "musicmaster" / "web" / "static" / "js" / "full-song-upload.js"


def test_full_song_is_the_default_transcription_input():
    html = HTML.read_text(encoding="utf-8")
    modes = re.findall(
        r'<input[^>]*type="radio"[^>]*name="tr"[^>]*value="([^"]+)"([^>]*)>',
        html,
    )
    checked = [value for value, attrs in modes if re.search(r"\bchecked(?:\s|>|$)", attrs)]
    assert checked == ["full-song"]
    assert 'id="full-song-start"' in html
    assert "开始记谱" in html


def test_queued_full_song_keeps_manual_start_available_for_retry():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "start.hidden = state !== 'queued';" in script
    assert "start.disabled = state !== 'queued' || startRequestInFlight;" in script
    assert "startRequestInFlight" in script
