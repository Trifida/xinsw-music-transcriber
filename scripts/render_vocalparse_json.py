"""Render a saved VocalParse JSON result as staff and numbered notation.

Run from the repository root:
    python scripts/render_vocalparse_json.py parsed_result.json output/vocalparse-score

The input JSON must contain the model result keys: bpm, words, pitches, notes.
No model download or audio inference is performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def render_file(
    input_json: str | Path,
    output_dir: str | Path,
    *,
    require_all: bool = True,
) -> dict[str, Path]:
    """Load one saved VocalParse result and render its score artifacts."""
    from musicmaster.core.vocalparse import render_vocalparse_result

    source = Path(input_json)
    if not source.is_file():
        raise FileNotFoundError(f"VocalParse JSON file not found: {source}")

    try:
        parsed: Any = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {source} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError("VocalParse JSON root must be an object.")
    missing = [key for key in ("bpm", "words", "pitches", "notes") if key not in parsed]
    if missing:
        raise ValueError("VocalParse JSON is missing required keys: " + ", ".join(missing))

    return render_vocalparse_result(
        parsed,
        output_dir,
        require_all=require_all,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a saved VocalParse JSON file into five-line staff and jianpu."
    )
    parser.add_argument("input_json", help="Path to saved VocalParse result JSON")
    parser.add_argument("output_dir", help="Directory for MusicXML and score files")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow best-effort output if an optional renderer is unavailable",
    )
    args = parser.parse_args()

    try:
        artifacts = render_file(
            args.input_json,
            args.output_dir,
            require_all=not args.allow_partial,
        )
    except Exception as exc:
        parser.exit(2, f"Rendering failed: {exc}\n")

    print("VocalParse score rendering completed:")
    for name, path in artifacts.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
