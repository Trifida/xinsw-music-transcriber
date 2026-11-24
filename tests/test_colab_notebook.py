# -*- coding: utf-8 -*-
"""唯一正式 Colab 入口的静态契约测试。"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "notebooks" / "XinsW_Music_Transcriber_Main.ipynb"


def test_single_colab_notebook_is_valid_and_uses_vocalparse_baseline():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    cells = notebook["cells"]
    source = "\n".join(
        line
        for cell in cells
        for line in cell.get("source", [])
    )

    assert "feature/vocalparse-event-musicxml" in source
    assert "vocalparse_tokens_to_events" in source
    assert "vocalparse_events_to_musicxml" in source
    assert "musicxml_roundtrip_errors" in source
    assert "XinsW_Lead_Transcription" in source
    assert "GH_TOKEN" in source
    assert "V2" in source
    assert "CREPE" in source  # 明确标记为非当前主线，而非旧模型入口
    assert "pip install crepe" not in source.lower()
    assert "import crepe" not in source.lower()
    assert "import torchcrepe" not in source.lower()
    assert "from torchcrepe" not in source.lower()
