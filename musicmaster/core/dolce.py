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
            try:
                _run([rsvg, "-f", "png", "-d", "192", "-p", "192", "-b", "white", "-o",
                      str(destination / png_name), str(svg)], timeout=60)
                if (destination / png_name).is_file():
                    png_files.append(png_name)
            except Exception as exc:  # noqa: BLE001 — SVG remains the source of truth
                print(f"[Dolce] PNG conversion skipped for {name}: {exc}", flush=True)

            page_pdf = destination / f".{svg.stem}.pdf"
            try:
                _run([rsvg, "-f", "pdf", "-o", str(page_pdf), str(svg)], timeout=60)
                if page_pdf.is_file() and page_pdf.stat().st_size > 100:
                    pdf_pages.append(page_pdf)
            except Exception as exc:  # noqa: BLE001 — keep the legacy PDF if conversion fails
                print(f"[Dolce] PDF conversion skipped for {name}: {exc}", flush=True)

    pdf_name: str | None = None
    try:
        # Only replace the legacy PDF when every page converted and the pages can be merged.
        if pdf_pages and len(pdf_pages) == len(svg_files):
            combined = destination / "jianpu-dolce.pdf"
            if len(pdf_pages) == 1:
                shutil.copyfile(pdf_pages[0], combined)
            else:
                pdfunite = shutil.which("pdfunite")
                if pdfunite:
                    try:
                        _run([pdfunite, *[str(p) for p in pdf_pages], str(combined)], timeout=60)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[Dolce] PDF page merge skipped: {exc}", flush=True)
                else:
                    print("[Dolce] pdfunite unavailable; keeping the legacy PDF.", flush=True)

            if combined.is_file() and combined.stat().st_size > 100:
                primary = destination / "jianpu.pdf"
                legacy = destination / "jianpu-lilypond-fallback.pdf"
                if primary.is_file() and not legacy.exists():
                    shutil.copyfile(primary, legacy)
                shutil.copyfile(combined, primary)
                pdf_name = primary.name
    finally:
        for page in pdf_pages:
            page.unlink(missing_ok=True)

    return {
        "page_count": len(svg_files),
        "svg_files": svg_files,
        "png_files": png_files,
        "pdf_file": pdf_name,
    }
