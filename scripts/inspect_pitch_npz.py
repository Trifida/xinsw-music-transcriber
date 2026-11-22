"""Safely inspect a saved NumPy .npz pitch-track archive without model inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def inspect_npz(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"NPZ file not found: {source}")

    arrays: dict[str, Any] = {}
    with np.load(source, allow_pickle=False) as archive:
        for key in archive.files:
            try:
                value = archive[key]
            except ValueError as exc:
                arrays[key] = {"readable": False, "reason": str(exc)}
                continue

            item: dict[str, Any] = {
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "size": int(value.size),
            }
            if value.size and np.issubdtype(value.dtype, np.number):
                flat = value.reshape(-1)
                finite = np.isfinite(flat)
                item["finite_count"] = int(finite.sum())
                if finite.any():
                    finite_values = flat[finite]
                    item["min"] = float(finite_values.min())
                    item["max"] = float(finite_values.max())
                    item["sample"] = [
                        float(x) for x in finite_values[:8]
                    ]
                else:
                    item["sample"] = []
            elif value.size:
                item["sample"] = [str(x) for x in value.reshape(-1)[:8]]
            else:
                item["sample"] = []
            arrays[key] = item

    return {
        "file": source.name,
        "format": "numpy_npz",
        "arrays": arrays,
        "notes": [
            "Inspection only: no pitch model is loaded or executed.",
            "Object arrays are not unpickled; allow_pickle remains disabled.",
            "Array names and shapes must be reviewed before choosing conversion keys.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect keys, shapes, dtypes and value ranges in a saved .npz file."
    )
    parser.add_argument("npz_file")
    parser.add_argument("--output-json", help="Optional path to save the inspection report.")
    args = parser.parse_args()
    try:
        report = inspect_npz(args.npz_file)
    except Exception as exc:
        parser.exit(2, f"NPZ inspection failed: {exc}\\n")

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        destination = Path(args.output_json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\\n", encoding="utf-8")
        print(f"Inspection report saved: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
