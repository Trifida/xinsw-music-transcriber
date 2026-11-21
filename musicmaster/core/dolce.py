"""Dolce headless jianpu engraving adapter.

Dolce owns the notation layout. This module only bridges MusicXML to its
Node headless entry and converts the resulting SVG pages to PNG/PDF with
librsvg when those system tools are available.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "dolce_render.mjs"
DEFAULT_ENTRY = Path("/opt/dolce/out/cli/engrave.js")


def _run(command: list[str], *, timeout: float = 90.0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def render_dolce(
    musicxml: str | Path,
    out_dir: str | Path,
    *,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Render a MusicXML score with Dolce and return generated artifact names.

    SVG is the authoritative Dolce output. PNG/PDF are convenience conversions
    of those exact SVG pages; if librsvg is unavailable, SVG remains available.
    The legacy LilyPond PDF is retained as a fallback if conversion fails.
    """
    source = Path(musicxml).resolve()
    destination = Path(out_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"MusicXML not found: {source}")
    if not SCRIPT.is_file():
        raise RuntimeError(f"Dolce adapter script is missing: {SCRIPT}")

    node = os.environ.get("DOLCE_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is unavailable; Dolce headless renderer is not installed.")

    entry = os.environ.get("DOLCE_CLI_ENTRY")
    if not entry:
        if not DEFAULT_ENTRY.is_file():
            raise RuntimeError("Dolce CLI build is missing at /opt/dolce/out/cli/engrave.js.")
        entry = str(DEFAULT_ENTRY)

    destination.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["DOLCE_CLI_ENTRY"] = entry
    proc = _run([node, str(SCRIPT), str(source), str(destination)], timeout=timeout, env=env)
    try:
        manifest = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Dolce returned invalid output metadata: {proc.stdout[-500:]}") from exc

    names = manifest.get("svg_files")
    if manifest.get("ok") is not True or not isinstance(names, list) or not names:
        raise RuntimeError(f"Dolce did not return SVG pages: {manifest!r}")
    if len(names) > 40:
        raise RuntimeError(f"Dolce produced an unreasonable page count: {len(names)}")

    svg_files: list[str] = []
    png_files: list[str] = []
    pdf_pages: list[Path] = []
    rsvg = shutil.which("rsvg-convert")
    for raw_name in names:
        name = Path(str(raw_name)).name
        if name != str(raw_name) or not name.endswith(".svg"):
            raise RuntimeError(f"Unsafe SVG artifact name from Dolce: {raw_name!r}")
        svg = destination / name
        if not svg.is_file() or svg.stat().st_size < 100:
            raise RuntimeError(f"Dolce SVG page is missing or empty: {name}")
        svg_files.append(name)

        if rsvg:
            png_name = svg.with_suffix(".png").name
            _run([rsvg, "-f", "png", "-d", "192", "-p", "192", "-o",
                  str(destination / png_name), str(svg)], timeout=60)
            png_files.append(png_name)

            page_pdf = destination / f".{svg.stem}.pdf"
            _run([rsvg, "-f", "pdf", "-o", str(page_pdf), str(svg)], timeout=60)
            pdf_pages.append(page_pdf)

    pdf_name: str | None = None
    if pdf_pages:
        combined = destination / "jianpu-dolce.pdf"
        if len(pdf_pages) == 1:
            shutil.copyfile(pdf_pages[0], combined)
        else:
            pdfunite = shutil.which("pdfunite")
            if pdfunite:
                _run([pdfunite, *[str(p) for p in pdf_pages], str(combined)], timeout=60)
            else:
                combined = pdf_pages[0]
        if combined.is_file() and combined.stat().st_size > 100:
            primary = destination / "jianpu.pdf"
            legacy = destination / "jianpu-lilypond-fallback.pdf"
            if primary.is_file() and not legacy.exists():
                shutil.copyfile(primary, legacy)
            shutil.copyfile(combined, primary)
            pdf_name = primary.name
        for page in pdf_pages:
            page.unlink(missing_ok=True)

    return {
        "page_count": len(svg_files),
        "svg_files": svg_files,
        "png_files": png_files,
        "pdf_file": pdf_name,
    }
