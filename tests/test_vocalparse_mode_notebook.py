"""Static contract tests for the VocalParse dual-mode experiment notebook."""
import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "notebooks" / "VocalParse_AudioOnly_vs_AudioLyric.ipynb"


def test_dual_mode_notebook_is_valid_and_preserves_controlled_inputs():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4

    code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]
    assert len(code_cells) == 1
    source = "".join(code_cells[0]["source"])

    # Parse the entire cell to catch accidental notebook code-generation errors.
    ast.parse(source)

    assert 'START_SEC = 30.0' in source
    assert 'END_SEC = 55.0' in source
    assert 'SAMPLE_RATE = 16000' in source
    assert 'inference_mode="audio-only"' in source
    assert 'inference_mode="audio-lyric"' in source
    assert 'lyrics=[GROUND_TRUTH_LYRICS]' in source
    assert 'VocalParseTranscriber(' in source
    assert 'clip_sha256' in source
    assert 'VocalParse_Mode_Comparison' in source


def test_dual_mode_notebook_does_not_install_or_download_models():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    source = "".join(
        line
        for cell in notebook["cells"]
        for line in cell.get("source", [])
    )

    lowered = source.lower()
    assert "pip install" not in lowered
    assert "git clone" not in lowered
    assert "torchcrepe" not in lowered
    assert "wget " not in lowered
    assert "混响" in source
    assert "合唱" in source
    assert "ground_truth_claim" in source
