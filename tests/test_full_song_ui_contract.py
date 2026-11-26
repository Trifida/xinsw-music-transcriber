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

def test_full_song_task_is_restored_after_page_reload():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "xinsw.fullSong.activeJobId" in script
    assert "window.sessionStorage.getItem" in script
    assert "window.sessionStorage.setItem" in script
    assert "queryJob(false);" in script
def test_failed_replacement_upload_preserves_previous_task():
    script = SCRIPT.read_text(encoding="utf-8")
    submit_start = script.index("submit.addEventListener('click'")
    upload_catch = script.index("上传未成功：")
    assert "var previousJobId = activeJobId;" in script[submit_start:upload_catch]
    assert "if (previousJobId)" in script[upload_catch:]
    assert "saveJobId(previousJobId);" in script[upload_catch:]
    assert "queryJob(false);" in script[upload_catch:]
def test_missing_task_record_clears_stale_recovery_reference():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "error.status = response.status;" in script
    assert "error.status === 404" in script
    assert "saveJobId('');" in script
    assert "这条任务记录已不存在或已过期" in script


def test_old_status_response_cannot_overwrite_a_newer_task():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "var queriedJobId = activeJobId;" in script
    assert "if (queriedJobId !== activeJobId) return;" in script
def test_full_song_upload_reports_real_transfer_progress():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function uploadFullSong(body)" in script
    assert "request.upload.addEventListener('progress'" in script
    assert "event.loaded / event.total" in script
    assert "正在上传完整歌曲：" in script
    assert "request.timeout = 15 * 60 * 1000;" in script
