#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Provision only the CREPE 'full' model required by MusicMaster's default path.

Set CREPE_MODEL_URL to a trusted HTTPS mirror for deployments where GitHub is
not reliably reachable. The URL must point to the upstream-compatible
model-full.h5.bz2 file. The script never silently switches model capacities.
"""
from __future__ import annotations

import bz2
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "vendor" / "crepe" / "crepe"
MODEL = MODEL_DIR / "model-full.h5"
UPSTREAM_MODELS_COMMIT = "bb29b8d99a89924476d112d27ed470e4ac5617c0"
EXPECTED_ARCHIVE_SIZE = 57689301
EXPECTED_GIT_BLOB_SHA1 = "073f07dd696b851136d59c46b777c909502ad9a1"
DEFAULT_URL = f"https://raw.githubusercontent.com/marl/crepe/{UPSTREAM_MODELS_COMMIT}/model-full.h5.bz2"


def main() -> int:
    if MODEL.is_file() and MODEL.stat().st_size > 0:
        print(f"CREPE full model already present: {MODEL.stat().st_size} bytes")
        return 0

    url = os.environ.get("CREPE_MODEL_URL", DEFAULT_URL).strip()
    if not url.lower().startswith("https://"):
        print("ERROR: CREPE_MODEL_URL must use HTTPS.", file=sys.stderr)
        return 2

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    fd, archive_name = tempfile.mkstemp(prefix="crepe-full-", suffix=".bz2", dir=str(MODEL_DIR))
    os.close(fd)
    archive = Path(archive_name)
    tmp_model = MODEL.with_suffix(".h5.part")
    try:
        print("Downloading only CREPE full model (compressed upstream asset ~57.7 MB)...")
        request = urllib.request.Request(url, headers={"User-Agent": "XinsW-MusicMaster-setup/1.0"})
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

        # Verify Git's canonical blob SHA-1 for the pinned immutable upstream asset.
        blob_digest = hashlib.sha1()
        blob_digest.update(
            f"blob {archive.stat().st_size}".encode("ascii") + bytes([0])
        )
        with archive.open("rb") as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                blob_digest.update(chunk)
        if blob_digest.hexdigest() != EXPECTED_GIT_BLOB_SHA1:
            raise RuntimeError(
                f"CREPE model archive integrity check failed: {blob_digest.hexdigest()}"
            )

        digest = hashlib.sha256()
        with bz2.open(archive, "rb") as source, tmp_model.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                target.write(chunk)
        if tmp_model.stat().st_size < 10_000_000:
            raise RuntimeError(f"Decompressed model unexpectedly small: {tmp_model.stat().st_size} bytes")
        tmp_model.replace(MODEL)
        print(f"CREPE full model ready: {MODEL.stat().st_size} bytes; sha256={digest.hexdigest()}")
        return 0
    except Exception as exc:
        tmp_model.unlink(missing_ok=True)
        print(f"ERROR preparing CREPE full model: {exc}", file=sys.stderr)
        return 1
    finally:
        archive.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
