# -*- coding: utf-8 -*-
"""Guardrails for the single daily-use Google Colab notebook."""
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "notebooks" / "XinsW_Music_Transcriber_Main.ipynb"


def test_colab_notebook_contains_only_the_daily_score_workflow():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    cells = notebook["cells"]
    assert len(cells) == 9
    assert [cell["cell_type"] for cell in cells] == [
        "markdown", "markdown", "code",
        "markdown", "code",
        "markdown", "code",
        "markdown", "code",
    ]

    source = "\n".join(
        line
        for cell in cells
        for line in cell.get("source", [])
    )

    # The daily workflow is Drive -> private GitHub branch -> score backend -> saved MusicXML.
    assert "feature/vocalparse-event-musicxml" in source
    assert "GH_TOKEN" in source
    assert "drive.mount" in source
    assert "MUSICXML_PATH" in source
    assert "restore_20261123T150049_359290Z" in source
    assert "musicmaster.core.render" in source
    assert "formats=('staff', 'jianpu')" in source
    assert "require_all=True" in source
    assert "score_render_" in source

    # Test fixtures, environment inventories and old recognition engines are not daily notebook steps.
    assert "vocalparse_25s_sample.json" not in source
    assert "vocalparse_tokens_to_events" not in source
    assert "torchcrepe" not in source.lower()
    assert "import crepe" not in source.lower()
    assert "pip install crepe" not in source.lower()
    assert "auto_lyrics" not in source
    assert "自动识别歌词" not in source
    assert "Platform:" not in source
    assert "MY_DRIVE.iterdir()" not in source
