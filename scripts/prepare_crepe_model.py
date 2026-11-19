#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Provision the CREPE full model in the *installed* package directory.

The CREPE loader resolves model-full.h5 relative to crepe.core.__file__.
Therefore the model must be written beside the installed crepe/core.py,
not into the source checkout's vendor directory.
"""
from __future__ import annotations

import bz2
import hashlib
import importlib.util
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

UPSTREAM_MODELS_COMMIT = "bb29b8d99a89924476d112d27ed470e4ac5617c0"
EXPECTED_ARCHIVE_SIZE = 57689301
EXPECTED_GIT_BLOB_SHA1 = "073f07dd696b851136d59c46b777c909502ad9a1"
DEFAULT_URL = f"https://raw.githubusercontent.com/marl/crepe/{UPSTREAM_MODELS_COMMIT}/model-full.h5.bz2"


def installed_crepe_dir() -> Path:
    """Find the package directory used by the running Python interpreter."""
    spec = importlib.util.find_spec("crepe")
    if spec is None or not spec.origin:
        raise RuntimeError(
            "CREPE package is not installed in this Python environment. "
            "Run the notebook dependency-install cell first."
        )
    package_dir = Path(spec.origin).resolve().parent
    if not (package_dir / "core.py").is_file():
        raise RuntimeError(f"CREPE package path is unexpected: {package_dir}")
    return package_dir


def main(model_dir: Path | None = None) -> int:
    try:
        # The notebook passes the directory of the already-imported crepe.core.
        # This avoids resolving a different package through importlib after pip installs.
        model_dir = Path(model_dir).resolve() if model_dir is not None else installed_crepe_dir()
        if not (model_dir / "core.py").is_file():
            raise RuntimeError(f"CREPE package path is unexpected: {model_dir}")
        print(f"CREPE package directory (authoritative): {model_dir}", flush=True)
    except Exception as exc:
        print(f"ERROR locating installed CREPE package: {exc}", file=sys.stderr)
        return 2

    model = model_dir / "model-full.h5"
    if model.is_file() and model.stat().st_size > 10_000_000:
        print(f"CREPE full model already present: {model} ({model.stat().st_size} bytes)")
        return 0

    url = os.environ.get("CREPE_MODEL_URL", DEFAULT_URL).strip()
    if not url.lower().startswith("https://"):
        print("ERROR: CREPE_MODEL_URL must use HTTPS.", file=sys.stderr)
        return 2

    fd, archive_name = tempfile.mkstemp(prefix="crepe-full-", suffix=".bz2", dir=str(model_dir))
    os.close(fd)
    archive = Path(archive_name)
    tmp_model = model.with_suffix(".h5.part")
    try:
        print(f"CREPE package directory: {model_dir}", flush=True)
        print("Downloading pinned CREPE full model archive (~57.7 MB)...", flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "XinsW-MusicMaster-setup/1.1"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)

        if archive.stat().st_size != EXPECTED_ARCHIVE_SIZE:
            raise RuntimeError(
                f"Unexpected model archive size: {archive.stat().st_size}; "
                f"expected {EXPECTED_ARCHIVE_SIZE}"
            )

        blob_digest = hashlib.sha1()
        blob_digest.update(f"blob {archive.stat().st_size}".encode("ascii") + bytes([0]))
        with archive.open("rb") as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                blob_digest.update(chunk)
        if blob_digest.hexdigest() != EXPECTED_GIT_BLOB_SHA1:
            raise RuntimeError(
                f"CREPE model archive integrity check failed: {blob_digest.hexdigest()}"
            )

        digest = hashlib.sha256()
        with bz2.open(archive, "rb") as source, tmp_model.open("wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                target.write(chunk)

        if tmp_model.stat().st_size < 10_000_000:
            raise RuntimeError(f"Decompressed model unexpectedly small: {tmp_model.stat().st_size} bytes")

        tmp_model.replace(model)
        print(
            f"CREPE full model ready: {model} "
            f"({model.stat().st_size} bytes); sha256={digest.hexdigest()}",
            flush=True,
        )
        return 0
    except Exception as exc:
        tmp_model.unlink(missing_ok=True)
        print(f"ERROR preparing CREPE model: {exc}", file=sys.stderr)
        return 1
    finally:
        archive.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
