# -*- coding: utf-8 -*-
"""Colab 免费临时运行入口的静态契约测试。"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "notebooks" / "XinsW_Colab_Free_v2.ipynb"


def test_colab_notebook_is_valid_and_uses_free_ephemeral_runtime():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    cells = notebook["cells"]
    source = "\n".join(
        line
        for cell in cells
        for line in cell.get("source", [])
    )
    assert "zipball/" in source
    assert "google.colab.kernel.proxyPort(7860)" in source
    assert "MUSICMASTER_HOST" in source
    assert "model-full.h5" in source
    assert "prepare_crepe_model.py" in source
    assert "tensorflow==2.15.0" not in source
    assert "render.com" not in source.lower()
    assert "api_key" not in source.lower()
    assert "xinsw.html" in source
