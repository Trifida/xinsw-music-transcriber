"""Guardrails for the V1/V2 lyric boundary.

These tests verify that V1's active web and runner paths only accept manual lyrics.
The separate ASR adapter tests are retained as V2 technical-reserve tests.
"""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_v1_transcribe_api_has_no_automatic_lyrics_parameter():
    tree = ast.parse(_source("musicmaster/web/server.py"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "api_transcribe"
    )
    argument_names = [arg.arg for arg in function.args.args]
    assert "lyrics" in argument_names
    assert "auto_lyrics" not in argument_names
    assert "get_asr_status" not in _source("musicmaster/web/server.py")


def test_v1_runner_only_uses_user_provided_lyrics():
    source = _source("musicmaster/web/runners.py")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_transcribe"
    )
    argument_names = [arg.arg for arg in function.args.args]
    assert "lyrics_text" in argument_names
    assert "auto_lyrics" not in argument_names
    assert "transcribe_lyrics" not in source
    assert "lyric_asr" not in source


def test_v1_web_ui_has_manual_lyrics_and_no_asr_toggle():
    html = _source("musicmaster/web/static/index.html")
    js = _source("musicmaster/web/static/js/transcribe.js")
    assert "手动输入 / 粘贴" in html
    assert "V1 只使用你输入的歌词" in html
    assert "自动识别歌词" not in html
    assert "auto-lyrics" not in html
    assert "auto_lyrics" not in js
    assert "auto-lyrics" not in js


def test_v1_health_check_does_not_expose_asr_configuration():
    source = _source("musicmaster/web/server.py")
    assert "lyric_asr" not in source
    assert "get_asr_status" not in source


def test_asr_adapter_is_explicitly_reserved_for_v2():
    source = _source("musicmaster/transcribe/lyric_asr.py")
    assert "V2-only dormant ASR adapter" in source
